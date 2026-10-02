"""Achados do Codex no PR #8 (cenários SINTETICOS)."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.contracts.temporal import MetodoId
from sustemporal.rules import saidas
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import materializar, politica, reemitir_insumo, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, tabela
from tests.fixtures.regras_exemplos import ART_SIGTAP, cenario_base, registro, selecao

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"


def _falha_de_selecao(resultado: RunResult) -> None:
    assert resultado.estado is EstadoExecucao.FALHOU
    assert tabela(resultado, "avaliacoes.v1") == []
    falhas = tabela(resultado, "falhas.v1")
    assert [f["etapa"] for f in falhas] == ["conferir_selecao"]
    assert "selecao_incoerente_com_politica" in falhas[0]["erro"]


def test_selecao_de_outra_base_e_recusada(tmp_path: Path) -> None:
    cenario = cenario_base().com(politica=politica(MetodoId.B_PROC))
    _falha_de_selecao(executar(tmp_path, cenario))


def test_selecao_de_outra_competencia_e_recusada(tmp_path: Path) -> None:
    cenario = cenario_base(registro(competencia_atendimento="202003"))
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), competencia="202001") for s in cenario.selecoes
    )
    _falha_de_selecao(executar(tmp_path, cenario.com(selecoes=selecoes)))


def test_politica_nao_resolvida_recusa_selecao_resolvida(tmp_path: Path) -> None:
    cenario = cenario_base().com(politica=politica(MetodoId.M_TEMP))
    _falha_de_selecao(executar(tmp_path, cenario))


def test_selecao_coerente_com_b_proc_e_avaliada(tmp_path: Path) -> None:
    cenario = cenario_base(registro(competencia_atendimento="201912"))
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), base="PROCESSAMENTO") for s in cenario.selecoes
    )
    resultado = executar(
        tmp_path, cenario.com(selecoes=selecoes, politica=politica(MetodoId.B_PROC))
    )
    assert resultado.falhas == 0
    assert avaliacoes_por_chave(resultado)[(LINHA, PROC)]["estado"] == "CONFORME"


@pytest.mark.parametrize("cbo", ["225125", "999999"])
def test_versao_auxiliar_em_quarentena_nunca_sustenta_conforme_nem_violacao(
    tmp_path: Path, cbo: str
) -> None:
    cenario = cenario_base(registro(cbo=cbo))
    cenario = cenario.com(
        integridade=cenario.integridade | {ART_SIGTAP: EstadoIntegridade.QUARENTENA_CHECKSUM}
    )
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "ARQUIVO_EM_QUARENTENA")


def test_versao_auxiliar_nao_verificada_admite_conforme(tmp_path: Path) -> None:
    cenario = cenario_base()
    cenario = cenario.com(
        integridade=cenario.integridade | {ART_SIGTAP: EstadoIntegridade.NAO_VERIFICADO}
    )
    assert avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]["estado"] == "CONFORME"


def _reescrever_inteiro(caminho: str, coluna: str, valor: int) -> None:
    tabela_pa = pq.read_table(caminho)
    indice = tabela_pa.schema.get_field_index(coluna)
    numeros = pa.array([valor] * tabela_pa.num_rows, type=pa.int64())
    pq.write_table(tabela_pa.set_column(indice, coluna, numeros), caminho)


@pytest.mark.parametrize(
    ("coluna", "valor"), [("procedimento", 301010072), ("cnes", 1234567), ("cbo", 225125)]
)
def test_codigo_numerico_no_sia_e_falha_de_carga(tmp_path: Path, coluna: str, valor: int) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    _reescrever_inteiro(dataset.caminho, coluna, valor)
    dataset, insumos = reemitir_insumo(dataset, insumos, "sia_pa.v1")
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.FALHOU
    falhas = tabela(resultado, "falhas.v1")
    assert falhas[0]["etapa"] == "carregar_insumos"
    assert "tipo_incompativel" in falhas[0]["erro"]


def test_codigo_numerico_no_auxiliar_e_leiaute_incompativel(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    ocupacao = next(d for d in insumos.auxiliares if d.schema_id == "sigtap_proc_ocupacao.v1")
    _reescrever_inteiro(ocupacao.caminho, "co_ocupacao", 225125)
    dataset, insumos = reemitir_insumo(dataset, insumos, "sigtap_proc_ocupacao.v1")
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "LEIAUTE_INCOMPATIVEL")


def test_cobertura_com_competencia_numerica_nunca_fica_disponivel(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    assert insumos.cobertura is not None
    _reescrever_inteiro(insumos.cobertura.caminho, "competencia", 202001)
    dataset, insumos = reemitir_insumo(dataset, insumos, "cobertura.v1")
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_evidencia_rejeitada_nao_e_gravada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = saidas.Evidence

    def recusar_aplicabilidade(**campos: object) -> object:
        if campos["tipo"] == "APLICABILIDADE":
            raise ValueError("evidencia_sintetica_invalida")
        return original(**campos)

    monkeypatch.setattr(saidas, "Evidence", recusar_aplicabilidade)
    resultado = executar(tmp_path, cenario_base(registro(0), registro(1, instrumento="Z")))
    assert {e["tipo"] for e in tabela(resultado, "evidencias.v1")} == {"VINCULO_ENCONTRADO"}
    assert all(a["estado"] != "NAO_APLICAVEL" for a in tabela(resultado, "avaliacoes.v1"))
    assert {f["etapa"] for f in tabela(resultado, "falhas.v1")} >= {"validar_evidencia"}
