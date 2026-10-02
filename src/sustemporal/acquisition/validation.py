"""Validação de conteúdo baixado sem executar nem extrair nada."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade, FormatoArquivo, MembroArquivo

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["Veredito", "parece_html", "validar_conteudo"]


@dataclass(frozen=True)
class Veredito:
    integridade: EstadoIntegridade
    membros: tuple[MembroArquivo, ...] = ()
    motivo: str | None = None

    @property
    def em_quarentena(self) -> bool:
        return self.integridade.name.startswith("QUARENTENA")


def parece_html(inicio: bytes) -> bool:
    """Os primeiros bytes parecem uma página HTML/XML (erro de portal, login, índice)."""
    raise NotImplementedError


def validar_conteudo(caminho: Path, formato: FormatoArquivo) -> Veredito:
    """Confere assinatura e estrutura mínima do formato esperado; ZIP só é listado."""
    raise NotImplementedError
