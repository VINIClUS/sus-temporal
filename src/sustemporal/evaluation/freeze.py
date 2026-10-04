"""Congelamento do protocolo e conferência de compatibilidade com o manifesto (T11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sustemporal.gates import DIR_DECISOES

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date, datetime
    from decimal import Decimal
    from pathlib import Path

    from sustemporal.contracts import (
        CodeVersion,
        DatasetRef,
        FeatureSpec,
        FreezeManifest,
        RunConfig,
        SplitManifest,
    )

__all__ = [
    "COMPARACOES_PRIMARIAS",
    "Protocolo",
    "carregar_freeze",
    "congelar",
    "hash_protocolo",
    "verificar_compatibilidade",
]

COMPARACOES_PRIMARIAS = ("M_TEMP_x_B_ATEND", "M_TEMP_x_B_PROC")


def hash_protocolo(config: RunConfig) -> str:
    """Identidade da config sem `modo` e `freeze_id`, que mudam ao abrir o teste."""
    raise NotImplementedError


@dataclass(frozen=True)
class Protocolo:
    """O que se congela: config, split, atributos, entradas completas, catálogos e margens."""

    config: RunConfig
    split: SplitManifest
    features: FeatureSpec
    dataset: DatasetRef
    rotulos: DatasetRef
    catalogos: Mapping[str, Path]
    margens: Mapping[str, Decimal] = field(default_factory=dict)


def congelar(
    protocolo: Protocolo,
    destino: Path,
    *,
    decisoes: Path = DIR_DECISOES,
    codigo: CodeVersion | None = None,
    relogio: Callable[[], datetime] | None = None,
    hoje: date | None = None,
) -> FreezeManifest:
    """Emite o manifesto único do protocolo; exige G0 humano liberado."""
    raise NotImplementedError


def carregar_freeze(diretorio: Path, freeze_id: str) -> FreezeManifest:
    """Manifesto `<diretorio>/<freeze_id>.json` cujo id confere com o conteúdo."""
    raise NotImplementedError


def verificar_compatibilidade(
    manifesto: FreezeManifest,
    *,
    config: RunConfig,
    split: SplitManifest,
    features: FeatureSpec,
    datasets: Sequence[DatasetRef],
    codigo: CodeVersion,
) -> None:
    """Recusa código, split, atributos, config ou entradas fora do congelamento."""
    raise NotImplementedError
