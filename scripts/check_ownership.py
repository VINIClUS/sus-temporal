"""Verifica a propriedade de arquivos de um branch contra docs/process/propriedade.yaml."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO_PADRAO = RAIZ / "docs" / "process" / "propriedade.yaml"


@dataclass(frozen=True)
class Dono:
    branches: tuple[str, ...]
    caminhos: tuple[str, ...]


@dataclass(frozen=True)
class EspecificacaoPropriedade:
    donos: dict[str, Dono]
    somente_humanos: tuple[str, ...] = field(default=())
    excecoes_humanos: tuple[str, ...] = field(default=())
    integradores: tuple[str, ...] = field(default=())


def _casa(caminho: str, padroes: Iterable[str]) -> bool:
    return any(fnmatchcase(caminho, padrao) for padrao in padroes)


def carregar_especificacao(caminho: Path) -> EspecificacaoPropriedade:
    bruto = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    donos = {
        str(nome): Dono(
            branches=tuple(str(b) for b in dados["branches"]),
            caminhos=tuple(str(c) for c in dados["caminhos"]),
        )
        for nome, dados in bruto["donos"].items()
    }
    return EspecificacaoPropriedade(
        donos=donos,
        somente_humanos=tuple(str(p) for p in bruto.get("somente_humanos", [])),
        excecoes_humanos=tuple(str(p) for p in bruto.get("excecoes_humanos", [])),
        integradores=tuple(str(n) for n in bruto.get("integradores", [])),
    )


def dono_do_branch(branch: str, especificacao: EspecificacaoPropriedade) -> str | None:
    for nome, dono in especificacao.donos.items():
        if _casa(branch, dono.branches):
            return nome
    return None


def _viola(caminho: str, dono: str, especificacao: EspecificacaoPropriedade) -> bool:
    if _casa(caminho, especificacao.somente_humanos):
        return not _casa(caminho, especificacao.excecoes_humanos)
    if dono in especificacao.integradores:
        return False
    if _casa(caminho, especificacao.donos[dono].caminhos):
        return False
    outros = (d for nome, d in especificacao.donos.items() if nome != dono)
    return any(_casa(caminho, d.caminhos) for d in outros)


def encontrar_violacoes(
    alterados: Iterable[str], dono: str, especificacao: EspecificacaoPropriedade
) -> list[str]:
    return [caminho for caminho in alterados if _viola(caminho, dono, especificacao)]


def _git(*argumentos: str) -> str:
    resultado = subprocess.run(
        ["git", *argumentos], cwd=RAIZ, check=True, capture_output=True, text=True
    )
    return resultado.stdout.strip()


def _branch_atual() -> str:
    return os.environ.get("GITHUB_HEAD_REF") or _git("rev-parse", "--abbrev-ref", "HEAD")


def _arquivos_alterados(base: str) -> list[str]:
    ponto = _git("merge-base", "HEAD", base)
    saida = _git("diff", "--name-only", "--no-renames", f"{ponto}..HEAD")
    return [linha for linha in saida.splitlines() if linha]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        logger.info("propriedade_ignorada motivo=push")
        return 0
    especificacao = carregar_especificacao(ARQUIVO_PADRAO)
    branch = _branch_atual()
    dono = dono_do_branch(branch, especificacao)
    if dono is None:
        logger.info("propriedade_ignorada motivo=branch_sem_dono branch=%s", branch)
        return 0
    violacoes = encontrar_violacoes(_arquivos_alterados("origin/main"), dono, especificacao)
    for caminho in violacoes:
        logger.error("propriedade_violada dono=%s caminho=%s", dono, caminho)
    logger.info("propriedade_verificada dono=%s violacoes=%d", dono, len(violacoes))
    return 1 if violacoes else 0


if __name__ == "__main__":
    sys.exit(main())


def arquivos_alterados(raiz: Path, ponto: str) -> list[str]:
    raise NotImplementedError


def branch_atual(raiz: Path) -> str:
    raise NotImplementedError


def verificar(raiz: Path, branch: str, base: str) -> int:
    raise NotImplementedError
