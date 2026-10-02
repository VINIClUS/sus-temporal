"""Transportes de aquisição (ftp, https, file) atrás de uma interface pequena."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from typing import BinaryIO

__all__ = [
    "ErroTransporte",
    "LimiteExcedido",
    "Recebimento",
    "RecursoNaoEncontrado",
    "TransferenciaInterrompida",
    "Transporte",
    "TransporteArquivo",
    "TransporteFTP",
    "TransporteHTTPS",
    "transportes_padrao",
]


class ErroTransporte(Exception):
    """Falha do transporte; `recebidos` conta os bytes já gravados no temporário."""

    def __init__(self, mensagem: str, recebidos: int = 0) -> None:
        super().__init__(mensagem)
        self.recebidos = recebidos


class RecursoNaoEncontrado(ErroTransporte):
    """O servidor respondeu que o recurso não existe."""


class TransferenciaInterrompida(ErroTransporte):
    """A transferência começou e não terminou."""


class LimiteExcedido(ErroTransporte):
    """O conteúdo passou do tamanho máximo da requisição."""


@dataclass(frozen=True)
class Recebimento:
    bytes_recebidos: int
    tamanho_anunciado: int | None = None
    metadados: dict[str, str] = field(default_factory=dict)


class Transporte(Protocol):
    def baixar(self, localizador: str, destino: BinaryIO, limite: int) -> Recebimento: ...

    def listar(self, localizador: str) -> list[str]: ...


class TransporteArquivo:
    """Cópia local (`file://`), para testes e importação manual."""

    def baixar(self, localizador: str, destino: BinaryIO, limite: int) -> Recebimento:
        raise NotImplementedError

    def listar(self, localizador: str) -> list[str]:
        raise NotImplementedError


class TransporteFTP:
    """FTP anônimo em modo passivo."""

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def baixar(self, localizador: str, destino: BinaryIO, limite: int) -> Recebimento:
        raise NotImplementedError

    def listar(self, localizador: str) -> list[str]:
        raise NotImplementedError


class TransporteHTTPS:
    """HTTPS com timeout; não lista diretórios."""

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def baixar(self, localizador: str, destino: BinaryIO, limite: int) -> Recebimento:
        raise NotImplementedError

    def listar(self, localizador: str) -> list[str]:
        raise NotImplementedError


def transportes_padrao() -> dict[str, Transporte]:
    raise NotImplementedError
