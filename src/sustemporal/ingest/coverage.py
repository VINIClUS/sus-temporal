"""Matriz de cobertura família × instrumento × competência × base temporal (T04, `cobertura.v1`)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import OrigemDados

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sustemporal.contracts import DatasetRef, RuntimeConfig

__all__ = ["CATALOGO_FAMILIAS", "CORRESPONDENCIA_DOCORIG_REGISTRO", "build_coverage"]

CATALOGO_FAMILIAS = Path(__file__).resolve().parents[3] / "catalog" / "familias.yaml"
# PA_DOCORIG → CO_REGISTRO do SIGTAP: INFERIDA dos rótulos (catalog/familias.yaml); A_CONFIRMAR.
CORRESPONDENCIA_DOCORIG_REGISTRO = {
    "C": "01",
    "I": "02",
    "P": "06",
    "S": "07",
    "A": "08",
    "B": "09",
}


def build_coverage(
    sia_pa: Sequence[DatasetRef],
    auxiliares: Sequence[DatasetRef],
    competencias: Sequence[str],
    out: Path,
    *,
    familias: Path = CATALOGO_FAMILIAS,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.SINTETICO,
) -> DatasetRef:
    """Matriz completa de cobertura a partir das tabelas efetivamente carregadas."""
    raise NotImplementedError
