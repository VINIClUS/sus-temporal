"""Identidade, campo a campo, da entrada de validação (`EntradaValidacao`) das regras (T11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts import RunResult
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = ["campos_divergentes", "entrada_da_execucao", "identidades_da_entrada"]


def identidades_da_entrada(entrada: EntradaValidacao) -> dict[str, str]:
    """Identidade de cada campo da entrada, por nome do campo."""
    raise NotImplementedError("freeze_entrada")


def campos_divergentes(congeladas: Mapping[str, str], entrada: EntradaValidacao) -> list[str]:
    """Campos da entrada cuja identidade difere da congelada."""
    raise NotImplementedError("freeze_entrada")


def entrada_da_execucao(entrada: EntradaValidacao, run: RunResult) -> bool:
    """A entrada é a que a execução usou: mesmo `SnapshotSet` e entradas contidas."""
    raise NotImplementedError("freeze_entrada")
