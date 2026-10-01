import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "bloquear-push-perigoso.sh"


def _executar(comando: str) -> subprocess.CompletedProcess[str]:
    entrada = json.dumps({"tool_name": "Bash", "tool_input": {"command": comando}})
    return subprocess.run(
        ["bash", str(HOOK)], input=entrada, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    "comando",
    [
        "git push --force origin claude/s1-x",
        "git push -f origin claude/s1-x",
        "git push origin --force claude/s1-x",
        "git push --force-with-lease origin claude/s1-x",
        "git push origin +HEAD:claude/s1-x",
        "git push origin HEAD:main",
        "git push origin main",
        "git push -u origin main",
        "git push origin refs/heads/main",
        "git push origin --delete claude/s1-x",
        "git push origin :claude/s1-x",
        "uv run git push --force origin claude/s1-x",
        "bash -c 'git push origin HEAD:main'",
        "cd repo && git push origin main",
        "git -C repo push origin main",
    ],
)
def test_push_perigoso_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        "git push -u origin claude/s1-bitemporal",
        "git push origin claude/s2-dbc-sia-pa",
        "git push -u origin HEAD:claude/s3-referencias-piloto",
        "git status",
        "uv run pytest -q",
        "git log --oneline -3 main",
    ],
)
def test_comando_seguro_e_permitido(comando: str) -> None:
    assert _executar(comando).returncode == 0
