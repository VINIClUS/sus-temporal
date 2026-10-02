"""Hook PreToolUse (Bash): bloqueia push forçado, remoção de branch e push para main."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
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
_ALVOS_PROIBIDOS = {"main", "heads/main", "refs/heads/main"}
_OPCOES_PUSH_COM_VALOR = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_ORIGENS_IMPLICITAS = {"HEAD", "@"}
_COMANDOS_DE_DIRETORIO = {"cd", "pushd"}
_SUBCOMANDOS_NATIVOS = frozenset(
    [
        "add",
        "am",
        "apply",
        "archive",
        "bisect",
        "blame",
        "branch",
        "cat-file",
        "checkout",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "config",
        "describe",
        "diff",
        "fetch",
        "for-each-ref",
        "format-patch",
        "gc",
        "grep",
        "hash-object",
        "init",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge",
        "mv",
        "notes",
        "pull",
        "rebase",
        "reflog",
        "remote",
        "reset",
        "restore",
        "rev-list",
        "rev-parse",
        "rm",
        "shortlog",
        "show",
        "show-ref",
        "stash",
        "status",
        "submodule",
        "switch",
        "symbolic-ref",
        "tag",
        "update-ref",
        "worktree",
    ]
)
_INDETERMINADO = "\x00indeterminado"
_ALIAS_DESCONHECIDO = "\x00alias_desconhecido"


def _tokens(comando: str) -> list[str]:
    lexer = shlex.shlex(comando, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
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


def _novo_diretorio(atual: str | None, destino: str | None) -> str:
    if destino is None or atual == _INDETERMINADO:
        return _INDETERMINADO
    if any(caractere in destino for caractere in "$~`"):
        return _INDETERMINADO
    if atual is None or os.path.isabs(destino):
        return destino
    return os.path.join(atual, destino)


def _registrar_alias(aliases: dict[str, str], opcao: str, valor: str) -> None:
    nome, _, expansao = valor.partition("=")
    if not nome.lower().startswith("alias."):
        return
    alias = nome[len("alias.") :].lower()
    if opcao == "-c":
        aliases[alias] = expansao
    elif opcao == "--config-env":
        aliases[alias] = _ALIAS_DESCONHECIDO


def _subcomando_git(
    tokens: list[str], inicio: int, diretorio: str | None
) -> tuple[int, dict[str, str], str | None]:
    aliases: dict[str, str] = {}
    indice = inicio
    while indice < len(tokens):
        opcao = tokens[indice]
        if opcao.startswith("--config-env="):
            _registrar_alias(aliases, "--config-env", opcao.partition("=")[2])
            indice += 1
        elif opcao in _OPCOES_GIT_COM_VALOR:
            valor = tokens[indice + 1] if indice + 1 < len(tokens) else ""
            _registrar_alias(aliases, opcao, valor)
            if opcao == "-C":
                diretorio = _novo_diretorio(diretorio, valor)
            indice += 2
        elif opcao.startswith("-"):
            indice += 1
        else:
            return indice, aliases, diretorio
    return indice, aliases, diretorio


def _argumento_perigoso(token: str) -> bool:
    if token.startswith("--force") or token in _FLAGS_PERIGOSAS:
        return True
    if _CURTAS_PERIGOSAS.match(token) or token.startswith(("+", ":")):
        return True
    return token.rsplit(":", 1)[-1] in _ALVOS_PROIBIDOS


def _alias_perigoso(expansao: str, resto: list[str], diretorio: str | None) -> bool:
    if expansao == _ALIAS_DESCONHECIDO:
        return True
    argumentos = " ".join(shlex.quote(token) for token in resto)
    if expansao.startswith("!"):
        return comando_perigoso(f"{expansao[1:]} {argumentos}", diretorio)
    return comando_perigoso(f"git {expansao} {argumentos}", diretorio)


def _push_perigoso(tokens: list[str], posicao_git: int, diretorio: str | None) -> bool:
    indice, aliases, diretorio = _subcomando_git(tokens, posicao_git + 1, diretorio)
    if indice >= len(tokens):
        return False
    subcomando, resto = tokens[indice], tokens[indice + 1 :]
    if subcomando.lower() in aliases:
        return _alias_perigoso(aliases[subcomando.lower()], resto, diretorio)
    if subcomando != "push":
        return _alias_persistido_perigoso(subcomando, resto, diretorio)
    if any(_argumento_perigoso(token) for token in resto):
        return True
    return _destino_implicito_perigoso(_posicionais_push(resto), diretorio)


def _alias_persistido_perigoso(subcomando: str, resto: list[str], diretorio: str | None) -> bool:
    if subcomando in _SUBCOMANDOS_NATIVOS or diretorio == _INDETERMINADO:
        return False
    expansao = _git(diretorio, "config", "--get", f"alias.{subcomando}")
    return bool(expansao) and _alias_perigoso(expansao, resto, diretorio)


def _posicionais_push(argumentos: list[str]) -> list[str]:
    posicionais: list[str] = []
    indice = 0
    while indice < len(argumentos):
        argumento = argumentos[indice]
        if argumento in _OPCOES_PUSH_COM_VALOR:
            indice += 2
            continue
        if not argumento.startswith("-"):
            posicionais.append(argumento)
        indice += 1
    return posicionais


def _git(diretorio: str | None, *argumentos: str) -> str:
    prefixo = ["git"] if diretorio is None else ["git", "-C", diretorio]
    try:
        resultado = subprocess.run(
            [*prefixo, *argumentos], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return resultado.stdout.strip() if resultado.returncode == 0 else ""


def _destino_implicito_perigoso(posicionais: list[str], diretorio: str | None) -> bool:
    refspecs = posicionais[1:]
    implicitos = [r for r in refspecs if r.lstrip("+") in _ORIGENS_IMPLICITAS]
    if refspecs and not implicitos:
        return False
    if diretorio == _INDETERMINADO:
        return True
    ramo = _git(diretorio, "rev-parse", "--abbrev-ref", "HEAD")
    if ramo == "main" or (diretorio is not None and not ramo):
        return True
    upstream = _git(diretorio, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return not refspecs and upstream.endswith("/main")


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


def _interpretado_perigoso(tokens: list[str], posicao: int, diretorio: str | None) -> bool:
    comando = _comando_do_interpretador(tokens[posicao + 1 :])
    return comando is not None and comando_perigoso(comando, diretorio)


def _segmento_perigoso(tokens: list[str], diretorio: str | None) -> bool:
    for posicao, token in enumerate(tokens):
        nome = token.rsplit("/", 1)[-1]
        if nome == "git" and _push_perigoso(tokens, posicao, diretorio):
            return True
        if nome in _INTERPRETADORES and _interpretado_perigoso(tokens, posicao, diretorio):
            return True
        if nome == "eval" and comando_perigoso(" ".join(tokens[posicao + 1 :]), diretorio):
            return True
    return False


def comando_perigoso(comando: str, diretorio: str | None = None) -> bool:
    for segmento in _segmentos(_tokens(comando)):
        if segmento and segmento[0] in _COMANDOS_DE_DIRETORIO:
            diretorio = _novo_diretorio(diretorio, segmento[1] if len(segmento) > 1 else None)
        elif _segmento_perigoso(segmento, diretorio):
            return True
    return False


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
