"""Itens da comparação do `reproduce`: a situação de cada um e o que se comparou (T14).

Divergência de conteúdo é `DIVERGENTE`; o que não tem original para comparar é `INCONCLUSIVO`,
nunca violação.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = ["Comparacao", "Situacao"]


class Situacao(StrEnum):
    IGUAL = "IGUAL"
    BYTES_DIFERENTES = "BYTES_DIFERENTES_HASH_LOGICO_IGUAL"
    DIVERGENTE = "DIVERGENTE"
    INCONCLUSIVO = "INCONCLUSIVO"


@dataclass(frozen=True)
class Comparacao:
    """Um item comparado: o que se esperava, o que se obteve e a situação."""

    item: str
    situacao: Situacao
    esperado: str | None = None
    obtido: str | None = None
    detalhe: str = ""

    def como_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "situacao": self.situacao.value,
            "esperado": self.esperado,
            "obtido": self.obtido,
            "detalhe": self.detalhe,
        }
