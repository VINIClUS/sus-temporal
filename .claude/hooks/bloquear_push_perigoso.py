"""Hook PreToolUse (Bash): bloqueia push forçado, remoção de branch e push para main."""

from __future__ import annotations

import json
import re
import shlex
import sys

_OPERADORES = {"&&", "||", ";", "|", "&", ";;", "|&"}
_OPCOES_GIT_COM_VALOR = {
    "-c",
    "-C",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
    "--config-env",
    "--super-prefix",
}
_INTERPRETADORES = {"bash", "sh", "zsh", "dash", "ksh"}
_FLAGS_PERIGOSAS = {"--delete", "--mirror", "--all", "--tags", "--prune"}
_CURTAS_PERIGOSAS = re.compile(r"^-[a-zA-Z]*[fd][a-zA-Z]*$")
_ALVOS_PROIBIDOS = {"main", "refs/heads/main"}


def _tokens(comando: str) -> list[str]:
    lexer = shlex.shlex(comando, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return comando.split()


def _segmentos(tokens: list[str]) -> list[list[str]]:
    segmentos: list[list[str]] = [[]]
    for token in tokens:
        if token in _OPERADORES:
            segmentos.append([])
        else:
            segmentos[-1].append(token)
    return segmentos


def _subcomando_git(tokens: list[str], inicio: int) -> int:
    indice = inicio
    while indice < len(tokens):
        token = tokens[indice]
        if token in _OPCOES_GIT_COM_VALOR:
            indice += 2
        elif token.startswith("-"):
            indice += 1
        else:
            return indice
    return indice


def _argumento_perigoso(token: str) -> bool:
    if token.startswith("--force") or token in _FLAGS_PERIGOSAS:
        return True
    if _CURTAS_PERIGOSAS.match(token) or token.startswith(("+", ":")):
        return True
    return token.rsplit(":", 1)[-1] in _ALVOS_PROIBIDOS


def _push_perigoso(tokens: list[str], posicao_git: int) -> bool:
    indice = _subcomando_git(tokens, posicao_git + 1)
    if indice >= len(tokens) or tokens[indice] != "push":
        return False
    return any(_argumento_perigoso(token) for token in tokens[indice + 1 :])


def _interpretado_perigoso(tokens: list[str], posicao: int) -> bool:
    restantes = tokens[posicao + 1 :]
    if "-c" not in restantes:
        return False
    indice = restantes.index("-c") + 1
    return indice < len(restantes) and comando_perigoso(restantes[indice])


def _segmento_perigoso(tokens: list[str]) -> bool:
    for posicao, token in enumerate(tokens):
        nome = token.rsplit("/", 1)[-1]
        if nome == "git" and _push_perigoso(tokens, posicao):
            return True
        if nome in _INTERPRETADORES and _interpretado_perigoso(tokens, posicao):
            return True
    return False


def comando_perigoso(comando: str) -> bool:
    return any(_segmento_perigoso(segmento) for segmento in _segmentos(_tokens(comando)))


def main() -> int:
    entrada = json.load(sys.stdin)
    if entrada.get("tool_name") != "Bash":
        return 0
    comando = str(entrada.get("tool_input", {}).get("command", ""))
    if comando_perigoso(comando):
        sys.stderr.write(f"push_bloqueado motivo=force_delete_ou_main comando={comando}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
