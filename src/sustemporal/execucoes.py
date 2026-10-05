"""Lugar único das execuções do `validate` e leitor comum do `run_result.json`.

`validate` (`--entrada` e `--ingest`) grava cada execução em `<raiz_saidas>/runs/<run_id>/` por
padrão e os consumidores (`explain`, `counterfactual`) só a descobrem ali, pelo `run_id` exato e
nunca pela mais recente. `validate --saida` desvia a gravação; uma execução fora de `runs/` não é
encontrada por eles.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult

__all__ = [
    "DIRETORIO_EXECUCOES",
    "ExecucaoNaoResolvida",
    "ler_execucao",
    "raiz_execucoes",
    "validar_run_id",
]

DIRETORIO_EXECUCOES = "runs"


class ExecucaoNaoResolvida(ValueError):
    """`run_id` fora do formato, ou sem `run_result.json` exato, legível e coerente."""


def raiz_execucoes(config: RunConfig) -> Path:
    """Raiz das execuções: `<raiz_saidas>/runs`."""
    return Path(config.runtime.raiz_saidas) / DIRETORIO_EXECUCOES


def validar_run_id(run_id: str) -> str:
    """`run_id` no formato de identificador e que não aponta para fora da raiz (`.`, `..`)."""
    raise NotImplementedError


def ler_execucao(raiz: Path, run_id: str) -> RunResult:
    """`RunResult` gravado em `<raiz>/<run_id>/run_result.json`; nunca a execução mais recente."""
    raise NotImplementedError
