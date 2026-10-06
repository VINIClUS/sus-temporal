"""Estragos de arquivo da varredura do `reproduce`: diretório no lugar, sem permissão e bytes (T14).

`estragado` estraga o arquivo de verdade até sair do bloco e o devolve como estava (conteúdo, modo e
tipo); `Dano.PERMISSAO` pula o teste quando o processo lê arquivo sem permissão (root com
`CAP_DAC_OVERRIDE`): ali a permissão não se nega, e rodá-lo daria um resultado que não é o do dano.
`estragado_na_abertura` não toca no arquivo: a abertura dele falha com o erro que o dano daria, por
um gancho de auditoria do Python (`sys.addaudithook`); serve aos catálogos do clone, que um teste
não estraga, e roda também como root. `aberturas` lista o que o Python abre no bloco. O gancho fica
instalado até o fim do processo e não faz nada fora desses blocos.
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.reporting.reproduce_varredura import Dano

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "BYTES_ILEGIVEIS",
    "aberturas",
    "estragado",
    "estragado_na_abertura",
    "permissao_se_nega",
]

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


@dataclass
class _Auditoria:
    instalada: bool = False
    falhas: dict[str, Dano] = field(default_factory=dict)
    abertas: list[tuple[str, str]] | None = None


_AUDITORIA = _Auditoria()


def _erro_da_abertura(dano: Dano, nome: str) -> Exception:
    if dano is Dano.DIRETORIO:
        return IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), nome)
    if dano is Dano.PERMISSAO:
        return PermissionError(errno.EACCES, os.strerror(errno.EACCES), nome)
    return UnicodeDecodeError("utf-8", BYTES_ILEGIVEIS, 0, 1, "invalid start byte")


def _modo_de_leitura(modo: object, flags: object) -> bool:
    """Se a abertura lê (`r`, `+`) ou é de trava (`a`); em `os.open`, a que não é só de escrita."""
    if isinstance(modo, str):
        return any(letra in modo for letra in "ra+")
    return isinstance(flags, int) and not flags & os.O_WRONLY


def _gancho(evento: str, argumentos: tuple[Any, ...]) -> None:
    if evento != "open" or not (_AUDITORIA.falhas or _AUDITORIA.abertas is not None):
        return
    caminho, modo, flags = argumentos
    if not isinstance(caminho, str | bytes | os.PathLike):
        return
    nome = os.path.abspath(os.fsdecode(caminho))
    if not _modo_de_leitura(modo, flags):
        return
    if _AUDITORIA.abertas is not None:
        _AUDITORIA.abertas.append((nome, str(modo)))
    if (dano := _AUDITORIA.falhas.get(nome)) is not None:
        raise _erro_da_abertura(dano, nome)


def _instalar() -> None:
    if not _AUDITORIA.instalada:
        sys.addaudithook(_gancho)
        _AUDITORIA.instalada = True


@contextmanager
def estragado_na_abertura(caminho: Path, dano: Dano) -> Iterator[None]:
    """A abertura de `caminho` falha como o `dano` faria, sem tocar no arquivo.

    `Dano.DIRETORIO` dá `IsADirectoryError`, `Dano.PERMISSAO` dá `PermissionError` e `Dano.BYTES`
    dá `UnicodeDecodeError`, na primeira abertura para ler e em todas as seguintes até o fim do
    bloco.
    """
    _instalar()
    chave = os.path.abspath(caminho)
    _AUDITORIA.falhas[chave] = dano
    try:
        yield
    finally:
        del _AUDITORIA.falhas[chave]


@contextmanager
def aberturas() -> Iterator[list[tuple[str, str]]]:
    """Os arquivos que o Python abre para ler no bloco: `(caminho absoluto, modo)`, na ordem."""
    _instalar()
    lidas: list[tuple[str, str]] = []
    _AUDITORIA.abertas = lidas
    try:
        yield lidas
    finally:
        _AUDITORIA.abertas = None
