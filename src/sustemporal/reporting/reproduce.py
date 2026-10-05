"""Reprodução offline a partir de originais locais (T14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport, RunConfig


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    """Acrescenta `--saida` ao subcomando `reproduce`."""
    raise NotImplementedError


def reproduce(config: RunConfig, out: Path) -> EvaluationReport:
    """Reexecuta o fluxo congelado e compara hashes lógicos e métricas."""
    raise NotImplementedError


def executar_reproduce(args: argparse.Namespace, config: RunConfig) -> int:
    """`sustemporal reproduce --freeze ID --offline`."""
    raise NotImplementedError
