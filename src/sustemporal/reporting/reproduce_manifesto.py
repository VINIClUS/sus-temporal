"""Manifesto de aquisição como estava no congelamento: o histórico até o `criado_em` (T14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__all__ = ["Recorte", "manifesto_do_congelamento", "observacoes_do_recorte"]


@dataclass(frozen=True)
class Recorte:
    """O que o manifesto atual tem depois do congelamento e a cópia deixou de fora."""

    artefatos: int
    observacoes: int


def manifesto_do_congelamento(raiz_origem: Path, raiz_destino: Path, instante: datetime) -> Recorte:
    raise NotImplementedError("manifesto_do_congelamento")


def observacoes_do_recorte(recorte: Recorte) -> list[str]:
    raise NotImplementedError("observacoes_do_recorte")
