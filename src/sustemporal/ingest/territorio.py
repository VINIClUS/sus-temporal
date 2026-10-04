"""Carga e checagem do território do piloto (catálogo SECUNDARIA, A_CONFIRMAR)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import Territorio

__all__ = ["carregar_territorio", "municipios_ibge6"]


def carregar_territorio(caminho: Path, *, uf: str) -> Territorio:
    """Território validado: contrato, UF do piloto e dígito verificador do IBGE7."""
    raise NotImplementedError


def municipios_ibge6(territorio: Territorio) -> frozenset[str]:
    """Códigos IBGE de 6 dígitos dos municípios (os do DATASUS)."""
    raise NotImplementedError
