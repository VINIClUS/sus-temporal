"""Documento PROV da explicação: entidades, atividades e agente (T08)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prov.model import ProvDocument


class ProvIncompleto(ValueError):
    """Documento PROV sem as relações exigidas."""


def exigir_relacoes(documento: ProvDocument) -> None:
    raise NotImplementedError
