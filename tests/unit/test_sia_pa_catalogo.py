import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from sustemporal.contracts import (
    CodigoCBO,
    CodigoCNES,
    CodigoMunicipio6,
    CodigoProcedimento,
    CodigoRotulo,
    CompetenciaAtendimento,
    CompetenciaProcessamento,
    EsquemaCanonico,
    EstadoIntegridade,
    PapelColuna,
    TipoCanonico,
)
from sustemporal.evaluation.labels import CONTRADICOES
from sustemporal.ingest.dbc import ler_dbc
from sustemporal.ingest.dbf import QuarentenaLeitura
from sustemporal.ingest.sia_pa import CAMPOS_DESCARTADOS, PADROES, casar_leiaute
from sustemporal.yamlio import carregar_yaml
from tests.fixtures.dbf_writer import CampoDbf
from tests.fixtures.sia_pa_fixtures import (
    CAMINHO_CODEBOOK,
    CAMINHO_ESQUEMA,
    campos_pa,
    dbc_pa,
    leiaute_pa,
    registro_pa,
)

ESQUEMA = EsquemaCanonico.de_yaml(CAMINHO_ESQUEMA)
TIPOS = {c.nome: c.tipo for c in ESQUEMA.colunas}
PAPEIS = {c.nome: c.papel for c in ESQUEMA.colunas}
LINHAGEM_INGESTAO = {"row_id", "artifact_id", "membro", "indice_registro", "deletado"}


def test_leiaute_cobre_todas_as_colunas_do_esquema() -> None:
    canonicos = {c.nome_canonico for c in leiaute_pa().campos}
    derivadas = {n for n in TIPOS if PAPEIS[n] in {PapelColuna.BRUTO, PapelColuna.MOTIVO}}
    derivadas |= LINHAGEM_INGESTAO | {"idade_unidade"}
    assert set(TIPOS) - derivadas == canonicos - CAMPOS_DESCARTADOS
    assert canonicos - set(TIPOS) == CAMPOS_DESCARTADOS


def test_leiaute_tem_mesmo_papel_e_tipo_que_o_esquema() -> None:
    for campo in leiaute_pa().campos:
        if campo.nome_canonico in CAMPOS_DESCARTADOS:
            continue
        assert campo.papel is PAPEIS[campo.nome_canonico], campo.nome_fisico
        assert campo.tipo_canonico is TIPOS[campo.nome_canonico], campo.nome_fisico


def test_campos_normalizados_de_texto_tem_padrao() -> None:
    normalizados = {n.removesuffix("_bruto") for n in TIPOS if n.endswith("_bruto")}
    textos = {n for n in normalizados if TIPOS[n] is TipoCanonico.TEXTO}
    assert textos == set(PADROES)


def test_leiaute_marca_so_as_colunas_tardias_como_opcionais() -> None:
    opcionais = [c.nome_fisico for c in leiaute_pa().campos if not c.obrigatorio]
    assert opcionais == [
        "PA_VL_CF",
        "PA_VL_CL",
        "PA_VL_INC",
        "PA_SRV_C",
        "PA_INE",
        "PA_NAT_JUR",
        "PA_FNTORC",
    ]


@pytest.mark.parametrize(
    ("nome", "tipo"),
    [
        ("cnes", CodigoCNES),
        ("municipio_estabelecimento", CodigoMunicipio6),
        ("procedimento", CodigoProcedimento),
        ("cbo", CodigoCBO),
        ("competencia_processamento", CompetenciaProcessamento),
        ("competencia_atendimento", CompetenciaAtendimento),
    ],
)
@given(data=st.data())
def test_padrao_aceita_so_valores_validos_no_contrato(
    nome: str, tipo: object, data: st.DataObject
) -> None:
    valor = data.draw(st.from_regex(PADROES[nome], fullmatch=True))
    TypeAdapter(tipo).validate_python(valor)


def test_codebook_mapeia_para_codigos_de_rotulo_e_vocabulario_fechado() -> None:
    codebook = carregar_yaml(CAMINHO_CODEBOOK)
    assert codebook["codigos"] == {
        "0": "NAO_APROVADO",
        "5": "APROVADO_TOTAL",
        "6": "APROVADO_PARCIAL",
    }
    assert {CodigoRotulo(v) for v in codebook["codigos"].values()} < set(CodigoRotulo)
    assert tuple(sorted(codebook["contradicoes"])) == CONTRADICOES
    assert codebook["proveniencia"] == "SECUNDARIA"
    assert codebook["confirmacao"] == "A_CONFIRMAR"


@pytest.mark.parametrize("n_colunas", [54, 55, 60, 61])
def test_casar_leiaute_aceita_prefixos_com_opcionais(n_colunas: int) -> None:
    cabecalho = ler_dbc(dbc_pa([registro_pa()], n_colunas=n_colunas)).leitura.cabecalho
    casados = casar_leiaute(cabecalho, leiaute_pa())
    assert [c.nome_fisico for c in casados] == [c.nome for c in campos_pa(n_colunas)]


def test_casar_leiaute_aceita_opcional_ausente_no_meio() -> None:
    campos = [c for c in campos_pa(61) if c.nome != "PA_SRV_C"]
    cabecalho = ler_dbc(dbc_pa([registro_pa()], campos=campos)).leitura.cabecalho
    assert "PA_SRV_C" not in [c.nome_fisico for c in casar_leiaute(cabecalho, leiaute_pa())]


@pytest.mark.parametrize(
    "campos",
    [
        campos_pa(53),
        [*campos_pa(60), CampoDbf("PA_NOVO", "C", 1)],
        [CampoDbf("PA_CODUNI", "N", 7), *campos_pa(60)[1:]],
        [*campos_pa(54)[:-1], *campos_pa(60)[54:], campos_pa(54)[-1]],
    ],
)
def test_casar_leiaute_recusa_incompativel(campos: list[CampoDbf]) -> None:
    registro = {**registro_pa(), "PA_NOVO": "x"}
    cabecalho = ler_dbc(dbc_pa([registro], campos=campos)).leitura.cabecalho
    with pytest.raises(QuarentenaLeitura) as erro:
        casar_leiaute(cabecalho, leiaute_pa())
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert re.fullmatch(r"[a-z_]+( [a-z_]+=\S+)*", erro.value.motivo)


def test_casar_leiaute_recusa_leiaute_que_nao_e_dbf() -> None:
    cabecalho = ler_dbc(dbc_pa([registro_pa()])).leitura.cabecalho
    largura_fixa = leiaute_pa().model_copy(update={"formato": "LARGURA_FIXA"})
    with pytest.raises(QuarentenaLeitura) as erro:
        casar_leiaute(cabecalho, largura_fixa)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


@pytest.mark.parametrize(
    ("codificacao", "aceito"),
    [("cp1252", False), ("utf-8", False), ("latin-1", True), ("ISO-8859-1", True)],
)
def test_casar_leiaute_exige_codificacao_latin1(codificacao: str, aceito: bool) -> None:
    cabecalho = ler_dbc(dbc_pa([registro_pa()])).leitura.cabecalho
    layout = leiaute_pa().model_copy(update={"codificacao": codificacao})
    if aceito:
        assert casar_leiaute(cabecalho, layout)
        return
    with pytest.raises(QuarentenaLeitura) as erro:
        casar_leiaute(cabecalho, layout)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
