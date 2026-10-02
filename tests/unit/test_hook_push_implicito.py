import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "bloquear_push_perigoso.py"


def _git(repo: Path, *argumentos: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *argumentos],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _executar(comando: str, repo: Path) -> subprocess.CompletedProcess[str]:
    entrada = json.dumps({"tool_name": "Bash", "tool_input": {"command": comando}})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=entrada,
        capture_output=True,
        text=True,
        check=False,
        cwd=repo,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remoto = tmp_path / "remoto.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "-q", "--bare", str(remoto)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(local)], check=True)
    _git(
        local,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    _git(local, "remote", "add", "origin", str(remoto))
    _git(local, "push", "-q", "-u", "origin", "main")
    return local


@pytest.mark.parametrize(
    "comando",
    [
        "git push",
        "git push origin",
        "git push -u origin",
        "git push origin HEAD",
        "git push origin @",
    ],
)
def test_push_implicito_estando_em_main_e_bloqueado(repo: Path, comando: str) -> None:
    resultado = _executar(comando, repo)
    assert resultado.returncode == 2
    assert "push_bloqueado" in resultado.stderr


def test_push_implicito_para_upstream_main_e_bloqueado(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    _git(repo, "branch", "-q", "-u", "origin/main")
    assert _executar("git push", repo).returncode == 2


def test_push_implicito_de_branch_proprio_e_permitido(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    _git(repo, "push", "-q", "-u", "origin", "claude/s1-x")
    assert _executar("git push", repo).returncode == 0
    assert _executar("git push origin HEAD", repo).returncode == 0


@pytest.mark.parametrize(
    "comando",
    [
        "git commit -m 'corrige #12' && git push origin main",
        "git log -1 --format=%h#%s && git push origin HEAD:main",
        "git push origin HEAD:heads/main",
    ],
)
def test_push_perigoso_disfarcado_e_bloqueado(repo: Path, comando: str) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    assert _executar(comando, repo).returncode == 2


@pytest.fixture
def outro(repo: Path, tmp_path: Path) -> Path:
    clone = tmp_path / "outro"
    subprocess.run(
        ["git", "clone", "-q", "-b", "main", str(tmp_path / "remoto.git"), str(clone)],
        check=True,
        capture_output=True,
    )
    _git(clone, "checkout", "-q", "-b", "claude/s1-x")
    _git(clone, "push", "-q", "-u", "origin", "claude/s1-x")
    return clone


@pytest.mark.parametrize(
    "modelo",
    [
        "git -C {repo} push",
        "git -C {repo} push origin HEAD",
        "cd {repo} && git push",
        "cd {repo}; git push -u origin",
        "cd $REPO && git push",
        "cd ~/x && git push",
    ],
)
def test_push_implicito_no_repositorio_do_comando_e_bloqueado(
    repo: Path, outro: Path, modelo: str
) -> None:
    assert _executar(modelo.format(repo=repo), outro).returncode == 2


def test_push_implicito_noutro_diretorio_de_branch_proprio_e_permitido(
    repo: Path, outro: Path
) -> None:
    assert _executar(f"cd {outro} && git push", repo).returncode == 0
    assert _executar(f"git -C {outro} push", repo).returncode == 0


@pytest.mark.parametrize(
    "comando", ["cd /definitivamente/inexistente || git push", "git -C /nao/existe push"]
)
def test_push_implicito_em_diretorio_nao_resolvido_e_bloqueado(repo: Path, comando: str) -> None:
    assert _executar(comando, repo).returncode == 2


@pytest.mark.parametrize(
    ("expansao", "comando"),
    [
        ("push", "git p origin main"),
        ("push -f", "git p origin claude/s1-x"),
        ("!git push -f", "git p"),
    ],
)
def test_alias_persistido_no_repositorio_e_resolvido(
    repo: Path, expansao: str, comando: str
) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    _git(repo, "config", "alias.p", expansao)
    assert _executar(comando, repo).returncode == 2


def test_alias_persistido_seguro_e_permitido(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    _git(repo, "config", "alias.p", "push")
    assert _executar("git p origin claude/s1-x", repo).returncode == 0
