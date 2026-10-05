"""Etapas do fluxo pequeno que a reprodução refaz: janelas do ingest, rótulos e partições (T14)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult, SplitManifest, SplitSpec
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.temporal import MetodoId

__all__ = [
    "Derivado",
    "competencias_da_particao",
    "derivar_protocolo",
    "janela_do_ingest",
    "validar_janela",
]


@dataclass(frozen=True)
class Derivado:
    """União dos `sia_pa.v1` do ingest, os rótulos dela e o split que as partições formam."""

    uniao: DatasetRef
    rotulos: DatasetRef
    split: SplitManifest


def janela_do_ingest(
    config: RunConfig, pasta: Path, destino: Path, competencias: Collection[str]
) -> Path:
    """Pasta com o `datasets.jsonl` do ingest sem o SIA-PA dos arquivos de fora da janela."""
    raise NotImplementedError


def competencias_da_particao(particao: DatasetRef) -> tuple[str, ...]:
    """Competências de processamento (distintas, em ordem) das linhas da partição."""
    raise NotImplementedError


def derivar_protocolo(
    config: RunConfig, pasta: Path, destino: Path, *, spec: SplitSpec
) -> Derivado:
    """União do SIA-PA do ingest, rótulos pelo codebook e partições do split, em `destino`."""
    raise NotImplementedError


def validar_janela(
    config: RunConfig, janela: Path, metodos: Collection[MetodoId] | None = None
) -> dict[MetodoId, RunResult]:
    """`validate --ingest` da janela, um método por vez, gravado em `raiz_execucoes(config)`."""
    raise NotImplementedError
