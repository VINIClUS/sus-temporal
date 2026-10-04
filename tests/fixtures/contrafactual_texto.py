"""Detector de afirmações proibidas: aprovação, garantia ou recomendação não negadas."""

from __future__ import annotations

import re

__all__ = ["afirmacoes_proibidas"]

_TERMOS = re.compile(
    r"aprovad\w*|assegur\w*|garant\w*|aprova[çc][ãa]o garantida|recomend\w*"
    r"|execut[áa]vel com certeza",
    re.IGNORECASE,
)
_NEGACAO = re.compile(r"\b(não|nunca|nem|nenhum\w*|sem)\b", re.IGNORECASE)
_JANELA = 60


def afirmacoes_proibidas(texto: str) -> list[str]:
    """Trechos com termo proibido sem negação logo antes; identificadores ficam de fora."""
    achados = []
    for termo in _TERMOS.finditer(texto):
        inicio = termo.start()
        if inicio and texto[inicio - 1] in "_`":
            continue
        if not _NEGACAO.search(texto[max(0, inicio - _JANELA) : inicio]):
            achados.append(texto[max(0, inicio - _JANELA) : termo.end()])
    return achados
