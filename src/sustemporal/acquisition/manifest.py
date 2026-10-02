"""Manifesto append-only em JSONL com cadeia de hash."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import (
        ArtifactObservation,
        ArtifactVersion,
        LinhaManifesto,
    )

__all__ = ["EstadoManifesto", "Manifesto", "ManifestoCorrompido"]


class ManifestoCorrompido(FalhaOperacionalErro):
    """Linha reescrita, removida, reordenada ou ilegível."""


@dataclass(frozen=True)
class EstadoManifesto:
    linhas: tuple[LinhaManifesto, ...] = ()

    @property
    def versoes(self) -> dict[str, ArtifactVersion]:
        raise NotImplementedError

    @property
    def observacoes(self) -> tuple[ArtifactObservation, ...]:
        raise NotImplementedError

    @property
    def cabeca_sha256(self) -> str | None:
        raise NotImplementedError


class Manifesto:
    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho

    def ler(self) -> EstadoManifesto:
        """Lê e confere a cadeia inteira.

        Raises:
            ManifestoCorrompido: cadeia, sequência ou referências incoerentes.
        """
        raise NotImplementedError

    def registrar(
        self, observacao: ArtifactObservation, versao: ArtifactVersion | None = None
    ) -> None:
        """Acrescenta a versão (se nova) e a observação, sob trava exclusiva."""
        raise NotImplementedError
