"""T04: fontes de referência (SIGTAP) normalizadas a partir de zips sintéticos (SINTETICO)."""

from __future__ import annotations

from contextlib import closing
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.fixtures.sigtap_apoio import (
    leiautes,
    ler_linhas,
    normalizar,
    pacote,
    quarentena,
    runtime,
)
from tests.fixtures.sigtap_zip import (
    COLUNAS,
    ColunaSigtap,
    artefato_sigtap,
    colunas_com_valor,
    membros_tabela,
    pacote_padrao,
    registro_procedimento,
    zip_sigtap,
)

from sustemporal.contracts import (
    EsquemaCanonico,
    EstadoIntegridade,
    LayoutSpec,
    OrigemDados,
)
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.ingest.sigtap import ESQUEMAS, TABELAS, normalize_sigtap

_TIPOS_FISICOS = {"TEXTO": "VARCHAR", "INTEIRO": "BIGINT"}


@pytest.mark.parametrize("tabela", sorted(TABELAS))
def test_dataset_segue_esquema_com_hash_logico_e_tipos_fisicos(tmp_path: Path, tabela: str) -> None:
    dataset = normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), tabela)
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{TABELAS[tabela]}.yaml")
    colunas = [c.nome for c in esquema.colunas]
    assert dataset.schema_id == esquema.schema_id
    assert dataset.origem_dados is OrigemDados.SINTETICO
    with closing(duckdb.connect()) as con:
        con.execute("CREATE TABLE t AS SELECT * FROM read_parquet($c)", {"c": dataset.caminho})
        descricao = con.execute("DESCRIBE t").fetchall()
        assert [str(d[0]) for d in descricao] == colunas
        for linha, coluna in zip(descricao, esquema.colunas, strict=True):
            esperado = _TIPOS_FISICOS.get(coluna.tipo.value, "DECIMAL(")
            assert str(linha[1]).startswith(esperado)
        assert hash_logico_relacao(con, "t", colunas) == dataset.hash_logico
        assert con.execute("SELECT count(*) FROM t").fetchall()[0][0] == dataset.linhas


def test_identificadores_com_zeros_a_esquerda_ficam_texto(tmp_path: Path) -> None:
    dataset = normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_procedimento")
    linhas = ler_linhas(dataset)
    assert sorted(linha["co_procedimento"] for linha in linhas) == [
        "0101010010",
        "0201010020",
        "0301010030",
    ]
    assert {linha["dt_competencia"] for linha in linhas} == {"201801"}
    assert {linha["co_financiamento"] for linha in linhas} == {"06"}
    registro = ler_linhas(normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_registro"))
    assert sorted(linha["co_registro"] for linha in registro) == ["01", "02", "06"]


def test_texto_latin1_preservado_e_vazio_vira_nulo(tmp_path: Path) -> None:
    linhas = ler_linhas(normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_procedimento"))
    assert {linha["no_procedimento"] for linha in linhas} == {"PROCEDIMENTO SINTETICO ÁÉÇ"}
    assert {linha["co_rubrica"] for linha in linhas} == {None}


def test_sentinela_9999_da_idade_vira_nulo_com_motivo_e_bruto(tmp_path: Path) -> None:
    linhas = ler_linhas(normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_procedimento"))
    por_codigo = {linha["co_procedimento"]: linha for linha in linhas}
    sentinela = por_codigo["0201010020"]
    assert sentinela["vl_idade_minima"] is None
    assert sentinela["vl_idade_minima_bruto"] == "9999"
    assert sentinela["vl_idade_minima_motivo"] == "SENTINELA"
    comum = por_codigo["0101010010"]
    assert comum["vl_idade_maxima"] == 1560
    assert comum["vl_idade_maxima_bruto"] == "1560"
    assert comum["vl_idade_maxima_motivo"] is None
    assert por_codigo["0301010030"]["vl_idade_maxima_motivo"] == "SENTINELA"


def test_idade_vazia_ou_invalida_vira_nulo_com_motivo(tmp_path: Path) -> None:
    procedimentos = [
        registro_procedimento("0101010010", "201801", VL_IDADE_MINIMA=""),
        registro_procedimento("0201010020", "201801", VL_IDADE_MINIMA="12A4"),
    ]
    membros = membros_tabela("tb_procedimento", procedimentos)
    linhas = ler_linhas(normalizar(tmp_path, pacote(tmp_path, membros), "tb_procedimento"))
    motivos = {linha["co_procedimento"]: linha["vl_idade_minima_motivo"] for linha in linhas}
    assert motivos == {"0101010010": "VAZIO", "0201010020": "CODIFICACAO_INVALIDA"}
    assert {linha["vl_idade_minima"] for linha in linhas} == {None}
    assert {linha["vl_idade_minima_bruto"] for linha in linhas} == {"    ", "12A4"}


def test_valores_monetarios_sao_decimais_com_casas_implicitas(tmp_path: Path) -> None:
    linhas = ler_linhas(normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_procedimento"))
    por_codigo = {linha["co_procedimento"]: linha for linha in linhas}
    assert por_codigo["0101010010"]["vl_sa"] == Decimal("12.34")
    assert por_codigo["0301010030"]["vl_sh"] == Decimal("0.01")
    assert all(isinstance(linha["vl_sp"], Decimal) for linha in linhas)


def test_mudanca_de_leiaute_valores_com_10_e_12_posicoes_dao_mesmos_valores(
    tmp_path: Path,
) -> None:
    curto = pacote(tmp_path, pacote_padrao(largura_valor=10), geracao="1801101010")
    longo = pacote(tmp_path, pacote_padrao(largura_valor=12), geracao="1801201010")
    a = normalizar(tmp_path, curto, "tb_procedimento")
    b = normalizar(tmp_path, longo, "tb_procedimento")
    assert a.artifact_ids != b.artifact_ids
    sem_linhagem = [{k: v for k, v in x.items() if k != "artifact_id"} for x in ler_linhas(a)]
    assert sem_linhagem == [
        {k: v for k, v in x.items() if k != "artifact_id"} for x in ler_linhas(b)
    ]


@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    centavos=st.integers(min_value=0, max_value=9_999_999_999),
    largura=st.sampled_from([10, 12]),
)
def test_valor_com_casas_implicitas_ida_e_volta(
    tmp_path_factory: pytest.TempPathFactory, centavos: int, largura: int
) -> None:
    pasta = tmp_path_factory.mktemp("valor")
    procedimento = registro_procedimento("0101010010", "201801", VL_SP=str(centavos))
    membros = membros_tabela("tb_procedimento", [procedimento], colunas_com_valor(largura))
    linhas = ler_linhas(normalizar(pasta, pacote(pasta, membros), "tb_procedimento"))
    assert linhas[0]["vl_sp"] == Decimal(centavos).scaleb(-2)


def test_cardinalidade_muitos_para_muitos_sem_multiplicar_linhas(tmp_path: Path) -> None:
    dataset = normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "rl_procedimento_ocupacao")
    pares = sorted(
        (linha["co_procedimento"], linha["co_ocupacao"]) for linha in ler_linhas(dataset)
    )
    assert pares == [
        ("0101010010", "2231F9"),
        ("0101010010", "225125"),
        ("0201010020", "225125"),
        ("0301010030", "322205"),
    ]
    assert dataset.linhas == 4
    assert dataset.multiplicidade is not None
    assert dataset.multiplicidade.max_repeticoes == 1
    assert dataset.reconciliacao is not None
    assert dataset.reconciliacao.fisicos == 4


def test_duplicata_exata_da_relacao_entra_na_reconciliacao(tmp_path: Path) -> None:
    linha = {"CO_PROCEDIMENTO": "0101010010", "CO_REGISTRO": "02", "DT_COMPETENCIA": "201801"}
    outra = {**linha, "CO_REGISTRO": "01"}
    membros = membros_tabela("rl_procedimento_registro", [linha, outra, linha])
    dataset = normalizar(tmp_path, pacote(tmp_path, membros), "rl_procedimento_registro")
    assert dataset.linhas == 2
    assert dataset.reconciliacao is not None
    assert dataset.reconciliacao.fisicos == 3
    assert dict(dataset.reconciliacao.excluidas_por_motivo) == {"duplicata_exata": 1}


def test_chave_repetida_com_conteudo_divergente_vai_para_quarentena(tmp_path: Path) -> None:
    procedimentos = [
        registro_procedimento("0101010010", "201801"),
        registro_procedimento("0101010010", "201801", TP_SEXO="F"),
    ]
    erro = quarentena(tmp_path, membros_tabela("tb_procedimento", procedimentos), "tb_procedimento")
    assert erro.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "chave_repetida" in erro.motivo


def test_componente_ausente_no_zip_e_inconclusivo(tmp_path: Path) -> None:
    membros = pacote_padrao()
    del membros["rl_procedimento_registro.txt"]
    artefato = pacote(tmp_path, membros)
    with pytest.raises(ArquivoAusente, match="membro_ausente"):
        normalizar(tmp_path, artefato, "rl_procedimento_registro")
    assert normalizar(tmp_path, artefato, "tb_procedimento").linhas == 3


def test_leiaute_embutido_ausente_vai_para_quarentena(tmp_path: Path) -> None:
    membros = pacote_padrao()
    del membros["tb_registro_layout.txt"]
    erro = quarentena(tmp_path, membros, "tb_registro")
    assert erro.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert "leiaute_ausente" in erro.motivo


def _sem(tabela: str, nome: str) -> tuple[ColunaSigtap, ...]:
    return tuple(c for c in COLUNAS[tabela] if c.nome != nome)


@pytest.mark.parametrize(
    ("colunas", "motivo"),
    [
        (_sem("rl_procedimento_ocupacao", "CO_OCUPACAO"), "colunas_divergentes"),
        (tuple(reversed(COLUNAS["rl_procedimento_ocupacao"])), "colunas_divergentes"),
    ],
    ids=["coluna_ausente", "ordem_trocada"],
)
def test_leiaute_embutido_divergente_do_catalogo_vai_para_quarentena(
    tmp_path: Path, colunas: tuple[ColunaSigtap, ...], motivo: str
) -> None:
    registro = {
        "CO_PROCEDIMENTO": "0101010010",
        "CO_OCUPACAO": "225125",
        "DT_COMPETENCIA": "201801",
    }
    membros = membros_tabela("rl_procedimento_ocupacao", [registro], colunas)
    erro = quarentena(tmp_path, membros, "rl_procedimento_ocupacao")
    assert erro.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert motivo in erro.motivo


def test_largura_acima_da_maxima_do_catalogo_vai_para_quarentena(tmp_path: Path) -> None:
    procedimento = registro_procedimento("0101010010", "201801")
    membros = membros_tabela("tb_procedimento", [procedimento], colunas_com_valor(14))
    erro = quarentena(tmp_path, membros, "tb_procedimento")
    assert erro.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert "largura_acima_da_maxima" in erro.motivo


def test_registro_truncado_vai_para_quarentena(tmp_path: Path) -> None:
    membros = pacote_padrao()
    membros["rl_procedimento_ocupacao.txt"] = membros["rl_procedimento_ocupacao.txt"][:-5]
    erro = quarentena(tmp_path, membros, "rl_procedimento_ocupacao")
    assert erro.estado is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_tabela_vazia_vai_para_quarentena_e_nao_vira_ausencia(tmp_path: Path) -> None:
    membros = {**pacote_padrao(), **membros_tabela("rl_procedimento_ocupacao", [])}
    erro = quarentena(tmp_path, membros, "rl_procedimento_ocupacao")
    assert erro.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "tabela_vazia" in erro.motivo


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("CO_PROCEDIMENTO", "010101001 "), ("CO_OCUPACAO", "2231f9"), ("DT_COMPETENCIA", "201813")],
)
def test_codigo_fora_do_dominio_vai_para_quarentena(tmp_path: Path, campo: str, valor: str) -> None:
    registro = {
        "CO_PROCEDIMENTO": "0101010010",
        "CO_OCUPACAO": "225125",
        "DT_COMPETENCIA": "201801",
    }
    membros = membros_tabela("rl_procedimento_ocupacao", [{**registro, campo: valor}])
    erro = quarentena(tmp_path, membros, "rl_procedimento_ocupacao")
    assert erro.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "codigo_invalido" in erro.motivo


def test_dt_competencia_diferente_da_do_arquivo_vai_para_quarentena(tmp_path: Path) -> None:
    erro = quarentena(tmp_path, pacote_padrao("201712"), "tb_registro")
    assert erro.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "competencia_divergente" in erro.motivo


def test_numero_invalido_em_atributo_vai_para_quarentena(tmp_path: Path) -> None:
    procedimento = registro_procedimento("0101010010", "201801", QT_PONTOS="1X")
    erro = quarentena(
        tmp_path, membros_tabela("tb_procedimento", [procedimento]), "tb_procedimento"
    )
    assert "numero_invalido" in erro.motivo


def test_versoes_da_mesma_competencia_sao_artefatos_distintos(tmp_path: Path) -> None:
    primeira = pacote(tmp_path, pacote_padrao(), geracao="1801101010")
    membros = pacote_padrao()
    membros["tb_registro.txt"] += membros["tb_registro.txt"].replace(b"06APAC", b"07APAC")[-60:]
    segunda = pacote(tmp_path, membros, geracao="1802051200")
    a = normalizar(tmp_path, primeira, "tb_registro")
    b = normalizar(tmp_path, segunda, "tb_registro")
    assert a.artifact_ids != b.artifact_ids
    assert a.dataset_id != b.dataset_id
    assert (a.linhas, b.linhas) == (3, 4)
    assert {linha["artifact_id"] for linha in ler_linhas(a)} == {primeira.artifact_id}


@pytest.mark.parametrize(
    "estado", [EstadoIntegridade.QUARENTENA_TRUNCADO, EstadoIntegridade.NAO_VERIFICADO]
)
def test_artefato_nao_integro_vai_para_quarentena(
    tmp_path: Path, estado: EstadoIntegridade
) -> None:
    artefato = artefato_sigtap(tmp_path, zip_sigtap(pacote_padrao()), integridade=estado)
    with pytest.raises(QuarentenaLeitura) as erro:
        normalizar(tmp_path, artefato, "tb_registro")
    assert erro.value.estado is estado


def test_conteudo_alterado_apos_registro_vai_para_quarentena_de_checksum(tmp_path: Path) -> None:
    artefato = pacote(tmp_path, pacote_padrao())
    caminho = Path(artefato.caminho_conteudo)
    caminho.write_bytes(zip_sigtap(pacote_padrao("201802")))
    with pytest.raises(QuarentenaLeitura) as erro:
        normalizar(tmp_path, artefato, "tb_registro")
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CHECKSUM


def test_caminho_fora_da_raiz_de_dados_vai_para_quarentena(tmp_path: Path) -> None:
    artefato = pacote(tmp_path / "outra", pacote_padrao())
    with pytest.raises(QuarentenaLeitura) as erro:
        normalizar(tmp_path / "dados", artefato, "tb_registro")
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO


def test_conteudo_ausente_e_inconclusivo(tmp_path: Path) -> None:
    artefato = pacote(tmp_path, pacote_padrao())
    Path(artefato.caminho_conteudo).unlink()
    with pytest.raises(ArquivoAusente):
        normalizar(tmp_path, artefato, "tb_registro")


def test_membro_acima_do_limite_descomprimido_vai_para_quarentena(tmp_path: Path) -> None:
    artefato = pacote(tmp_path, pacote_padrao())
    with pytest.raises(QuarentenaLeitura) as erro:
        normalizar(tmp_path, artefato, "tb_procedimento", limite_membro_bytes=100)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "membro_excede_limite" in erro.value.motivo


@pytest.mark.parametrize(
    "sobrescrita",
    [{"layout_id": "sigtap.tb_inexistente"}, {"fonte": "SIA_PA"}, {"formato": "DBF"}],
    ids=["tabela_desconhecida", "outra_fonte", "formato_dbf"],
)
def test_leiaute_que_nao_e_tabela_sigtap_vai_para_quarentena(
    tmp_path: Path, sobrescrita: dict[str, str]
) -> None:
    artefato = pacote(tmp_path, pacote_padrao())
    estranho = LayoutSpec.model_validate({**leiautes()["tb_registro"].model_dump(), **sobrescrita})
    with pytest.raises(QuarentenaLeitura) as erro:
        normalize_sigtap(artefato, estranho, tmp_path, runtime=runtime(tmp_path))
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE
