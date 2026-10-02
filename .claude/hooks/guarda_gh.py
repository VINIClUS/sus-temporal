"""Regras do gh para a guarda do Bash: merge de PR e gh api destrutivo."""

from __future__ import annotations

_OPCOES_GH_COM_VALOR = {"-R", "--repo", "--hostname"}
_OPCOES_METODO_GH = {"-X", "--method"}
_TRECHOS_PROIBIDOS_GH_API = ("/merge", "/git/refs")


def posicionais(argumentos: list[str], opcoes_com_valor: set[str]) -> list[str]:
    encontrados: list[str] = []
    indice = 0
    while indice < len(argumentos):
        argumento = argumentos[indice]
        if argumento in opcoes_com_valor:
            indice += 2
            continue
        if not argumento.startswith("-"):
            encontrados.append(argumento)
        indice += 1
    return encontrados


def gh_perigoso(argumentos: list[str]) -> bool:
    comando = posicionais(argumentos, _OPCOES_GH_COM_VALOR)[:2]
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
