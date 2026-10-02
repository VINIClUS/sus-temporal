import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "bloquear_push_perigoso.py"


def _executar(comando: str) -> subprocess.CompletedProcess[str]:
    entrada = json.dumps({"tool_name": "Bash", "tool_input": {"command": comando}})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=entrada, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    "comando",
    [
        "git push --force origin claude/s1-x",
        "git push -f origin claude/s1-x",
        "git push origin --force claude/s1-x",
        "git push --force-with-lease origin claude/s1-x",
        "git push --force-if-includes origin claude/s1-x",
        "git push origin +HEAD:claude/s1-x",
        "git push origin HEAD:main",
        "git push origin main",
        "git push -u origin main",
        "git push origin refs/heads/main",
        "git push origin HEAD:refs/heads/main",
        "git push origin --delete claude/s1-x",
        "git push origin -d claude/s1-x",
        "git push origin :claude/s1-x",
        "git push --mirror origin",
        "git push --all origin",
        "uv run git push --force origin claude/s1-x",
        "bash -c 'git push origin HEAD:main'",
        'sh -c "git push -f origin claude/s1-x"',
        "cd repo && git push origin main",
        "git status; git push origin main",
        "git -C repo push origin main",
        "git -c core.askPass=x push --force origin claude/s1-x",
        "uv run git -c core.askPass=x push --force origin claude/s1-x",
        "git --no-pager push origin main",
        "git --git-dir=.git --work-tree=. push origin main",
        "/usr/bin/git push origin main",
        "env GIT_TRACE=1 git push -f origin claude/s1-x",
        "bash -lc 'git push origin main'",
        "bash -ec 'git push -f origin claude/s1-x'",
        "bash -c -e 'git push origin main'",
        "bash -o pipefail -c 'git push origin main'",
        "eval 'git push --force origin claude/s1-x'",
        "git -c alias.p=push p -f origin claude/s1-x",
        "git -c alias.p=push p origin main",
        "P=push git --config-env=alias.p=P p origin main",
        "git --config-env alias.p=P p -f origin claude/s1-x",
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
        "git -c user.name=x push -u origin claude/s4-motor-regras",
        "git status",
        "uv run pytest -q",
        "git log --oneline -3 main",
        "git fetch origin main",
        "git merge --no-edit origin/main",
        "echo 'git push origin main' > notas.txt",
        "bash -lc 'git status'",
        "bash -c 'git push -u origin claude/s1-x'",
        "git commit -m 'bloqueia git push origin main'",
        "git -c alias.st=status st",
    ],
)
def test_comando_seguro_e_permitido(comando: str) -> None:
    assert _executar(comando).returncode == 0


def test_entrada_que_nao_e_bash_e_permitida() -> None:
    entrada = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    resultado = subprocess.run(
        [sys.executable, str(HOOK)], input=entrada, capture_output=True, text=True, check=False
    )
    assert resultado.returncode == 0
