from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow.parquet as pq
import pytest
from tests.fixtures.dbf_writer import CampoDbf
from tests.fixtures.sia_pa_fixtures import (
    CAMINHO_CODEBOOK,
    CAMINHO_ESQUEMA,
    CAMINHO_ESQUEMA_ROTULOS,
    artefato_pa,
    campos_pa,
    dbc_pa,
    leiaute_pa,
    registro_pa,
)

from sustemporal.contracts import (
    CodigoRotulo,
    DatasetRef,
    EsquemaCanonico,
    EstadoIntegridade,
    OrigemDados,
    PapelColuna,
    RuntimeConfig,
)
from sustemporal.evaluation.labels import label_pa
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.dbf import QuarentenaLeitura
from sustemporal.ingest.sia_pa import normalize_pa, perfil_pa

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, LayoutSpec

ESQUEMA = EsquemaCanonico.de_yaml(CAMINHO_ESQUEMA)
ESQUEMA_ROTULOS = EsquemaCanonico.de_yaml(CAMINHO_ESQUEMA_ROTULOS)


def _saida(tmp_path: Path, nome: str = "saida") -> Path:
    pasta = tmp_path / nome
    pasta.mkdir(exist_ok=True)
    return pasta


def _artefato(
    tmp_path: Path, registros: Sequence[dict[str, str]], **kwargs: Any
) -> ArtifactVersion:
    return artefato_pa(_saida(tmp_path, "artefatos"), dbc_pa(registros, **kwargs))


def _normalizar(
    tmp_path: Path,
    registros: Sequence[dict[str, str]],
    *,
    layout: LayoutSpec | None = None,
    runtime: RuntimeConfig | None = None,
    **kwargs: Any,
) -> tuple[DatasetRef, list[dict[str, Any]]]:
    artefato = _artefato(tmp_path, registros, **kwargs)
    ref = normalize_pa(
        artefato,
        layout or leiaute_pa(),
        _saida(tmp_path),
        runtime=runtime,
        origem_dados=OrigemDados.SINTETICO,
    )
    return ref, pq.read_table(ref.caminho).to_pylist()


def _rotular(tmp_path: Path, ref: DatasetRef) -> tuple[DatasetRef, list[dict[str, Any]]]:
    rotulos = label_pa(ref, CAMINHO_CODEBOOK, _saida(tmp_path, "rotulos"))
    return rotulos, pq.read_table(rotulos.caminho).to_pylist()


def test_preserva_zeros_a_esquerda_em_codigos(tmp_path: Path) -> None:
    registro = registro_pa(
        PA_CODUNI="0000123", PA_PROC_ID="0101010010", PA_UFMUN="012345", PA_CBOCOD="0000A1"
    )
    _, (linha,) = _normalizar(tmp_path, [registro])
    assert linha["cnes"] == "0000123"
    assert linha["procedimento"] == "0101010010"
    assert linha["municipio_estabelecimento"] == "012345"
    assert linha["cbo"] == "0000A1"
    assert linha["cnes_bruto"] == "0000123"
    assert linha["cnes_motivo"] is None


def test_competencias_de_processamento_e_atendimento_distintas(tmp_path: Path) -> None:
    registros = [registro_pa(PA_MVM="201801", PA_CMP="201710"), registro_pa(PA_CMP="")]
    _, linhas = _normalizar(tmp_path, registros)
    assert linhas[0]["competencia_processamento"] == "201801"
    assert linhas[0]["competencia_atendimento"] == "201710"
    assert linhas[1]["competencia_atendimento"] is None
    assert linhas[1]["competencia_atendimento_motivo"] == "VAZIO"
    assert linhas[1]["competencia_atendimento_bruto"] == " " * 6


def test_duplicatas_preservam_multiplicidade(tmp_path: Path) -> None:
    registros = [registro_pa()] * 3 + [registro_pa(PA_CODUNI="0099999")]
    ref, linhas = _normalizar(tmp_path, registros)
    assert ref.linhas == 4
    assert len({linha["row_id"] for linha in linhas}) == 4
    assert [linha["indice_registro"] for linha in linhas] == [0, 1, 2, 3]
    assert ref.multiplicidade is not None
    assert ref.multiplicidade.linhas_totais == 4
    assert ref.multiplicidade.combinacoes_distintas == 2
    assert ref.multiplicidade.max_repeticoes == 3


def test_registros_agregados_bpa_c_preservados_sem_inventar_paciente(tmp_path: Path) -> None:
    registro = registro_pa(PA_DOCORIG="C", PA_QTDPRO="37", PA_QTDAPR="37", PA_IDADE="999")
    ref, (linha,) = _normalizar(tmp_path, [registro])
    assert ref.linhas == 1
    assert linha["instrumento"] == "C"
    assert linha["quantidade_apresentada"] == 37
    assert linha["quantidade_aprovada"] == 37


def test_rotulos_0_5_6(tmp_path: Path) -> None:
    registros = [registro_pa(PA_INDICA=c) for c in ("0", "5", "6")]
    ref, _ = _normalizar(tmp_path, registros)
    _, rotulos = _rotular(tmp_path, ref)
    assert [r["rotulo"] for r in rotulos] == [
        CodigoRotulo.NAO_APROVADO,
        CodigoRotulo.APROVADO_TOTAL,
        CodigoRotulo.APROVADO_PARCIAL,
    ]
    assert [r["pa_indica_bruto"] for r in rotulos] == ["0", "5", "6"]
    assert {r["codebook_id"] for r in rotulos} == {"sia_pa_indica.v1"}


def test_codigo_desconhecido_vira_desconhecido_com_bruto_preservado(tmp_path: Path) -> None:
    registros = [registro_pa(PA_INDICA="9"), registro_pa(PA_INDICA="")]
    ref, _ = _normalizar(tmp_path, registros)
    _, rotulos = _rotular(tmp_path, ref)
    assert [r["rotulo"] for r in rotulos] == [CodigoRotulo.DESCONHECIDO] * 2
    assert [r["pa_indica_bruto"] for r in rotulos] == ["9", " "]


@pytest.mark.parametrize(
    ("campos", "esperadas"),
    [
        (
            {"PA_INDICA": "0", "PA_QTDAPR": "2", "PA_VALAPR": "5.00"},
            "NAO_APROVADO_COM_QUANTIDADE_APROVADA;NAO_APROVADO_COM_VALOR_APROVADO",
        ),
        (
            {"PA_INDICA": "5", "PA_QTDPRO": "3", "PA_QTDAPR": "1", "PA_VALAPR": "4.00"},
            "APROVADO_TOTAL_COM_QUANTIDADE_DIVERGENTE;APROVADO_TOTAL_COM_VALOR_DIVERGENTE",
        ),
        ({"PA_INDICA": "6"}, "APROVADO_PARCIAL_SEM_REDUCAO"),
        (
            {"PA_INDICA": "6", "PA_QTDAPR": "0", "PA_VALAPR": "0.00"},
            "APROVADO_SEM_QUANTIDADE_APROVADA",
        ),
        (
            {"PA_INDICA": "0", "PA_QTDPRO": "1", "PA_QTDAPR": "2", "PA_VALAPR": "11.00"},
            (
                "NAO_APROVADO_COM_QUANTIDADE_APROVADA;NAO_APROVADO_COM_VALOR_APROVADO;"
                "QUANTIDADE_APROVADA_MAIOR_QUE_APRESENTADA;VALOR_APROVADO_MAIOR_QUE_APRESENTADO"
            ),
        ),
        ({"PA_INDICA": "5"}, ""),
        ({"PA_INDICA": "0", "PA_QTDAPR": "", "PA_VALAPR": ""}, ""),
    ],
)
def test_valores_contraditorios_contados_sem_correcao(
    tmp_path: Path, campos: dict[str, str], esperadas: str
) -> None:
    ref, (linha,) = _normalizar(tmp_path, [registro_pa(**campos)])
    _, (rotulo,) = _rotular(tmp_path, ref)
    assert rotulo["contradicoes"] == esperadas
    assert rotulo["pa_indica_bruto"] == campos["PA_INDICA"]
    assert rotulo["quantidade_aprovada"] == linha["quantidade_aprovada"]
    assert rotulo["valor_aprovado"] == linha["valor_aprovado"]


def test_nao_aprovados_e_deletados_nao_sao_filtrados(tmp_path: Path) -> None:
    registros = [registro_pa(PA_INDICA="0"), registro_pa(PA_INDICA="0"), registro_pa()]
    ref, linhas = _normalizar(tmp_path, registros, deletados={1})
    assert ref.linhas == 3
    assert [linha["pa_indica"] for linha in linhas] == ["0", "0", "5"]
    assert [linha["deletado"] for linha in linhas] == [False, True, False]
    rotulos_ref, rotulos = _rotular(tmp_path, ref)
    assert rotulos_ref.linhas == 3
    assert [r["rotulo"] for r in rotulos].count(CodigoRotulo.NAO_APROVADO) == 2


def test_reconciliacao_bruto_canonico_sem_perda(tmp_path: Path) -> None:
    ref, _ = _normalizar(tmp_path, [registro_pa()] * 4, deletados={0, 3})
    assert ref.reconciliacao is not None
    assert ref.reconciliacao.fisicos == 4
    assert ref.reconciliacao.canonicas == 4
    assert ref.reconciliacao.deletados == 2
    assert ref.reconciliacao.quarentena == 0
    assert ref.reconciliacao.excluidas_por_motivo == {}


def test_rotulo_fica_separado_dos_atributos_de_predicao(tmp_path: Path) -> None:
    atributos = set(ESQUEMA.colunas_com_papel(PapelColuna.ATRIBUTO))
    assert "pa_indica" not in atributos
    assert not {"quantidade_aprovada", "valor_aprovado", "valor_apresentado"} & atributos
    assert ESQUEMA_ROTULOS.colunas_com_papel(PapelColuna.ATRIBUTO) == ()
    ref, (linha,) = _normalizar(tmp_path, [registro_pa()])
    _, (rotulo,) = _rotular(tmp_path, ref)
    assert set(rotulo) == {c.nome for c in ESQUEMA_ROTULOS.colunas}
    assert rotulo["row_id"] == linha["row_id"]


def test_dbc_truncado_vai_para_quarentena_sem_dataset(tmp_path: Path) -> None:
    artefato = _artefato(tmp_path, [registro_pa()] * 3, truncar_bytes=10)
    saida = _saida(tmp_path)
    with pytest.raises(QuarentenaLeitura) as erro:
        normalize_pa(artefato, leiaute_pa(), saida, origem_dados=OrigemDados.SINTETICO)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_TRUNCADO
    assert list(saida.iterdir()) == []


def test_artefato_ja_em_quarentena_nao_e_lido(tmp_path: Path) -> None:
    artefato = artefato_pa(
        _saida(tmp_path, "artefatos"),
        dbc_pa([registro_pa()]),
        integridade=EstadoIntegridade.QUARENTENA_CHECKSUM,
    )
    with pytest.raises(QuarentenaLeitura) as erro:
        normalize_pa(artefato, leiaute_pa(), _saida(tmp_path))
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CHECKSUM


@pytest.mark.parametrize("n_colunas", [54, 60, 61])
def test_aceita_leiaute_com_54_60_ou_61_colunas(tmp_path: Path, n_colunas: int) -> None:
    ref, (linha,) = _normalizar(tmp_path, [registro_pa()], n_colunas=n_colunas)
    assert ref.linhas == 1
    if n_colunas == 54:
        assert linha["pa_vl_cf"] is None
        assert linha["pa_vl_cf_bruto"] is None
        assert linha["pa_vl_cf_motivo"] == "DESCONHECIDO"
        assert linha["pa_srv_c"] is None
    else:
        assert linha["pa_vl_cf"] == Decimal("0.00")
        assert linha["pa_vl_cf_motivo"] is None


def _campos_com(alteracao: str) -> list[CampoDbf]:
    campos = campos_pa(60)
    if alteracao == "extra":
        return [*campos, CampoDbf("PA_NOVO", "C", 1)]
    if alteracao == "ordem":
        campos[13], campos[14] = campos[14], campos[13]
        return campos
    if alteracao == "faltando":
        return [c for c in campos if c.nome != "PA_CMP"]
    if alteracao == "largura":
        return [
            CampoDbf(c.nome, c.tipo, 8 if c.nome == "PA_CODUNI" else c.largura, c.decimais)
            for c in campos
        ]
    return campos[::-1]


@pytest.mark.parametrize("alteracao", ["extra", "ordem", "faltando", "largura", "invertido"])
def test_leiaute_incompativel_vai_para_quarentena(tmp_path: Path, alteracao: str) -> None:
    registro = {**registro_pa(), "PA_NOVO": "x"}
    artefato = _artefato(tmp_path, [registro], campos=_campos_com(alteracao))
    with pytest.raises(QuarentenaLeitura) as erro:
        normalize_pa(artefato, leiaute_pa(), _saida(tmp_path))
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


@pytest.mark.parametrize(
    ("campo_fisico", "bruto", "coluna", "motivo"),
    [
        ("PA_SEXO", "0", "sexo", "NAO_APLICAVEL"),
        ("PA_CATEND", "99", "carater_atendimento", "DESCONHECIDO"),
        ("PA_CATEND", "00", "carater_atendimento", "VAZIO"),
        ("PA_CODUNI", "", "cnes", "VAZIO"),
        ("PA_CODUNI", "12A4567", "cnes", "CODIFICACAO_INVALIDA"),
        ("PA_DOCORIG", "X", "instrumento", "CODIFICACAO_INVALIDA"),
        ("PA_MVM", "201813", "competencia_processamento", "CODIFICACAO_INVALIDA"),
        ("PA_QTDPRO", "1.5", "quantidade_apresentada", "CODIFICACAO_INVALIDA"),
        ("PA_VALPRO", "12.345", "valor_apresentado", "CODIFICACAO_INVALIDA"),
        ("PA_TPUPS", "", "tipo_unidade", "VAZIO"),
    ],
)
def test_ausencia_guarda_bruto_e_motivo(
    tmp_path: Path, campo_fisico: str, bruto: str, coluna: str, motivo: str
) -> None:
    _, (linha,) = _normalizar(tmp_path, [registro_pa(**{campo_fisico: bruto})])
    assert linha[coluna] is None
    assert linha[f"{coluna}_motivo"] == motivo
    assert linha[f"{coluna}_bruto"].strip() == bruto


def test_campo_presente_tem_motivo_nulo_e_bruto_sem_aparar(tmp_path: Path) -> None:
    _, (linha,) = _normalizar(tmp_path, [registro_pa(PA_QTDPRO="7", PA_SEXO="M")])
    assert linha["quantidade_apresentada"] == 7
    assert linha["quantidade_apresentada_bruto"] == "7".rjust(11)
    assert linha["quantidade_apresentada_motivo"] is None
    assert linha["sexo"] == "M"
    assert linha["sexo_motivo"] is None


def test_idade_so_convertida_com_unidade_conhecida(tmp_path: Path) -> None:
    _, (com_unidade,) = _normalizar(tmp_path, [registro_pa(PA_IDADE="034")])
    assert com_unidade["idade"] == 34
    assert com_unidade["idade_unidade"] == "ANOS"
    layout = leiaute_pa()
    campos = tuple(
        c.model_copy(update={"unidade": None}) if c.nome_fisico == "PA_IDADE" else c
        for c in layout.campos
    )
    sem_unidade = layout.model_copy(update={"campos": campos})
    _, (linha,) = _normalizar(
        _saida(tmp_path, "b"), [registro_pa(PA_IDADE="034")], layout=sem_unidade
    )
    assert linha["idade"] is None
    assert linha["idade_unidade"] is None
    assert linha["idade_motivo"] == "DESCONHECIDO"
    assert linha["idade_bruto"] == "034"


def test_dinheiro_e_decimal_exato(tmp_path: Path) -> None:
    ref, (linha,) = _normalizar(tmp_path, [registro_pa(PA_VALPRO="1234.56", PA_VALAPR="0.10")])
    assert linha["valor_apresentado"] == Decimal("1234.56")
    assert linha["valor_aprovado"] == Decimal("0.10")
    tipo = pq.read_schema(ref.caminho).field("valor_apresentado").type
    assert str(tipo).startswith("decimal")


def test_esquema_de_saida_segue_o_catalogo_e_descarta_identificadores(tmp_path: Path) -> None:
    ref, (linha,) = _normalizar(tmp_path, [registro_pa()])
    nomes = pq.read_schema(ref.caminho).names
    assert nomes == [c.nome for c in ESQUEMA.colunas]
    assert not {n for n in nomes if any(t in n for t in ("cnpj", "cns", "autoriz", "fntorc"))}
    assert linha["pa_gestao"] == "350000"
    assert linha["pa_racacor"] == "03"


def test_hash_logico_e_linhas_conferem_com_a_relacao(tmp_path: Path) -> None:
    ref, _ = _normalizar(tmp_path, [registro_pa()] * 2 + [registro_pa(PA_INDICA="0")])
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM read_parquet(?)", [ref.caminho])
    assert hash_logico_relacao(con, "t", [c.nome for c in ESQUEMA.colunas]) == ref.hash_logico
    assert con.execute("SELECT count(*) FROM t").fetchone() == (ref.linhas,)


def test_dataset_registra_origem_sintetica_e_artefato(tmp_path: Path) -> None:
    artefato = _artefato(tmp_path, [registro_pa()], deletados={0})
    ref = normalize_pa(artefato, leiaute_pa(), _saida(tmp_path), origem_dados=OrigemDados.SINTETICO)
    assert ref.origem_dados is OrigemDados.SINTETICO
    assert ref.artifact_ids == (artefato.artifact_id,)
    assert ref.schema_id == "sia_pa.v1"
    (linha,) = pq.read_table(ref.caminho).to_pylist()
    assert linha["row_id"] == f"{artefato.artifact_id}#0"
    assert linha["artifact_id"] == artefato.artifact_id
    assert linha["membro"] is None
    assert linha["deletado"] is True


def test_fidelidade_desligada_le_por_arquivo_com_o_mesmo_resultado(tmp_path: Path) -> None:
    registros = [registro_pa(), registro_pa(PA_INDICA="6")]
    completa, _ = _normalizar(tmp_path, registros)
    desligada, _ = _normalizar(
        _saida(tmp_path, "b"), registros, runtime=RuntimeConfig(verificacao_fidelidade="DESLIGADA")
    )
    assert desligada.hash_logico == completa.hash_logico


def test_perfil_por_estrato_reconciliado_inclui_aprovacoes(tmp_path: Path) -> None:
    registros = [
        registro_pa(PA_CMP="201712", PA_DOCORIG="I", PA_INDICA="5"),
        registro_pa(PA_CMP="201712", PA_DOCORIG="C", PA_INDICA="0"),
        registro_pa(PA_CMP="201711", PA_DOCORIG="I", PA_INDICA="6"),
        registro_pa(PA_CMP="", PA_DOCORIG="X", PA_INDICA="9"),
    ]
    ref, _ = _normalizar(tmp_path, registros, deletados={3})
    perfil = perfil_pa(ref, _saida(tmp_path, "perfil"))
    assert perfil.reconciliado
    assert perfil.linhas == 4
    assert set(perfil.totais.values()) == {4}
    linhas = pq.read_table(perfil.caminho).to_pylist()
    atendimento = {
        (item["origem"], item["valor"]): item
        for item in linhas
        if item["dimensao"] == "competencia_atendimento"
    }
    assert atendimento[("CANONICO", "201712")]["linhas"] == 2
    assert atendimento[("CANONICO", None)]["linhas"] == 1
    assert atendimento[("BRUTO", " " * 6)]["linhas"] == 1
    assert atendimento[("CANONICO", "201712")]["indica_5"] == 1
    assert atendimento[("CANONICO", "201712")]["indica_0"] == 1
    assert atendimento[("CANONICO", None)]["indica_outros"] == 1
    assert atendimento[("CANONICO", None)]["deletados"] == 1


def test_label_pa_recusa_dataset_divergente_da_referencia(tmp_path: Path) -> None:
    ref, _ = _normalizar(tmp_path, [registro_pa()] * 2)
    tabela = pq.read_table(ref.caminho)
    pq.write_table(tabela.slice(0, 1), ref.caminho)
    with pytest.raises(ValueError, match="dataset_divergente"):
        label_pa(ref, CAMINHO_CODEBOOK, _saida(tmp_path, "rotulos"))


def test_label_pa_herda_origem_e_artefatos(tmp_path: Path) -> None:
    ref, _ = _normalizar(tmp_path, [registro_pa()] * 2)
    rotulos, linhas = _rotular(tmp_path, ref)
    assert rotulos.schema_id == "sia_pa_rotulos.v1"
    assert rotulos.origem_dados is OrigemDados.SINTETICO
    assert rotulos.artifact_ids == ref.artifact_ids
    assert rotulos.linhas == 2
    assert pq.read_schema(rotulos.caminho).names == [c.nome for c in ESQUEMA_ROTULOS.colunas]
    assert all(linha["contradicoes"] == "" for linha in linhas)
