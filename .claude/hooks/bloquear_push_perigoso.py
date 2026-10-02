"""Hook PreToolUse (Bash): bloqueia push forçado ou para main, remoção, merge e desvio de hook."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace

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
_OPCOES_DE_REPOSITORIO = {"--git-dir", "--work-tree"}
_VARIAVEIS_DE_REPOSITORIO = {"GIT_DIR": "--git-dir", "GIT_WORK_TREE": "--work-tree"}
_INTERPRETADORES = {"bash", "sh", "zsh", "dash", "ksh"}
_EXECUTAVEIS_COM_AMBIENTE = {"git", "eval", *_INTERPRETADORES}
_OPCOES_SHELL_COM_VALOR = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
_FLAGS_PERIGOSAS = {"--delete", "--mirror", "--all", "--tags", "--prune"}
_CURTAS_PERIGOSAS = re.compile(r"^-[a-zA-Z]*[fd][a-zA-Z]*$")
_ALVOS_PROIBIDOS = {"main", "heads/main", "refs/heads/main"}
_OPCOES_PUSH_COM_VALOR = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_SEM_VERIFICACAO = "--no-verify"
_MENOR_ABREVIACAO_SEM_VERIFICACAO = len("--no-v")
_CHAVE_HOOKS = "core.hookspath"
_OPCOES_DE_CONFIG = {"-c", "--config-env"}
_SUBCOMANDOS_PROIBIDOS = {"send-pack"}
_OPCOES_GH_COM_VALOR = {"-R", "--repo", "--hostname"}
_OPCOES_METODO_GH = {"-X", "--method"}
_TRECHOS_PROIBIDOS_GH_API = ("/merge", "/git/refs")
_ORIGENS_IMPLICITAS = {"HEAD", "@"}
_COMANDOS_DE_DIRETORIO = {"cd", "pushd"}
_CARACTERES_INDETERMINADOS = "$~`"
_ABERTURAS_DE_SUBSTITUICAO = ("$(", "`", "<(", ">(")
_SINTAXE_DE_SUBSTITUICAO = re.compile(r"\$\(|[<>]\(|[`\"'()]")
_EXPANSIVEIS = frozenset("$`{*?[")
_INVOLUCROS = frozenset(
    {"env", "command", "exec", "nohup", "sudo", "time", "nice", "xargs", "timeout", "stdbuf"}
)
_ATRIBUICAO = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_CONFIG_POR_AMBIENTE = re.compile(r"^GIT_CONFIG_(COUNT|PARAMETERS|GLOBAL|SYSTEM|KEY_\d+|VALUE_\d+)=")
_REMOCOES_DE_CONFIG = frozenset(
    {"--unset", "--unset-all", "--remove-section", "--rename-section", "unset", "remove-section"}
)
_HOOKS_DO_REPOSITORIO = ".githooks"
_SUBCOMANDOS_NATIVOS = frozenset(
    """
    add am apply archive bisect blame branch cat-file checkout cherry-pick clean clone commit
    config describe diff fetch for-each-ref format-patch gc grep hash-object init log ls-files
    ls-remote ls-tree merge mv notes pull rebase reflog remote reset restore rev-list rev-parse
    rm shortlog show show-ref stash status submodule switch symbolic-ref tag update-ref worktree
    """.split()
)
_INDETERMINADO = "\x00indeterminado"
_ALIAS_DESCONHECIDO = "\x00alias_desconhecido"


@dataclass(frozen=True)
class _Contexto:
    diretorio: str | None = None
    repositorio: tuple[str, ...] = ()

    @property
    def indeterminado(self) -> bool:
        return self.diretorio == _INDETERMINADO

    @property
    def explicito(self) -> bool:
        return self.diretorio is not None or bool(self.repositorio)


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


def _indeterminado(caminho: str) -> bool:
    return any(caractere in caminho for caractere in _CARACTERES_INDETERMINADOS)


def _novo_diretorio(atual: str | None, destino: str | None) -> str:
    if destino is None or destino == "-" or atual == _INDETERMINADO or _indeterminado(destino):
        return _INDETERMINADO
    if atual is None or os.path.isabs(destino):
        return destino
    return os.path.join(atual, destino)


def _com_opcao(contexto: _Contexto, opcao: str, valor: str) -> _Contexto:
    if opcao == "-C":
        return replace(contexto, diretorio=_novo_diretorio(contexto.diretorio, valor))
    if opcao not in _OPCOES_DE_REPOSITORIO:
        return contexto
    if _indeterminado(valor):
        return replace(contexto, diretorio=_INDETERMINADO)
    return replace(contexto, repositorio=(*contexto.repositorio, f"{opcao}={valor}"))


def _com_ambiente(contexto: _Contexto, atribuicoes: list[str]) -> _Contexto:
    for atribuicao in atribuicoes:
        nome, igual, valor = atribuicao.partition("=")
        opcao = _VARIAVEIS_DE_REPOSITORIO.get(nome)
        if igual and opcao is not None:
            contexto = _com_opcao(contexto, opcao, valor)
    return contexto


def _registrar_alias(aliases: dict[str, str], opcao: str, valor: str) -> None:
    nome, _, expansao = valor.partition("=")
    if not nome.lower().startswith("alias."):
        return
    alias = nome[len("alias.") :].lower()
    if opcao == "-c":
        aliases[alias] = expansao
    elif opcao == "--config-env":
        aliases[alias] = _ALIAS_DESCONHECIDO


def _opcao_global(tokens: list[str], indice: int) -> tuple[str, str, int]:
    opcao = tokens[indice]
    nome, igual, valor = opcao.partition("=")
    if opcao.startswith("--") and igual and nome in _OPCOES_GIT_COM_VALOR:
        return nome, valor, 1
    if opcao in _OPCOES_GIT_COM_VALOR:
        return opcao, tokens[indice + 1] if indice + 1 < len(tokens) else "", 2
    return opcao, "", 1


def _subcomando_git(
    tokens: list[str], inicio: int, contexto: _Contexto
) -> tuple[int, dict[str, str], _Contexto]:
    aliases: dict[str, str] = {}
    indice = inicio
    while indice < len(tokens) and tokens[indice].startswith("-"):
        opcao, valor, passo = _opcao_global(tokens, indice)
        _registrar_alias(aliases, opcao, valor)
        contexto = _com_opcao(contexto, opcao, valor)
        indice += passo
    return indice, aliases, contexto


def _sem_verificacao(token: str) -> bool:
    return len(token) >= _MENOR_ABREVIACAO_SEM_VERIFICACAO and _SEM_VERIFICACAO.startswith(token)


def _argumento_perigoso(token: str) -> bool:
    if token.startswith("--force") or token in _FLAGS_PERIGOSAS or _sem_verificacao(token):
        return True
    if _CURTAS_PERIGOSAS.match(token) or token.startswith(("+", ":")):
        return True
    return token.rsplit(":", 1)[-1] in _ALVOS_PROIBIDOS


def _valor_de_config(opcoes: list[str], posicao: int) -> str | None:
    opcao = opcoes[posicao]
    if opcao.startswith("--config-env="):
        return opcao.partition("=")[2]
    if opcao in _OPCOES_DE_CONFIG and posicao + 1 < len(opcoes):
        return opcoes[posicao + 1]
    return None


def _expansivel(token: str) -> bool:
    return any(caractere in token for caractere in _EXPANSIVEIS)


def _sobrescreve_hooks(opcoes: list[str]) -> bool:
    for posicao in range(len(opcoes)):
        valor = _valor_de_config(opcoes, posicao)
        if valor is None:
            continue
        if _expansivel(valor) or valor.partition("=")[0].strip().lower() == _CHAVE_HOOKS:
            return True
    return False


def _config_de_hooks_perigosa(argumentos: list[str]) -> bool:
    minusculos = [argumento.lower() for argumento in argumentos]
    if not any(_CHAVE_HOOKS in argumento for argumento in minusculos):
        return False
    if any(a in _REMOCOES_DE_CONFIG or _expansivel(a) for a in minusculos):
        return True
    posicionais = [argumento for argumento in argumentos if not argumento.startswith("-")]
    chave = next(i for i, a in enumerate(posicionais) if _CHAVE_HOOKS in a.lower())
    valor = posicionais[chave + 1 : chave + 2]
    return bool(valor) and valor[0] != _HOOKS_DO_REPOSITORIO


def _alias_perigoso(expansao: str, resto: list[str], contexto: _Contexto) -> bool:
    if expansao == _ALIAS_DESCONHECIDO:
        return True
    argumentos = " ".join(shlex.quote(token) for token in resto)
    if expansao.startswith("!"):
        return comando_perigoso(f"{expansao[1:]} {argumentos}", contexto)
    return comando_perigoso(f"git {expansao} {argumentos}", contexto)


def _git_perigoso(tokens: list[str], posicao_git: int, contexto: _Contexto) -> bool:
    indice, aliases, contexto = _subcomando_git(tokens, posicao_git + 1, contexto)
    if _sobrescreve_hooks(tokens[posicao_git + 1 : indice]):
        return True
    if indice >= len(tokens):
        return False
    subcomando, resto = tokens[indice], tokens[indice + 1 :]
    if _expansivel(subcomando) or subcomando in _SUBCOMANDOS_PROIBIDOS:
        return True
    if subcomando == "push":
        return _push_perigoso(resto, contexto)
    if subcomando == "config":
        return _config_de_hooks_perigosa(resto)
    if subcomando.lower() in aliases:
        return _alias_perigoso(aliases[subcomando.lower()], resto, contexto)
    return _alias_persistido_perigoso(subcomando, resto, contexto)


def _push_perigoso(argumentos: list[str], contexto: _Contexto) -> bool:
    if any(_expansivel(token) or _argumento_perigoso(token) for token in argumentos):
        return True
    posicionais = _posicionais(argumentos, _OPCOES_PUSH_COM_VALOR)
    return _destino_implicito_perigoso(posicionais, contexto)


def _builtin(subcomando: str) -> bool:
    return subcomando in _git(_Contexto(), "--list-cmds=builtins").split()


def _alias_persistido_perigoso(subcomando: str, resto: list[str], contexto: _Contexto) -> bool:
    if subcomando in _SUBCOMANDOS_NATIVOS:
        return False
    if contexto.indeterminado:
        return not _builtin(subcomando)
    expansao = _git(contexto, "config", "--get", f"alias.{subcomando}")
    return bool(expansao) and _alias_perigoso(expansao, resto, contexto)


def _posicionais(argumentos: list[str], opcoes_com_valor: set[str]) -> list[str]:
    posicionais: list[str] = []
    indice = 0
    while indice < len(argumentos):
        argumento = argumentos[indice]
        if argumento in opcoes_com_valor:
            indice += 2
            continue
        if not argumento.startswith("-"):
            posicionais.append(argumento)
        indice += 1
    return posicionais


def _gh_perigoso(argumentos: list[str]) -> bool:
    comando = _posicionais(argumentos, _OPCOES_GH_COM_VALOR)[:2]
    if comando == ["pr", "merge"]:
        return True
    return comando[:1] == ["api"] and _gh_api_perigoso(argumentos)


def _gh_api_perigoso(argumentos: list[str]) -> bool:
    if _metodo_delete(argumentos):
        return True
    minusculos = [argumento.lower() for argumento in argumentos]
    return any(trecho in arg for arg in minusculos for trecho in _TRECHOS_PROIBIDOS_GH_API)


def _metodo_delete(argumentos: list[str]) -> bool:
    for posicao, argumento in enumerate(argumentos):
        if argumento in _OPCOES_METODO_GH:
            valor = argumentos[posicao + 1] if posicao + 1 < len(argumentos) else ""
        elif argumento.startswith("--method="):
            valor = argumento.partition("=")[2]
        elif argumento.startswith("-X"):
            valor = argumento[2:].removeprefix("=")
        else:
            continue
        if valor.upper() == "DELETE":
            return True
    return False


def _git(contexto: _Contexto, *argumentos: str) -> str:
    prefixo = ["git"] if contexto.diretorio is None else ["git", "-C", contexto.diretorio]
    try:
        resultado = subprocess.run(
            [*prefixo, *contexto.repositorio, *argumentos],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return resultado.stdout.strip() if resultado.returncode == 0 else ""


def _destino_implicito_perigoso(posicionais: list[str], contexto: _Contexto) -> bool:
    refspecs = posicionais[1:]
    implicitos = [r for r in refspecs if r.lstrip("+") in _ORIGENS_IMPLICITAS]
    if refspecs and not implicitos:
        return False
    if contexto.indeterminado:
        return True
    ramo = _git(contexto, "rev-parse", "--abbrev-ref", "HEAD")
    if ramo == "main" or (contexto.explicito and not ramo):
        return True
    upstream = _git(contexto, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
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


def _interpretado_perigoso(tokens: list[str], posicao: int, contexto: _Contexto) -> bool:
    comando = _comando_do_interpretador(tokens[posicao + 1 :])
    return comando is not None and comando_perigoso(comando, contexto)


def _executavel_perigoso(tokens: list[str], posicao: int, contexto: _Contexto) -> bool:
    nome = tokens[posicao].rsplit("/", 1)[-1]
    if nome == "gh":
        return _gh_perigoso(tokens[posicao + 1 :])
    if nome not in _EXECUTAVEIS_COM_AMBIENTE:
        return False
    local = _com_ambiente(contexto, tokens[:posicao])
    if nome == "git":
        return _git_perigoso(tokens, posicao, local)
    if nome == "eval":
        return comando_perigoso(" ".join(tokens[posicao + 1 :]), local)
    return _interpretado_perigoso(tokens, posicao, local)


def _contexto_do_segmento(segmento: list[str], contexto: _Contexto) -> _Contexto | None:
    if segmento and segmento[0] in _COMANDOS_DE_DIRETORIO:
        destino = segmento[1] if len(segmento) > 1 else None
        return replace(contexto, diretorio=_novo_diretorio(contexto.diretorio, destino))
    if segmento and segmento[0] == "export":
        return _com_ambiente(contexto, segmento[1:])
    return None


def _achatado(comando: str) -> str:
    """Remove aspas e delimitadores de substituição, expondo os comandos internos."""
    return _SINTAXE_DE_SUBSTITUICAO.sub(" ", comando)


def _posicoes_de_comando(segmento: list[str]) -> list[int]:
    posicoes: list[int] = []
    indice = 0
    while indice < len(segmento):
        token = segmento[indice]
        if _ATRIBUICAO.match(token) or (posicoes and token.startswith("-")):
            indice += 1
            continue
        posicoes.append(indice)
        nome = token.rsplit("/", 1)[-1]
        if nome == "uv" and segmento[indice + 1 : indice + 2] == ["run"]:
            indice += 2
        elif nome in _INVOLUCROS:
            indice += 1
        else:
            break
    return posicoes


def _comando_indeterminado_perigoso(segmento: list[str], contexto: _Contexto) -> bool:
    """Programa expansível em posição de comando é tratado como git (falha fechado)."""
    for posicao in _posicoes_de_comando(segmento):
        if any(caractere in segmento[posicao] for caractere in "$`"):
            local = _com_ambiente(contexto, segmento[:posicao])
            if _git_perigoso(segmento, posicao, local):
                return True
    return False


def _segmento_perigoso(segmento: list[str], contexto: _Contexto) -> bool:
    if _comando_indeterminado_perigoso(segmento, contexto):
        return True
    return any(_executavel_perigoso(segmento, p, contexto) for p in range(len(segmento)))


def _segmentos_perigosos(comando: str, contexto: _Contexto) -> bool:
    atual = contexto
    for segmento in _segmentos(_tokens(comando)):
        if any(_CONFIG_POR_AMBIENTE.match(token) for token in segmento):
            return True
        novo = _contexto_do_segmento(segmento, atual)
        if novo is not None:
            atual = novo
        elif _segmento_perigoso(segmento, atual):
            return True
    return False


def comando_perigoso(comando: str, contexto: _Contexto | None = None) -> bool:
    atual = contexto or _Contexto()
    substitui = any(abertura in comando for abertura in _ABERTURAS_DE_SUBSTITUICAO)
    if substitui and _segmentos_perigosos(_achatado(comando), atual):
        return True
    return _segmentos_perigosos(comando, atual)


def main() -> int:
    entrada = json.load(sys.stdin)
    if entrada.get("tool_name") != "Bash":
        return 0
    comando = str(entrada.get("tool_input", {}).get("command", ""))
    if comando_perigoso(comando):
        sys.stderr.write(
            f"push_bloqueado motivo=force_delete_main_merge_ou_desvio_de_hook comando={comando}\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
