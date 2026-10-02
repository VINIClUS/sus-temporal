"""Chaves nulas, cobertura incompleta e hash do SQL executado (cenários SINTETICOS)."""

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.rules import engine
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, tabela
from tests.fixtures.regras_exemplos import cenario_base, registro

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"


def _anular_primeira(caminho: str, coluna: str) -> None:
    tabela_pa = pq.read_table(caminho)
    valores = tabela_pa.column(coluna).to_pylist()
    valores[0] = None
    indice = tabela_pa.schema.get_field_index(coluna)
    nova = tabela_pa.set_column(indice, coluna, pa.array(valores, type=pa.string()))
    pq.write_table(nova, caminho)


def _avaliar(tmp_path: Path, schema_id: str, coluna: str) -> RunResult:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    entradas = [dataset, insumos.selecoes, insumos.cobertura]
    alvo = next(d for d in entradas if d is not None and d.schema_id == schema_id)
    _anular_primeira(alvo.caminho, coluna)
    return engine.evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )


@pytest.mark.parametrize(
    ("schema_id", "coluna"),
    [
        ("sia_pa.v1", "row_id"),
        ("selecao_versoes.v1", "row_id"),
        ("selecao_versoes.v1", "rule_id"),
        ("selecao_versoes.v1", "fonte"),
    ],
)
def test_chave_nula_em_tabela_de_entrada_e_falha_de_carga(
    tmp_path: Path, schema_id: str, coluna: str
) -> None:
    resultado = _avaliar(tmp_path, schema_id, coluna)
    assert resultado.estado is EstadoExecucao.FALHOU
    falha = tabela(resultado, "falhas.v1")[0]
    assert (falha["etapa"], "chave_nula" in falha["erro"]) == ("carregar_insumos", True)


@pytest.mark.parametrize("coluna", ["familia_regra", "instrumento", "competencia", "base_temporal"])
def test_cobertura_com_chave_nula_nao_e_utilizavel(tmp_path: Path, coluna: str) -> None:
    resultado = _avaliar(tmp_path, "cobertura.v1", coluna)
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_cobertura_sem_coluna_nao_e_utilizavel(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    assert insumos.cobertura is not None
    caminho = insumos.cobertura.caminho
    pq.write_table(pq.read_table(caminho).drop_columns(["estado"]), caminho)
    resultado = engine.evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_hash_da_evidencia_e_o_do_sql_executado(tmp_path: Path) -> None:
    regras = {regra.rule_id: regra for regra in carregar_regras()}
    resultado = executar(tmp_path, cenario_base(registro(0), registro(1, instrumento="Z")))
    evidencias = {e["evidence_id"]: e for e in tabela(resultado, "evidencias.v1")}
    for avaliacao in tabela(resultado, "avaliacoes.v1"):
        consulta = engine.montar_consulta(regras[avaliacao["rule_id"]])
        esperado = hashlib.sha256(consulta.encode("utf-8")).hexdigest()
        assert evidencias[avaliacao["evidence_ids"]]["sql_sha256"] == esperado
