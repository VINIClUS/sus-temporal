"""Comando `sustemporal validate`: mesmo motor, só a política temporal muda."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig

__all__ = ["configurar_parser", "executar_validate"]


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--saida", type=Path, default=None)


def executar_validate(args: argparse.Namespace, config: RunConfig) -> int:
    """`--policy documented|atendimento|processamento` → M_TEMP|B_ATEND|B_PROC."""
    raise NotImplementedError
