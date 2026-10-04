"""Conteúdo lido conferido contra o DatasetRef (linhas e hash lógico) — cenários SINTETICOS."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, tabela
from tests.fixtures.regras_exemplos import cenario_base, registro

if TYPE_CHECKING:
    from sustemporal.contracts.records import DatasetRef

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"


def _remover_primeira(tabela_pa: pa.Table) -> pa.Table:
    return tabela_pa.slice(1)


def _alterar_primeira(tabela_pa: pa.Table, coluna: str) -> pa.Table:
    valores = tabela_pa.column(coluna).to_pylist()
    valores[0] = "999999"
    indice = tabela_pa.schema.get_field_index(coluna)
    return tabela_pa.set_column(indice, coluna, pa.array(valores, type=pa.string()))


def _duplicar_primeira(tabela_pa: pa.Table) -> pa.Table:
    return pa.concat_tables([tabela_pa, tabela_pa.slice(0, 1)])


def _executar(tmp_path: Path, schema_id: str, mudar: Callable[[pa.Table], pa.Table]) -> RunResult:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    entradas: list[DatasetRef | None] = [
        dataset,
        *insumos.auxiliares,
        insumos.selecoes,
        insumos.cobertura,
    ]
    alvo = next(d for d in entradas if d is not None and d.schema_id == schema_id)
    pq.write_table(mudar(pq.read_table(alvo.caminho)), alvo.caminho)
    return evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )


@pytest.mark.parametrize(
    "mudar",
    [
        _remover_primeira,
        lambda t: _alterar_primeira(t, "co_ocupacao"),
        _duplicar_primeira,
    ],
    ids=["linha_removida", "linha_alterada", "linha_extra"],
)
def test_auxiliar_divergente_e_falha_da_regra(
    tmp_path: Path, mudar: Callable[[pa.Table], pa.Table]
) -> None:
    resultado = _executar(tmp_path, "sigtap_proc_ocupacao.v1", mudar)
    assert resultado.estado is EstadoExecucao.PARCIAL
    falhas = tabela(resultado, "falhas.v1")
    assert [(f["etapa"], f["rule_id"]) for f in falhas] == [("avaliar_regra", PROC)]
    assert "conteudo_divergente schema=sigtap_proc_ocupacao.v1" in falhas[0]["erro"]
    avaliacoes = avaliacoes_por_chave(resultado)
    assert (LINHA, PROC) not in avaliacoes
    assert avaliacoes[(LINHA, "VIGENCIA_PROCEDIMENTO_SIGTAP")]["estado"] == "CONFORME"


@pytest.mark.parametrize("schema_id", ["sia_pa.v1", "selecao_versoes.v1", "cobertura.v1"])
def test_insumo_principal_ou_cobertura_divergente_e_falha_de_carga(
    tmp_path: Path, schema_id: str
) -> None:
    resultado = _executar(tmp_path, schema_id, _duplicar_primeira)
    assert resultado.estado is EstadoExecucao.FALHOU
    falha = tabela(resultado, "falhas.v1")[0]
    assert falha["etapa"] == "carregar_insumos"
    assert f"conteudo_divergente schema={schema_id}" in falha["erro"]
    assert tabela(resultado, "avaliacoes.v1") == []


def test_evidencia_cita_o_hash_do_conteudo_verificado(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    hashes = {d.dataset_id: d.hash_logico for d in (dataset, *insumos.auxiliares)}
    for evidencia in tabela(resultado, "evidencias.v1"):
        assert hashes[evidencia["dataset_id"]] == evidencia["hash_logico"]


def test_insumos_sem_divergencia_seguem_normalmente(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    assert isinstance(insumos, InsumosAvaliacao)
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.CONCLUIDA
