"""Hook PreToolUse (mcp__github__.*): recusa merge, auto-merge, remoção de arquivo e ref main."""

from __future__ import annotations

import json
import os
import sys

_PREFIXO = "mcp__github__"
_PROIBIDAS = frozenset({"merge_pull_request", "enable_pr_auto_merge", "delete_file"})
_LIBERADAS_AO_ORQUESTRADOR = frozenset({"merge_pull_request"})
_CAMPOS_DE_REF = ("branch", "ref", "head")
_REFS_PROTEGIDAS = frozenset({"main", "heads/main", "refs/heads/main"})
_VARIAVEL_PAPEL = "SUSTEMPORAL_PAPEL"
_PAPEL_ORQUESTRADOR = "orquestrador"


def _aponta_para_main(valor: object) -> bool:
    if not isinstance(valor, str):
        return False
    return valor.strip().rsplit(":", 1)[-1].casefold() in _REFS_PROTEGIDAS


def _campo_em_main(entrada: dict[str, object]) -> str | None:
    return next((campo for campo in _CAMPOS_DE_REF if _aponta_para_main(entrada.get(campo))), None)


def _liberada_ao_papel(nome: str) -> bool:
    papel = os.environ.get(_VARIAVEL_PAPEL)
    return nome in _LIBERADAS_AO_ORQUESTRADOR and papel == _PAPEL_ORQUESTRADOR


def motivo_de_recusa(ferramenta: str, entrada: dict[str, object]) -> str | None:
    if not ferramenta.startswith(_PREFIXO):
        return None
    campo = _campo_em_main(entrada)
    if campo is not None:
        return f"ref_main campo={campo}"
    nome = ferramenta.removeprefix(_PREFIXO)
    if nome in _PROIBIDAS and not _liberada_ao_papel(nome):
        return nome
    return None


def _ler_chamada() -> tuple[str, dict[str, object]] | None:
    try:
        dados = json.load(sys.stdin)
    except ValueError:
        return None
    if not isinstance(dados, dict):
        return None
    ferramenta = dados.get("tool_name")
    entrada = dados.get("tool_input", {})
    if not isinstance(ferramenta, str) or not isinstance(entrada, dict):
        return None
    return ferramenta, entrada


def main() -> int:
    chamada = _ler_chamada()
    motivo = "entrada_invalida" if chamada is None else motivo_de_recusa(*chamada)
    if motivo is None:
        return 0
    ferramenta = "-" if chamada is None else chamada[0]
    sys.stderr.write(f"mcp_bloqueado motivo={motivo} ferramenta={ferramenta}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
