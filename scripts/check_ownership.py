"""Verifica a propriedade de arquivos de um branch contra docs/process/propriedade.yaml."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Dono:
    branches: tuple[str, ...]
    caminhos: tuple[str, ...]


@dataclass(frozen=True)
class EspecificacaoPropriedade:
    donos: dict[str, Dono]
    somente_humanos: tuple[str, ...] = field(default=())
    excecoes_humanos: tuple[str, ...] = field(default=())


def carregar_especificacao(caminho: Path) -> EspecificacaoPropriedade:
    raise NotImplementedError


def dono_do_branch(branch: str, especificacao: EspecificacaoPropriedade) -> str | None:
    raise NotImplementedError


def encontrar_violacoes(
    alterados: Iterable[str], dono: str, especificacao: EspecificacaoPropriedade
) -> list[str]:
    raise NotImplementedError
