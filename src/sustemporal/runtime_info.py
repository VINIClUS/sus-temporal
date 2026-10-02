"""Versão do código e ambiente de execução para registro de execuções."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from importlib import metadata
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import Ambiente, CodeVersion

if TYPE_CHECKING:
    from pathlib import Path

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


def _git(raiz: Path, *argumentos: str) -> str | None:
    try:
        resultado = subprocess.run(  # noqa: S603
            ["git", *argumentos],  # noqa: S607
            cwd=raiz,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return resultado.stdout.strip()


def versao_codigo(raiz: Path) -> CodeVersion:
    commit = _git(raiz, "rev-parse", "HEAD")
    estado = _git(raiz, "status", "--porcelain")
    return CodeVersion(
        commit=commit or "desconhecido",
        sujo=commit is None or estado is None or bool(estado),
        versao_pacote=metadata.version("sus-temporal"),
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
