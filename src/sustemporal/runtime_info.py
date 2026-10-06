"""Versão do código e ambiente de execução para registro de execuções."""

from __future__ import annotations

import hashlib
import os
import platform
import stat
import subprocess
from importlib import metadata
from pathlib import Path

from sustemporal.contracts.experiment import Ambiente, CodeVersion

# Raiz do checkout que contém o pacote: o código e o `uv.lock` registrados são os dele, nunca os
# do diretório de trabalho (rodar de outra pasta não troca o commit registrado).
RAIZ_DO_PACOTE = Path(__file__).resolve().parents[2]

PACOTES_RELEVANTES = (
    "sus-temporal",
    "duckdb",
    "pyarrow",
    "pydantic",
    "pyyaml",
    "numpy",
    "scikit-learn",
    "prov",
    "datasus-dbc",
    "dbc-to-dbf",
    "dbfread",
)


def _git_bytes(raiz: Path, *argumentos: str) -> bytes | None:
    try:
        resultado = subprocess.run(  # noqa: S603
            ["git", *argumentos],  # noqa: S607
            cwd=raiz,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return resultado.stdout


def _git(raiz: Path, *argumentos: str) -> str | None:
    saida = _git_bytes(raiz, *argumentos)
    return None if saida is None else saida.decode("utf-8", errors="surrogateescape").strip()


def _estado_do_caminho(caminho: Path) -> bytes | None:
    """Tipo, bit executável e conteúdo como o git os registraria.

    Link pelo alvo, arquivo pelo hash, diretório sem abri-lo (o que há dentro vem da listagem do
    git). Repositório aninhado, cujo conteúdo essa listagem não enumera, e falha de leitura
    resultam em None.
    """
    try:
        if caminho.is_symlink():
            return b"link\0" + os.fsencode(os.readlink(caminho))
        if not caminho.exists():
            return b"ausente"
        if caminho.is_dir():
            return None if (caminho / ".git").exists() else b"diretorio"
        executavel = os.lstat(caminho).st_mode & stat.S_IXUSR
        with caminho.open("rb") as arquivo:
            digest = hashlib.file_digest(arquivo, "sha256").hexdigest()
    except OSError:
        return None
    tipo = b"arquivo-exec" if executavel else b"arquivo"
    return tipo + b"\0" + digest.encode("ascii")


def _hash_diferencas(raiz: Path) -> str | None:
    """SHA-256 do estado de cada caminho alterado em relação ao HEAD ou não rastreado.

    Hash do conteúdo, nunca do texto do diff (que depende da configuração do git). Tudo é lido a
    partir do topo do repositório; falha em qualquer caminho resulta em None, nunca hash parcial.
    """
    topo = _git(raiz, "rev-parse", "--show-toplevel")
    if not topo:
        return None
    base = Path(topo)
    alterados = _git_bytes(base, "diff", "--name-only", "--no-renames", "-z", "HEAD")
    novos = _git_bytes(base, "ls-files", "--others", "--exclude-standard", "-z")
    if alterados is None or novos is None:
        return None
    resumo = hashlib.sha256()
    for caminho in sorted({nome for nome in (alterados + novos).split(b"\0") if nome}):
        estado = _estado_do_caminho(base / os.fsdecode(caminho))
        if estado is None:
            return None
        resumo.update(caminho + b"\0" + estado + b"\0")
    return resumo.hexdigest()


def versao_codigo(raiz: Path = RAIZ_DO_PACOTE) -> CodeVersion:
    commit = _git(raiz, "rev-parse", "HEAD")
    estado = _git(raiz, "status", "--porcelain", "--untracked-files=all")
    sujo = commit is None or estado is None or bool(estado)
    return CodeVersion(
        commit=commit or "desconhecido",
        sujo=sujo,
        versao_pacote=metadata.version("sus-temporal"),
        diff_sha256=_hash_diferencas(raiz) if sujo and commit is not None else None,
    )


def _versao(pacote: str) -> str:
    try:
        return metadata.version(pacote)
    except metadata.PackageNotFoundError:
        return "ausente"


def ambiente(raiz: Path = RAIZ_DO_PACOTE) -> Ambiente:
    trava = raiz / "uv.lock"
    return Ambiente(
        python=platform.python_version(),
        plataforma=platform.platform(),
        pacotes={pacote: _versao(pacote) for pacote in PACOTES_RELEVANTES},
        uv_lock_sha256=hashlib.sha256(trava.read_bytes()).hexdigest() if trava.exists() else None,
    )
