"""Versão do código e ambiente de execução para registro de execuções."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from importlib import metadata
from pathlib import Path

from sustemporal.contracts.experiment import Ambiente, CodeVersion

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


def _hash_arquivo(caminho: Path) -> bytes | None:
    try:
        with caminho.open("rb") as arquivo:
            return hashlib.file_digest(arquivo, "sha256").hexdigest().encode("ascii")
    except OSError:
        return None


def _hash_diferencas(raiz: Path) -> str | None:
    """SHA-256 do diff binário contra o HEAD e do conteúdo dos arquivos não rastreados.

    Tudo é lido a partir do topo do repositório, para o diff e a listagem terem o mesmo escopo.
    """
    topo = _git(raiz, "rev-parse", "--show-toplevel")
    if not topo:
        return None
    base = Path(topo)
    diff = _git_bytes(base, "diff", "--binary", "--no-color", "--no-ext-diff", "HEAD")
    novos = _git_bytes(base, "ls-files", "--others", "--exclude-standard", "-z")
    if diff is None or novos is None:
        return None
    resumo = hashlib.sha256(b"diff\0" + diff + b"\0nao_rastreados\0")
    for caminho in sorted(nome for nome in novos.split(b"\0") if nome):
        conteudo = _hash_arquivo(base / caminho.decode("utf-8", errors="surrogateescape"))
        if conteudo is None:
            return None
        resumo.update(caminho + b"\0" + conteudo + b"\0")
    return resumo.hexdigest()


def versao_codigo(raiz: Path) -> CodeVersion:
    commit = _git(raiz, "rev-parse", "HEAD")
    estado = _git(raiz, "status", "--porcelain")
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


def ambiente(raiz: Path) -> Ambiente:
    trava = raiz / "uv.lock"
    return Ambiente(
        python=platform.python_version(),
        plataforma=platform.platform(),
        pacotes={pacote: _versao(pacote) for pacote in PACOTES_RELEVANTES},
        uv_lock_sha256=hashlib.sha256(trava.read_bytes()).hexdigest() if trava.exists() else None,
    )
