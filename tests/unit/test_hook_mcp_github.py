"""Guarda PreToolUse das ferramentas MCP do GitHub (`.claude/hooks/bloquear_mcp_github.py`)."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
HOOK = RAIZ / ".claude" / "hooks" / "bloquear_mcp_github.py"
CONFIGURACAO = RAIZ / ".claude" / "settings.json"
_PAPEL = "SUSTEMPORAL_PAPEL"


def _executar_bruto(entrada: str, papel: str | None = None) -> subprocess.CompletedProcess[str]:
    ambiente = {chave: valor for chave, valor in os.environ.items() if chave != _PAPEL}
    if papel is not None:
        ambiente[_PAPEL] = papel
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=entrada,
        capture_output=True,
        text=True,
        check=False,
        env=ambiente,
    )


def _executar(
    ferramenta: str, entrada: dict[str, object], papel: str | None = None
) -> subprocess.CompletedProcess[str]:
    return _executar_bruto(json.dumps({"tool_name": ferramenta, "tool_input": entrada}), papel)


@pytest.mark.parametrize(
    ("ferramenta", "motivo"),
    [
        ("mcp__github__merge_pull_request", "merge_pull_request"),
        ("mcp__github__enable_pr_auto_merge", "enable_pr_auto_merge"),
        ("mcp__github__delete_file", "delete_file"),
    ],
)
def test_ferramenta_proibida_e_recusada(ferramenta: str, motivo: str) -> None:
    resultado = _executar(ferramenta, {"owner": "o", "repo": "r", "pullNumber": 1})
    assert resultado.returncode == 2
    assert f"mcp_bloqueado motivo={motivo}" in resultado.stderr


@pytest.mark.parametrize(
    ("ferramenta", "entrada"),
    [
        ("mcp__github__create_or_update_file", {"branch": "main", "path": "a", "content": "b"}),
        ("mcp__github__push_files", {"branch": "refs/heads/main", "files": []}),
        ("mcp__github__create_branch", {"branch": "main", "from_branch": "claude/s1-x"}),
        ("mcp__github__create_pull_request", {"head": "main", "base": "claude/s1-x"}),
        ("mcp__github__qualquer_ferramenta", {"ref": "main"}),
        ("mcp__github__push_files", {"branch": " main ", "files": []}),
    ],
)
def test_ref_main_e_recusada_em_qualquer_ferramenta(
    ferramenta: str, entrada: dict[str, object]
) -> None:
    resultado = _executar(ferramenta, entrada)
    assert resultado.returncode == 2
    assert "mcp_bloqueado motivo=ref_main" in resultado.stderr


@pytest.mark.parametrize(
    ("ferramenta", "entrada"),
    [
        ("mcp__github__create_branch", {"branch": "claude/s1-x", "from_branch": "main"}),
        ("mcp__github__create_pull_request", {"head": "claude/s1-x", "base": "main"}),
        ("mcp__github__push_files", {"branch": "claude/s1-x", "files": []}),
        ("mcp__github__create_or_update_file", {"branch": "mainline", "path": "a"}),
        ("mcp__github__pull_request_read", {"method": "get", "pullNumber": 3}),
        ("mcp__github__update_pull_request", {"pullNumber": 3, "draft": False}),
    ],
)
def test_ferramenta_fora_de_main_e_permitida(ferramenta: str, entrada: dict[str, object]) -> None:
    resultado = _executar(ferramenta, entrada)
    assert resultado.returncode == 0, resultado.stderr


def test_orquestrador_pode_mesclar_pr() -> None:
    entrada = {"owner": "o", "repo": "r", "pullNumber": 1, "merge_method": "squash"}
    resultado = _executar("mcp__github__merge_pull_request", entrada, papel="orquestrador")
    assert resultado.returncode == 0, resultado.stderr


@pytest.mark.parametrize(
    ("ferramenta", "entrada"),
    [
        ("mcp__github__push_files", {"branch": "main", "files": []}),
        ("mcp__github__create_or_update_file", {"branch": "refs/heads/main", "path": "a"}),
        ("mcp__github__enable_pr_auto_merge", {"pullNumber": 1}),
        ("mcp__github__delete_file", {"branch": "claude/s1-x", "path": "a"}),
    ],
)
def test_orquestrador_nao_escreve_em_main_nem_usa_outras_proibidas(
    ferramenta: str, entrada: dict[str, object]
) -> None:
    resultado = _executar(ferramenta, entrada, papel="orquestrador")
    assert resultado.returncode == 2
    assert "mcp_bloqueado motivo=" in resultado.stderr


@pytest.mark.parametrize("papel", ["", "s1", "ORQUESTRADOR", "orquestrador-falso"])
def test_outro_papel_nao_libera_merge(papel: str) -> None:
    resultado = _executar("mcp__github__merge_pull_request", {"pullNumber": 1}, papel=papel)
    assert resultado.returncode == 2
    assert "mcp_bloqueado motivo=merge_pull_request" in resultado.stderr


@pytest.mark.parametrize("entrada", ["nao e json", "[]", '{"tool_name": 3}'])
def test_entrada_invalida_e_recusada(entrada: str) -> None:
    resultado = _executar_bruto(entrada)
    assert resultado.returncode == 2
    assert "mcp_bloqueado motivo=entrada_invalida" in resultado.stderr


def test_ferramenta_fora_do_github_e_permitida() -> None:
    assert _executar("mcp__Claude_Docs__read", {"ref": "main"}).returncode == 0


def test_guarda_esta_registrada_para_as_ferramentas_mcp_do_github() -> None:
    configuracao = json.loads(CONFIGURACAO.read_text(encoding="utf-8"))
    registros = configuracao["hooks"]["PreToolUse"]
    guardas = [
        registro
        for registro in registros
        if any("bloquear_mcp_github.py" in gancho["command"] for gancho in registro["hooks"])
    ]
    assert len(guardas) == 1
    padrao = guardas[0]["matcher"]
    assert re.fullmatch(padrao, "mcp__github__merge_pull_request")
    assert re.fullmatch(padrao, "mcp__github__push_files")
    assert not re.fullmatch(padrao, "Bash")
