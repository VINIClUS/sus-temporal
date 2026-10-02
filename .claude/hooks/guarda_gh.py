"""Regras do gh para a guarda do Bash: merge de PR, escrita direta e gh api destrutivo."""

from __future__ import annotations

_OPCOES_GH_COM_VALOR = {"-R", "--repo", "--hostname"}
_OPCOES_METODO_GH = {"-X", "--method"}
_CAMPOS_GH = {"-f", "-F", "--field", "--raw-field"}
_OPCOES_API_COM_VALOR = {
    *_OPCOES_GH_COM_VALOR,
    *_OPCOES_METODO_GH,
    *_CAMPOS_GH,
    *("-H", "--header", "--input", "-q", "--jq", "-t", "--template", "--cache", "-p"),
}
_SUBCOMANDOS_GH_PROIBIDOS = (
    ["pr", "merge"],
    ["repo", "delete"],
    ["repo", "archive"],
    ["repo", "rename"],
)
_TRECHOS_PROIBIDOS_GH_API = ("/merge", "/git/refs")
_TRECHOS_SEM_ESCRITA = ("/contents", "/git/", "/branches")
_METODOS_DE_LEITURA = {"GET", "HEAD"}


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
    if comando in _SUBCOMANDOS_GH_PROIBIDOS:
        return True
    return comando[:1] == ["api"] and _gh_api_perigoso(argumentos)


def _gh_api_perigoso(argumentos: list[str]) -> bool:
    metodo = _metodo(argumentos)
    if metodo == "DELETE":
        return True
    soltos = posicionais(argumentos, _OPCOES_API_COM_VALOR)
    endpoint = soltos[1].lower() if len(soltos) > 1 else ""
    if endpoint == "graphql":
        return _graphql_perigoso(argumentos)
    minusculos = [argumento.lower() for argumento in argumentos]
    if any(trecho in arg for arg in minusculos for trecho in _TRECHOS_PROIBIDOS_GH_API):
        return True
    escrita = metodo not in _METODOS_DE_LEITURA if metodo else _tem_campos(argumentos)
    return escrita and any(trecho in endpoint for trecho in _TRECHOS_SEM_ESCRITA)


def _graphql_perigoso(argumentos: list[str]) -> bool:
    """Mutação, ou consulta que não dá para ler (--input ou campo vindo de arquivo)."""
    if "--input" in argumentos:
        return True
    if any("mutation" in argumento.lower() for argumento in argumentos):
        return True
    return any(argumento.partition("=")[2].startswith("@") for argumento in argumentos)


def _tem_campos(argumentos: list[str]) -> bool:
    return any(a in _CAMPOS_GH or a == "--input" for a in argumentos)


def _metodo(argumentos: list[str]) -> str:
    for posicao, argumento in enumerate(argumentos):
        if argumento in _OPCOES_METODO_GH:
            return argumentos[posicao + 1].upper() if posicao + 1 < len(argumentos) else ""
        if argumento.startswith("--method="):
            return argumento.partition("=")[2].upper()
        if argumento.startswith("-X") and len(argumento) > 2:
            return argumento[2:].removeprefix("=").upper()
    return ""
