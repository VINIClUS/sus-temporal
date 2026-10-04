"""Comando `sustemporal ingest`: normaliza as versões do manifesto e gera a cobertura (T04)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig

__all__ = ["executar_ingest"]


def executar_ingest(args: argparse.Namespace, config: RunConfig) -> int:
    """Normaliza cada versão do manifesto de aquisição pela família e grava a cobertura."""
    raise NotImplementedError
