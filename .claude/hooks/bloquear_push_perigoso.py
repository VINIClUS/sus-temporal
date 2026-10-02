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
_OPCOES_SHELL_COM_VALOR = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
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


def _subcomando_git(tokens: list[str], inicio: int) -> tuple[int, dict[str, str]]:
    aliases: dict[str, str] = {}
    indice = inicio
    while indice < len(tokens):
        opcao = tokens[indice]
        if opcao in _OPCOES_GIT_COM_VALOR:
            valor = tokens[indice + 1] if indice + 1 < len(tokens) else ""
            nome, _, expansao = valor.partition("=")
            if opcao == "-c" and nome.lower().startswith("alias."):
                aliases[nome[len("alias.") :].lower()] = expansao
            indice += 2
        elif opcao.startswith("-"):
            indice += 1
        else:
            return indice, aliases
    return indice, aliases


def _argumento_perigoso(token: str) -> bool:
    if token.startswith("--force") or token in _FLAGS_PERIGOSAS:
        return True
    if _CURTAS_PERIGOSAS.match(token) or token.startswith(("+", ":")):
        return True
    return token.rsplit(":", 1)[-1] in _ALVOS_PROIBIDOS


def _alias_perigoso(expansao: str, resto: list[str]) -> bool:
    argumentos = " ".join(shlex.quote(token) for token in resto)
    if expansao.startswith("!"):
        return comando_perigoso(f"{expansao[1:]} {argumentos}")
    return comando_perigoso(f"git {expansao} {argumentos}")


def _push_perigoso(tokens: list[str], posicao_git: int) -> bool:
    indice, aliases = _subcomando_git(tokens, posicao_git + 1)
    if indice >= len(tokens):
        return False
    subcomando, resto = tokens[indice], tokens[indice + 1 :]
    if subcomando.lower() in aliases:
        return _alias_perigoso(aliases[subcomando.lower()], resto)
    if subcomando != "push":
        return False
    return any(_argumento_perigoso(token) for token in resto)


def _comando_do_interpretador(argumentos: list[str]) -> str | None:
    modo_comando = False
    indice = 0
    while indice < len(argumentos):
        argumento = argumentos[indice]
        if argumento == "--":
            indice += 1
            break
        if argumento in _OPCOES_SHELL_COM_VALOR:
            indice += 2
        elif argumento.startswith(("-", "+")) and len(argumento) > 1:
            modo_comando = modo_comando or _agrupa_opcao_c(argumento)
            indice += 1
        else:
            break
    if modo_comando and indice < len(argumentos):
        return argumentos[indice]
    return None


def _agrupa_opcao_c(argumento: str) -> bool:
    return argumento.startswith("-") and not argumento.startswith("--") and "c" in argumento[1:]


def _interpretado_perigoso(tokens: list[str], posicao: int) -> bool:
    comando = _comando_do_interpretador(tokens[posicao + 1 :])
    return comando is not None and comando_perigoso(comando)


def _segmento_perigoso(tokens: list[str]) -> bool:
    for posicao, token in enumerate(tokens):
        nome = token.rsplit("/", 1)[-1]
        if nome == "git" and _push_perigoso(tokens, posicao):
            return True
        if nome in _INTERPRETADORES and _interpretado_perigoso(tokens, posicao):
            return True
        if nome == "eval" and comando_perigoso(" ".join(tokens[posicao + 1 :])):
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
