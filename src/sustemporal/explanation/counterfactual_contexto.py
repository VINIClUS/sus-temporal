"""Insumos da execução avaliada que a busca de contrafactuais revalida (T09)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts import DatasetRef, RuleSpec, SnapshotSet
    from sustemporal.rules.insumos import InsumosAvaliacao

__all__ = ["ContextoContrafactual"]


def _agora() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ContextoContrafactual:
    """Conjunto SIA-PA, seleção, regras e insumos com que o motor avaliou o registro.

    `cadastros`: conjuntos `cnes_*` lidos só pelas precondições (CNES ST, por exemplo), além dos
    auxiliares das regras. `competencia_aberta_cnes`: competência que evidência atual mostra aberta
    no CNES; `None` quando só há fontes históricas. Os arquivos nunca são alterados: a busca
    trabalha numa cópia em diretório temporário.
    """

    dataset: DatasetRef
    snapshots: SnapshotSet
    regras: tuple[RuleSpec, ...]
    insumos: InsumosAvaliacao
    cadastros: tuple[DatasetRef, ...] = ()
    competencia_aberta_cnes: str | None = None
    relogio: Callable[[], datetime] = _agora
