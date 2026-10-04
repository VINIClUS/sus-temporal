"""Comandos `sustemporal freeze` e `sustemporal evaluate --freeze FREEZE_ID` (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.runtime_info import versao_codigo

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import RunConfig

__all__ = ["executar_evaluate", "executar_freeze", "versao_codigo"]


def executar_freeze(args: argparse.Namespace, config: RunConfig) -> int:
    """Congela o protocolo a partir do split e das entradas em `<raiz_saidas>/split`."""
    raise NotImplementedError


def executar_evaluate(args: argparse.Namespace, config: RunConfig) -> int:
    """Avalia as execuções do congelamento e acrescenta o resultado ao registro."""
    raise NotImplementedError
