"""Comando `sustemporal counterfactual --run RUN_ID --row ROW_ID` (T09)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from sustemporal.contracts.config import RunConfig

__all__ = ["diretorio_contrafactual", "executar_counterfactual"]


def diretorio_contrafactual(raiz: Path, run_id: str, row_id: str) -> Path:
    """Diretório derivado só do `run_id` e do `row_id`."""
    raise NotImplementedError


def executar_counterfactual(args: argparse.Namespace, config: RunConfig) -> int:
    """Recompõe o bundle pelo `explain` e os insumos pela execução; publica o resultado."""
    raise NotImplementedError
