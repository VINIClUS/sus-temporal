"""Comando `sustemporal explain --run RUN_ID --row ROW_ID`."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from sustemporal.contracts.config import RunConfig


def diretorio_explicacao(raiz: Path, run_id: str, row_id: str) -> Path:
    raise NotImplementedError


def executar_explain(args: argparse.Namespace, config: RunConfig) -> int:
    raise NotImplementedError
