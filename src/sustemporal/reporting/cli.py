"""Comando `sustemporal pilot-report`: relatório do piloto de observabilidade (T05)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig

__all__ = ["executar_pilot_report"]


def executar_pilot_report(args: argparse.Namespace, config: RunConfig) -> int:
    """Lê a última execução do `ingest`, seleciona as versões e grava o relatório do piloto."""
    raise NotImplementedError
