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
CAMINHO_ESPECIFICACAO = "docs/process/propriedade.yaml"
PREFIXO_AGENTES = "claude/"


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
    reservados_integradores: tuple[str, ...] = field(default=())


class ErroPropriedade(Exception):
    pass


def _casa(caminho: str, padroes: Iterable[str]) -> bool:
    return any(fnmatchcase(caminho, padrao) for padrao in padroes)


def _textos(bruto: dict[str, object], chave: str) -> tuple[str, ...]:
    valores = bruto.get(chave) or []
    if not isinstance(valores, list):
        raise ErroPropriedade(f"especificacao_invalida chave={chave}")
    return tuple(str(valor) for valor in valores)


def especificacao_de_texto(texto: str) -> EspecificacaoPropriedade:
    bruto = yaml.safe_load(texto)
    donos = {
        str(nome): Dono(
            branches=tuple(str(b) for b in dados["branches"]),
            caminhos=tuple(str(c) for c in dados["caminhos"]),
        )
        for nome, dados in bruto["donos"].items()
    }
    return EspecificacaoPropriedade(
        donos=donos,
        somente_humanos=_textos(bruto, "somente_humanos"),
        excecoes_humanos=_textos(bruto, "excecoes_humanos"),
        integradores=_textos(bruto, "integradores"),
        reservados_integradores=_textos(bruto, "reservados_integradores"),
    )


def carregar_especificacao(caminho: Path) -> EspecificacaoPropriedade:
    return especificacao_de_texto(caminho.read_text(encoding="utf-8"))


def dono_do_branch(branch: str, especificacao: EspecificacaoPropriedade) -> str | None:
    for nome, dono in especificacao.donos.items():
        if _casa(branch, dono.branches):
            return nome
    return None


def _reservado(caminho: str, especificacao: EspecificacaoPropriedade) -> bool:
    return caminho.rsplit("/", 1)[-1] in especificacao.reservados_integradores


def _viola(caminho: str, dono: str, especificacao: EspecificacaoPropriedade) -> bool:
    if _casa(caminho, especificacao.somente_humanos):
        return not _casa(caminho, especificacao.excecoes_humanos)
    if dono in especificacao.integradores:
        return False
    if _reservado(caminho, especificacao):
        return True
    if _casa(caminho, especificacao.donos[dono].caminhos):
        return False
    outros = (d for nome, d in especificacao.donos.items() if nome != dono)
    return any(_casa(caminho, d.caminhos) for d in outros)


def encontrar_violacoes(
    alterados: Iterable[str], dono: str, especificacao: EspecificacaoPropriedade
) -> list[str]:
    return [caminho for caminho in alterados if _viola(caminho, dono, especificacao)]


def _git(raiz: Path, *argumentos: str) -> str:
    resultado = subprocess.run(
        ["git", *argumentos], cwd=raiz, check=True, capture_output=True, text=True
    )
    return resultado.stdout


def branch_atual(raiz: Path) -> str:
    for variavel in ("PROPRIEDADE_BRANCH", "GITHUB_HEAD_REF"):
        valor = os.environ.get(variavel)
        if valor:
            return valor
    return _git(raiz, "rev-parse", "--abbrev-ref", "HEAD").strip()


def _ponto_de_base(raiz: Path, base: str) -> str:
    try:
        return _git(raiz, "merge-base", "HEAD", base).strip()
    except subprocess.CalledProcessError as erro:
        raise ErroPropriedade(f"base_ausente base={base}") from erro


def arquivos_alterados(raiz: Path, ponto: str) -> list[str]:
    saida = _git(raiz, "diff", "--name-only", "--no-renames", "-z", f"{ponto}..HEAD")
    return [caminho for caminho in saida.split("\0") if caminho]


def especificacao_da_base(raiz: Path, ponto: str) -> EspecificacaoPropriedade:
    try:
        texto = _git(raiz, "show", f"{ponto}:{CAMINHO_ESPECIFICACAO}")
    except subprocess.CalledProcessError:
        return carregar_especificacao(raiz / CAMINHO_ESPECIFICACAO)
    return especificacao_de_texto(texto)


def verificar(raiz: Path, branch: str, base: str) -> int:
    ponto = _ponto_de_base(raiz, base)
    especificacao = especificacao_da_base(raiz, ponto)
    dono = dono_do_branch(branch, especificacao)
    if dono is None:
        if branch.startswith(PREFIXO_AGENTES):
            logger.error("propriedade_violada motivo=branch_sem_dono branch=%s", branch)
            return 1
        logger.info("propriedade_ignorada motivo=branch_humano branch=%s", branch)
        return 0
    violacoes = encontrar_violacoes(arquivos_alterados(raiz, ponto), dono, especificacao)
    for caminho in violacoes:
        logger.error("propriedade_violada dono=%s caminho=%s", dono, caminho)
    logger.info("propriedade_verificada dono=%s violacoes=%d", dono, len(violacoes))
    return 1 if violacoes else 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        logger.info("propriedade_ignorada motivo=push")
        return 0
    base = f"origin/{os.environ.get('GITHUB_BASE_REF') or 'main'}"
    try:
        return verificar(RAIZ, branch_atual(RAIZ), base)
    except ErroPropriedade as erro:
        logger.error("propriedade_erro %s", erro)
        return 1


if __name__ == "__main__":
    sys.exit(main())
