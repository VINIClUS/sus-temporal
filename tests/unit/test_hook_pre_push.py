"""Hook pre-push do git (`.githooks/pre-push`) e sua instalação pelo SessionStart."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
HOOKS = RAIZ / ".githooks"
PRE_PUSH = HOOKS / "pre-push"
SESSION_START = RAIZ / ".claude" / "hooks" / "session-start.sh"
_IDENTIDADE = ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false")
_ZERO = "0" * 40


def _git(repo: Path, *argumentos: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *_IDENTIDADE, *argumentos], cwd=repo, check=check, capture_output=True, text=True
    )


def _commit(repo: Path, mensagem: str) -> str:
    _git(repo, "commit", "-q", "--allow-empty", "-m", mensagem)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _push(repo: Path, *argumentos: str) -> subprocess.CompletedProcess[str]:
    return _git(repo, "push", "-q", *argumentos, check=False)


def _ref_remota(remoto: Path, ref: str) -> str:
    resultado = subprocess.run(
        ["git", "--git-dir", str(remoto), "rev-parse", "--verify", "-q", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    return resultado.stdout.strip()


@pytest.fixture
def remoto(tmp_path: Path) -> Path:
    caminho = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", str(caminho)], check=True)
    return caminho


@pytest.fixture
def repo(tmp_path: Path, remoto: Path) -> Path:
    local = tmp_path / "local"
    subprocess.run(["git", "init", "-q", "-b", "main", str(local)], check=True)
    _commit(local, "base")
    _git(local, "remote", "add", "origin", str(remoto))
    _git(local, "push", "-q", "-u", "origin", "main")
    _git(local, "config", "core.hooksPath", str(HOOKS))
    _git(local, "checkout", "-q", "-b", "claude/s1-x")
    return local


def test_hook_pre_push_e_executavel() -> None:
    assert PRE_PUSH.is_file()
    assert os.access(PRE_PUSH, os.X_OK)


@pytest.mark.parametrize("refspec", ["HEAD:main", "HEAD:refs/heads/main", "claude/s1-x:main"])
def test_push_para_main_e_recusado(repo: Path, remoto: Path, refspec: str) -> None:
    antes = _ref_remota(remoto, "refs/heads/main")
    _commit(repo, "nova")
    resultado = _push(repo, "origin", refspec)
    assert resultado.returncode != 0
    assert "push_bloqueado motivo=push_para_main" in resultado.stderr
    assert _ref_remota(remoto, "refs/heads/main") == antes


@pytest.mark.parametrize("argumentos", [("--delete", "claude/s1-x"), (":claude/s1-x",)])
def test_remocao_de_branch_remoto_e_recusada(
    repo: Path, remoto: Path, argumentos: tuple[str, ...]
) -> None:
    publicado = _commit(repo, "trabalho")
    assert _push(repo, "origin", "claude/s1-x").returncode == 0
    resultado = _push(repo, "origin", *argumentos)
    assert resultado.returncode != 0
    assert "push_bloqueado motivo=remocao" in resultado.stderr
    assert _ref_remota(remoto, "refs/heads/claude/s1-x") == publicado


@pytest.mark.parametrize(
    "argumentos", [("--force", "origin", "claude/s1-x"), ("origin", "+claude/s1-x")]
)
def test_push_nao_fast_forward_e_recusado(
    repo: Path, remoto: Path, argumentos: tuple[str, ...]
) -> None:
    publicado = _commit(repo, "primeira")
    assert _push(repo, "origin", "claude/s1-x").returncode == 0
    _git(repo, "commit", "-q", "--amend", "--allow-empty", "-m", "reescrita")
    resultado = _push(repo, *argumentos)
    assert resultado.returncode != 0
    assert "push_bloqueado motivo=nao_fast_forward" in resultado.stderr
    assert _ref_remota(remoto, "refs/heads/claude/s1-x") == publicado


def test_push_sobre_objeto_remoto_desconhecido_e_recusado(
    repo: Path, remoto: Path, tmp_path: Path
) -> None:
    _commit(repo, "primeira")
    assert _push(repo, "origin", "claude/s1-x").returncode == 0
    outro = tmp_path / "outro"
    subprocess.run(
        ["git", "clone", "-q", "-b", "claude/s1-x", str(remoto), str(outro)],
        check=True,
        capture_output=True,
    )
    desconhecido = _commit(outro, "de outro clone")
    _git(outro, "push", "-q", "origin", "claude/s1-x")
    _commit(repo, "local")
    resultado = _push(repo, "--force", "origin", "claude/s1-x")
    assert resultado.returncode != 0
    assert "push_bloqueado motivo=nao_fast_forward" in resultado.stderr
    assert _ref_remota(remoto, "refs/heads/claude/s1-x") == desconhecido


def test_push_normal_de_branch_de_sessao_e_aceito(repo: Path, remoto: Path) -> None:
    _commit(repo, "primeira")
    assert _push(repo, "-u", "origin", "claude/s1-x").returncode == 0
    segunda = _commit(repo, "segunda")
    resultado = _push(repo, "origin", "claude/s1-x")
    assert resultado.returncode == 0, resultado.stderr
    assert _ref_remota(remoto, "refs/heads/claude/s1-x") == segunda


@pytest.mark.parametrize(
    ("expansao", "argumentos"),
    [("push", ("p", "origin", "HEAD:main")), ("!git push origin HEAD:main", ("p",))],
)
def test_alias_persistido_para_push_e_recusado_pelo_pre_push(
    repo: Path, remoto: Path, expansao: str, argumentos: tuple[str, ...]
) -> None:
    antes = _ref_remota(remoto, "refs/heads/main")
    _git(repo, "config", "alias.p", expansao)
    _commit(repo, "nova")
    resultado = _git(repo, *argumentos, check=False)
    assert resultado.returncode != 0
    assert "push_bloqueado motivo=push_para_main" in resultado.stderr
    assert _ref_remota(remoto, "refs/heads/main") == antes


def _executar_hook(entrada: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PRE_PUSH), "origin", "url"],
        input=entrada,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("entrada", ["lixo\n", f"refs/heads/x {'a' * 40} refs/heads/x\n"])
def test_linha_fora_do_formato_e_recusada(entrada: str) -> None:
    resultado = _executar_hook(entrada)
    assert resultado.returncode == 1
    assert "push_bloqueado motivo=entrada_invalida" in resultado.stderr


def test_remocao_com_sha256_tambem_e_recusada() -> None:
    resultado = _executar_hook(f"(delete) {'0' * 64} refs/heads/claude/s1-x {'b' * 64}\n")
    assert resultado.returncode == 1
    assert "push_bloqueado motivo=remocao" in resultado.stderr


def test_entrada_vazia_e_aceita() -> None:
    assert _executar_hook("").returncode == 0


def test_criacao_de_branch_novo_e_aceita() -> None:
    resultado = _executar_hook(
        f"refs/heads/claude/s1-x {'a' * 40} refs/heads/claude/s1-x {_ZERO}\n"
    )
    assert resultado.returncode == 0, resultado.stderr


def _session_start(
    projeto: Path, tmp_path: Path, *, remoto: bool
) -> tuple[subprocess.CompletedProcess[str], Path]:
    binarios = tmp_path / "bin"
    binarios.mkdir()
    registro = tmp_path / "uv.log"
    falso = binarios / "uv"
    falso.write_text(
        '#!/bin/sh\ngit config --get core.hooksPath >> "$UV_REGISTRO"\n'
        'echo "$@" >> "$UV_REGISTRO"\n',
        encoding="utf-8",
    )
    falso.chmod(0o755)
    ambiente = {
        chave: valor for chave, valor in os.environ.items() if chave != "CLAUDE_CODE_REMOTE"
    }
    ambiente |= {
        "CLAUDE_PROJECT_DIR": str(projeto),
        "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
        "UV_REGISTRO": str(registro),
    }
    if remoto:
        ambiente["CLAUDE_CODE_REMOTE"] = "true"
    resultado = subprocess.run(
        ["bash", str(SESSION_START)], env=ambiente, capture_output=True, text=True, check=False
    )
    return resultado, registro


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    caminho = tmp_path / "projeto"
    subprocess.run(["git", "init", "-q", "-b", "main", str(caminho)], check=True)
    return caminho


def test_session_start_instala_hooks_mesmo_fora_do_remoto(projeto: Path, tmp_path: Path) -> None:
    resultado, registro = _session_start(projeto, tmp_path, remoto=False)
    assert resultado.returncode == 0, resultado.stderr
    instalado = _git(projeto, "config", "--get", "core.hooksPath", check=False)
    assert instalado.stdout.strip() == ".githooks"
    assert not registro.exists()


def test_session_start_instala_hooks_antes_do_uv_sync_no_remoto(
    projeto: Path, tmp_path: Path
) -> None:
    resultado, registro = _session_start(projeto, tmp_path, remoto=True)
    assert resultado.returncode == 0, resultado.stderr
    assert registro.read_text(encoding="utf-8").splitlines() == [".githooks", "sync --locked"]
