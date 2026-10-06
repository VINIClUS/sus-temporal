"""Varredura do que a cadeia do `reproduce` lê: de onde vem cada campo e como se confere (T14).

A reprodução tem de refazer o que foi registrado, e o que ela não consegue conferir sai
INCONCLUSIVO. Cada campo do `FreezeManifest` e da config (inclusive os de `runtime` e `piloto`)
tem aqui o tratamento: a fonte da verdade, como a diferença aparece e o efeito. Um teste percorre
os campos dos contratos e falha se um campo novo ficar sem tratamento, como em
`freeze_conferencia.CAMPOS_DO_MANIFESTO`; campo lido e não conferido é limite declarado (T14-16),
com efeito conservador: divergência ou inconclusão, nunca reprodução falsa.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "CAMPOS_DA_CONFIG",
    "CAMPOS_DO_CONGELAMENTO",
    "Conferencia",
    "Fonte",
    "Tratamento",
]


class Fonte(StrEnum):
    """De onde vem o valor que a reprodução usa."""

    CONGELAMENTO = "CONGELAMENTO"
    REGISTRO = "REGISTRO"
    ORIGINAL = "ORIGINAL"
    CODIGO = "CODIGO"
    CONFIG = "CONFIG"
    NENHUMA = "NENHUMA"


class Conferencia(StrEnum):
    """Como a diferença aparece no `reproducao.json`."""

    ITEM = "ITEM"
    OBSERVACAO = "OBSERVACAO"
    INDIRETA = "INDIRETA"
    RECUSA = "RECUSA"
    NENHUMA = "NENHUMA"


@dataclass(frozen=True)
class Tratamento:
    fonte: Fonte
    conferencia: Conferencia
    efeito: str


def _t(fonte: Fonte, conferencia: Conferencia, efeito: str) -> Tratamento:
    return Tratamento(fonte, conferencia, efeito)


F, C = Fonte, Conferencia

CAMPOS_DO_CONGELAMENTO: dict[str, Tratamento] = {}

CAMPOS_DA_CONFIG: dict[str, Tratamento] = {}
