"""Cadastros do contexto do `validate --ingest`: só entram os que o registro e o corte confirmam."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["CADASTROS_DO_CONTEXTO", "cadastros_aceitos"]

CADASTROS_DO_CONTEXTO = {"cnes_estabelecimento.v1": FamiliaFonte.CNES_ST}


def cadastros_aceitos(
    auxiliares: dict[str, list[DatasetRef]], registro: RegistroTemporal, config: RunConfig
) -> dict[str, list[DatasetRef]]:
    """`auxiliares` sem os conjuntos de cadastro que o registro e o corte não confirmam."""
    raise NotImplementedError(
        f"cadastros_aceitos esquemas={sorted(auxiliares)} versoes={len(registro.versoes)} "
        f"corte={config.corte_observacao}"
    )
