"""Normalização de arquivos do CNES (T04)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import OrigemDados
from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from sustemporal.contracts import (
        ArtifactVersion,
        DatasetRef,
        FamiliaFonte,
        LayoutSpec,
        RuntimeConfig,
    )

__all__ = ["CATALOGO_LEIAUTES", "FamiliaReservada", "carregar_leiautes_cnes", "normalize_cnes"]

CATALOGO_LEIAUTES = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "cnes.yaml"


class FamiliaReservada(FalhaOperacionalErro):
    """Fonte de família de regra reservada (SR, HB): sem esquema e sem tabela, nunca vazia."""


def carregar_leiautes_cnes(caminho: Path = CATALOGO_LEIAUTES) -> dict[FamiliaFonte, LayoutSpec]:
    """Leiautes do catálogo por fonte (CNES_PF, CNES_ST)."""
    raise NotImplementedError


def normalize_cnes(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.SINTETICO,
) -> DatasetRef:
    """Normaliza um artefato do CNES para o esquema canônico da família."""
    raise NotImplementedError
