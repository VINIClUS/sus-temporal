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
        "git -c alias.push=status push origin main",
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


@pytest.mark.parametrize(
    "comando",
    [
        "git push --no-verify origin claude/s1-x",
        "git push origin claude/s1-x --no-verify",
        "git push --no-verif -u origin claude/s1-x",
        "git -c alias.p='push --no-verify' p origin claude/s1-x",
        "bash -c 'git push --no-verify origin claude/s1-x'",
    ],
)
def test_push_sem_verificacao_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        'echo "$(git push --no-verify origin HEAD:main)"',
        "echo `git push --no-verify origin HEAD:main`",
        'echo "`git push --no-verify origin claude/s1-x`"',
        'echo "$(echo ")"; git push --no-verify origin HEAD:main)"',
        'X="$(git -c core.hooksPath=/dev/null push origin claude/s1-x)"',
        "cat <(git push --force origin claude/s1-x)",
        "echo \"$(bash -c 'git push --no-verify origin claude/s1-x')\"",
        'echo "${X:-$(git push --no-verify origin claude/s1-x)}"',
        'git push -u origin "$(git branch --show-current)"',
    ],
)
def test_substituicao_de_comando_e_inspecionada(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        'echo "$(git rev-parse HEAD)"',
        "git commit -m \"$(printf 'feat: x\\n\\ncorpo')\"",
        "git commit -m \"$(cat <<'EOF'\nfeat(x): descreve a mudança\nEOF\n)\"",
        "echo $((1 + 2))",
    ],
)
def test_substituicao_segura_continua_permitida(comando: str) -> None:
    assert _executar(comando).returncode == 0


@pytest.mark.parametrize(
    "comando",
    [
        "x=; y=; git push --no${x}-verify origin HEAD:${y}main",
        "git push origin HEAD:$ALVO",
        "git push --no-{verify,x} origin claude/s1-x",
        "git push origin 'refs/heads/*:refs/heads/*'",
        "git ${x}push --no-verify origin claude/s1-x",
        "git {push,x} origin claude/s1-x",
        'git -c "$CONFIG" push origin claude/s1-x',
        "g=git; $g push --no-verify origin claude/s1-x",
        "$g $p origin claude/s1-x",
        "env $g push --no-verify origin claude/s1-x",
        "uv run $g push --no-verify origin claude/s1-x",
    ],
)
def test_expansao_em_push_falha_fechado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        (
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null "
            "git push origin claude/s1-x"
        ),
        "export GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\"; git push origin x",
        "env GIT_CONFIG_GLOBAL=/tmp/outro git push origin claude/s1-x",
        "git config core.hooksPath /dev/null",
        "git config --global core.hooksPath ''",
        "git config --unset core.hooksPath",
        "git config set core.hooksPath /tmp/vazio",
    ],
)
def test_desvio_de_hooks_por_ambiente_ou_config_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        'git commit -m "$MSG"',
        '"$PYTHON" -m pytest -q',
        'cp "$ORIGEM" "$DESTINO"',
        "git config core.hooksPath .githooks",
        "git config --get core.hooksPath",
        'echo "$HOME"',
        "GIT_TRACE=1 git status",
    ],
)
def test_expansao_fora_de_push_continua_permitida(comando: str) -> None:
    assert _executar(comando).returncode == 0


@pytest.mark.parametrize(
    "comando",
    [
        "git -c core.hooksPath=/dev/null push origin claude/s1-x",
        "git -c CORE.HOOKSPATH= push origin claude/s1-x",
        "git -c core.hooksPath=/tmp/vazio commit -m x",
        "git --config-env=core.hooksPath=VAZIO push origin claude/s1-x",
        "git --config-env core.hooksPath=VAZIO push origin claude/s1-x",
        "git -c alias.p='-c core.hooksPath=/dev/null push' p origin claude/s1-x",
    ],
)
def test_hooks_path_sobrescrito_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        "git send-pack ../remoto.git refs/heads/claude/s1-x",
        "git -C repo send-pack --force ../remoto.git main",
        "uv run git send-pack ../remoto.git claude/s1-x",
    ],
)
def test_send_pack_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        "gh pr merge 12 --squash",
        "gh pr merge --auto --squash 12",
        "gh pr -R VINIClUS/sus-temporal merge 12",
        "uv run gh pr merge 12",
        "bash -c 'gh pr merge 12 --squash'",
        "gh pr view 12 && gh pr merge 12",
    ],
)
def test_merge_de_pr_pelo_gh_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        "gh api -X DELETE repos/o/r/issues/1/labels/x",
        "gh api --method DELETE repos/o/r/branches/x/protection",
        "gh api --method=delete repos/o/r/hooks/1",
        "gh api -XDELETE repos/o/r/hooks/1",
        "gh api repos/o/r/merges -f base=main -f head=claude/s1-x",
        "gh api -X PUT repos/o/r/pulls/12/merge",
        "gh api repos/o/r/git/refs -f ref=refs/heads/x -f sha=abc",
        "gh api -X PATCH /repos/o/r/git/refs/heads/main -f sha=abc -F force=true",
        "gh api https://api.github.com/repos/o/r/pulls/12/merge -X PUT",
    ],
)
def test_gh_api_de_remocao_ou_merge_e_bloqueado(comando: str) -> None:
    resultado = _executar(comando)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


@pytest.mark.parametrize(
    "comando",
    [
        "gh pr view 12",
        "gh pr create --draft --title x --body y",
        "gh pr checks 12",
        "gh api repos/o/r/pulls/12",
        "gh api repos/o/r/pulls/12/comments -f body=ok",
        "gh api -X GET repos/o/r/commits/abc/check-runs",
        "git -c core.editor=true commit -m x",
        "git -c core.hooksPathx=1 status",
    ],
)
def test_gh_e_git_seguros_continuam_permitidos(comando: str) -> None:
    assert _executar(comando).returncode == 0


def test_entrada_que_nao_e_bash_e_permitida() -> None:
    entrada = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    resultado = subprocess.run(
        [sys.executable, str(HOOK)], input=entrada, capture_output=True, text=True, check=False
    )
    assert resultado.returncode == 0
