"""Comando `sustemporal annotation-export --freeze FREEZE_ID` (T12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import RunConfig

__all__ = ["executar_annotation_export"]


def executar_annotation_export(args: argparse.Namespace, config: RunConfig) -> int:
    """Resolve o congelamento exato e exporta amostra, pacote cego e formulário."""
    raise NotImplementedError
