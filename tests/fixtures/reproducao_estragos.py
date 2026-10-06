"""Estragos de arquivo da varredura do `reproduce`: diretório no lugar, sem permissão e bytes (T14).

Cada estrago vale até sair do bloco e devolve o arquivo como estava (conteúdo, modo e tipo).
`Dano.PERMISSAO` pula o teste quando o processo lê arquivo sem permissão (root com
`CAP_DAC_OVERRIDE`): ali a permissão não se nega, e rodá-lo daria um resultado que não é o do dano.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sustemporal.reporting.reproduce_varredura import Dano

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["BYTES_ILEGIVEIS", "estragado", "permissao_se_nega"]

BYTES_ILEGIVEIS = b"\xff\xfe\x00\xc3\x28 bytes que nao sao utf-8 \x80\x81\n"


@cache
def permissao_se_nega() -> bool:
    """Se o processo, sem permissão de leitura num arquivo, deixa de lê-lo (não é root com DAC)."""
    with tempfile.TemporaryDirectory() as pasta:
        sonda = Path(pasta) / "sonda"
        sonda.write_text("x", encoding="utf-8")
        sonda.chmod(0)
        try:
            sonda.read_text(encoding="utf-8")
        except PermissionError:
            return True
        return False


@contextmanager
def _diretorio(caminho: Path, _binario: bool) -> Iterator[None]:
    guardado = caminho.with_name(f"{caminho.name}.original")
    caminho.rename(guardado)
    caminho.mkdir()
    try:
        yield
    finally:
        shutil.rmtree(caminho)
        guardado.rename(caminho)


@contextmanager
def _permissao(caminho: Path, _binario: bool) -> Iterator[None]:
    modo = caminho.stat().st_mode
    caminho.chmod(0)
    try:
        yield
    finally:
        caminho.chmod(modo)


@contextmanager
def _bytes(caminho: Path, binario: bool) -> Iterator[None]:
    dados, modo = caminho.read_bytes(), caminho.stat().st_mode
    caminho.write_bytes(dados[: max(1, len(dados) // 2)] if binario else BYTES_ILEGIVEIS)
    try:
        yield
    finally:
        caminho.write_bytes(dados)
        caminho.chmod(modo)


_ESTRAGOS = {Dano.DIRETORIO: _diretorio, Dano.PERMISSAO: _permissao, Dano.BYTES: _bytes}


@contextmanager
def estragado(caminho: Path, dano: Dano, *, binario: bool = False) -> Iterator[None]:
    """`caminho` estragado como `dano` até sair do bloco, e depois como estava.

    `binario` escolhe o estrago de `Dano.BYTES`: o arquivo truncado à metade (binário) ou
    `BYTES_ILEGIVEIS` no lugar do conteúdo (texto, que não decodifica como UTF-8).
    """
    if dano is Dano.PERMISSAO and not permissao_se_nega():
        pytest.skip("o processo lê arquivo sem permissão (root com CAP_DAC_OVERRIDE)")
    with _ESTRAGOS[dano](caminho, binario):
        yield
