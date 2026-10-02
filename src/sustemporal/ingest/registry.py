"""Registro de normalizadores por família de fonte (despacho preguiçoso)."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol

from sustemporal.contracts.base import FamiliaFonte

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec


class Normalizador(Protocol):
    def __call__(self, artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef: ...


NORMALIZADORES: dict[FamiliaFonte, str] = {
    FamiliaFonte.SIA_PA: "sustemporal.ingest.sia_pa:normalize_pa",
    FamiliaFonte.CNES_ST: "sustemporal.ingest.cnes:normalize_cnes",
    FamiliaFonte.CNES_PF: "sustemporal.ingest.cnes:normalize_cnes",
    FamiliaFonte.CNES_SR: "sustemporal.ingest.cnes:normalize_cnes",
    FamiliaFonte.CNES_HB: "sustemporal.ingest.cnes:normalize_cnes",
    FamiliaFonte.SIGTAP: "sustemporal.ingest.sigtap:normalize_sigtap",
}


def normalizador(familia: FamiliaFonte) -> Normalizador:
    """Resolve o normalizador da família.

    Raises:
        KeyError: família sem tabela canônica (ex.: documentos, território).
    """
    nome_modulo, nome_funcao = NORMALIZADORES[familia].split(":")
    funcao: Normalizador = getattr(importlib.import_module(nome_modulo), nome_funcao)
    return funcao
