"""Escritor DBF dBASE III determinístico, só para testes (SINTETICO)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

TIPOS_SUPORTADOS = frozenset("CNDL")


@dataclass(frozen=True)
class CampoDbf:
    nome: str
    tipo: str
    largura: int
    decimais: int = 0


def escrever_dbf(
    campos: Sequence[CampoDbf],
    registros: Sequence[Sequence[str | bytes]],
    *,
    deletados: Collection[int] = (),
    byte_driver: int = 0x00,
    data: tuple[int, int, int] = (2026, 1, 1),
    com_eof: bool = True,
    truncar_bytes: int = 0,
) -> bytes:
    """Monta um DBF dBASE III em memória; valores em latin-1, sem conversão."""
    raise NotImplementedError
