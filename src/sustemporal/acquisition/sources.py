"""Catálogo de fontes e plano de requisições em duas passadas."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts.artifacts import SourceRequest
    from sustemporal.contracts.base import FamiliaFonte
    from sustemporal.contracts.temporal import (
        CompetenciaArquivo,
        CompetenciaAtendimento,
        CompetenciaProcessamento,
    )

__all__ = [
    "CatalogoFontes",
    "carregar_catalogo",
    "competencias_auxiliares",
    "requisicao_listagem",
    "requisicoes_da_listagem",
    "requisicoes_documentos",
]


class CatalogoFontes:
    """Substituído pelo modelo validado."""


def carregar_catalogo(caminho: Path) -> CatalogoFontes:
    raise NotImplementedError


def requisicao_listagem(catalogo: CatalogoFontes, fonte: FamiliaFonte) -> SourceRequest:
    raise NotImplementedError


def requisicoes_da_listagem(
    catalogo: CatalogoFontes,
    fonte: FamiliaFonte,
    uf: str,
    competencias: Iterable[CompetenciaArquivo],
    nomes: Iterable[str],
) -> list[SourceRequest]:
    raise NotImplementedError


def competencias_auxiliares(
    atendimento: Iterable[CompetenciaAtendimento],
    processamento: Iterable[CompetenciaProcessamento],
) -> tuple[CompetenciaArquivo, ...]:
    raise NotImplementedError


def requisicoes_documentos(catalogo: CatalogoFontes) -> list[SourceRequest]:
    raise NotImplementedError
