"""Regra de interpretadores de código (python, node, perl...) para a guarda do Bash."""

from __future__ import annotations

import re

_INTERPRETADOR_DE_CODIGO = re.compile(
    r"^(python[0-9.]*|pypy[0-9.]*|nodejs|node|perl|ruby|php|deno|bun)$"
)
_CODIGO_EM_LINHA = frozenset({"-c", "-e", "-E", "-r", "-p", "--eval", "--print", "-", "<<", "<<<"})
_DISPAROS_DE_PROCESSO = (
    "subprocess", "os.system", "popen", "os.exec", "os.spawn", "pty.spawn", "pty.fork",
    "child_process", "execsync", "spawnsync", "system(", "exec(", "eval(", "__import__",
    "importlib", "qx(", "qx{", "qx/",
)


def codigo_perigoso(segmento: list[str], posicoes: list[int], comando: str) -> bool:
    """Código em linha que dispara processo, ou programa invisível vindo da entrada padrão."""
    for posicao in posicoes:
        if not _INTERPRETADOR_DE_CODIGO.match(segmento[posicao].rsplit("/", 1)[-1]):
            continue
        argumentos = segmento[posicao + 1 :]
        visivel = "<<" in argumentos or "<<<" in argumentos
        if not argumentos or "<" in argumentos or ("-" in argumentos and not visivel):
            return True
        if _CODIGO_EM_LINHA.intersection(argumentos) and _dispara_processo(comando):
            return True
    return False


def _dispara_processo(comando: str) -> bool:
    minusculo = comando.casefold()
    return any(marca in minusculo for marca in _DISPAROS_DE_PROCESSO)
