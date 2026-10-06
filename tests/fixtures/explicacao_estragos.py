"""Saída SINTETICA de uma execução gravada, estragada fora do esquema (T08, auditoria E2).

O `DatasetRef` da saída estragada é reemitido pelas funções de produção (`reemitir`:
`hash_logico_linhas` e `calcular_dataset_id`) e regravado no `run_result.json`. A conferência de
conteúdo passa; só o contrato das colunas e dos valores pode recusar a saída.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.experiment import RunResult
from tests.fixtures.regras_cenario import reemitir

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["ESTRAGOS_FORA_DO_ESQUEMA", "estragar_saida_gravada"]


def _sem_coluna(coluna: str) -> Callable[[pa.Table, str], pa.Table]:
    def estragar(tabela: pa.Table, _row_id: str) -> pa.Table:
        return tabela.drop_columns([coluna])

    return estragar


def _coluna_nao_declarada(tabela: pa.Table, _row_id: str) -> pa.Table:
    """Todas as colunas do esquema e mais uma; o hash lógico não a vê."""
    valores = pa.array(["x"] * tabela.num_rows, pa.string())
    return tabela.append_column("coluna_nao_declarada", valores)


def _parametros_nao_objeto(tabela: pa.Table, _row_id: str) -> pa.Table:
    linhas = [linha | {"parametros": "7"} for linha in tabela.to_pylist()]
    return pa.Table.from_pylist(linhas, tabela.schema)


def _rule_id_nulo(tabela: pa.Table, row_id: str) -> pa.Table:
    """Uma das avaliações do registro sem `rule_id`; as outras ficam como estavam."""
    linhas = tabela.to_pylist()
    alvo = next(i for i, linha in enumerate(linhas) if linha["row_id"] == row_id)
    linhas[alvo] = linhas[alvo] | {"rule_id": None}
    return pa.Table.from_pylist(linhas, tabela.schema)


def _selecao_com_fonte_nula(tabela: pa.Table, row_id: str) -> pa.Table:
    """Segunda seleção da mesma regra do registro, sem `fonte`."""
    linhas = tabela.to_pylist()
    copia = next(linha for linha in linhas if linha["row_id"] == row_id) | {"fonte": None}
    return pa.Table.from_pylist([*linhas, copia], tabela.schema)


ESTRAGOS_FORA_DO_ESQUEMA: dict[str, tuple[str, Callable[[pa.Table, str], pa.Table]]] = {
    "sem_coluna_metodo": ("avaliacoes.v1", _sem_coluna("metodo")),
    "sem_coluna_evidence_ids": ("avaliacoes.v1", _sem_coluna("evidence_ids")),
    "coluna_nao_declarada": ("avaliacoes.v1", _coluna_nao_declarada),
    "parametros_nao_objeto": ("evidencias.v1", _parametros_nao_objeto),
    "rule_id_nulo": ("avaliacoes.v1", _rule_id_nulo),
    "selecao_com_fonte_nula": ("selecao_versoes.v1", _selecao_com_fonte_nula),
}


def estragar_saida_gravada(run_result: Path, estrago: str, row_id: str) -> None:
    """Estraga a saída do `estrago` e regrava `run_result` com o `DatasetRef` reemitido."""
    run = RunResult.model_validate_json(run_result.read_text(encoding="utf-8"))
    schema_id, estragar = ESTRAGOS_FORA_DO_ESQUEMA[estrago]
    ref = next(r for r in run.saidas if r.schema_id == schema_id)
    pq.write_table(estragar(pq.read_table(ref.caminho), row_id), ref.caminho)
    saidas = tuple(reemitir(r) if r.schema_id == schema_id else r for r in run.saidas)
    reemitido = run.model_copy(update={"saidas": saidas})
    run_result.write_text(reemitido.model_dump_json(), encoding="utf-8")
