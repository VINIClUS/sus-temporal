"""Transportes de aquisição (ftp, https, file) atrás de uma interface pequena."""

from __future__ import annotations

import contextlib
import ftplib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, override
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable
    from http.client import HTTPMessage

__all__ = [
    "ErroTransporte",
    "Escrita",
    "LimiteExcedido",
    "Recebimento",
    "RecursoNaoEncontrado",
    "RedirecionamentoSoHTTPS",
    "TransferenciaInterrompida",
    "Transporte",
    "TransporteArquivo",
    "TransporteFTP",
    "TransporteHTTPS",
    "transportes_padrao",
]

_BLOCO = 1024 * 1024
PRAZO_TOTAL = 4 * 3600.0
_HTTP_AUSENTE = {404, 410}
_CABECALHOS_HTTP = ("Content-Length", "Content-Type", "Last-Modified", "ETag")


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


class Escrita(Protocol):
    def write(self, dados: bytes, /) -> int: ...


class Transporte(Protocol):
    def baixar(self, localizador: str, destino: Escrita, limite: int) -> Recebimento: ...

    def listar(self, localizador: str) -> list[str]: ...


class _Gravador:
    """Grava blocos no destino e recusa passar do limite."""

    def __init__(self, destino: Escrita, limite: int, *, prazo: float | None = None) -> None:
        self.destino = destino
        self.limite = limite
        self.prazo = prazo
        self.recebidos = 0

    def __call__(self, bloco: bytes) -> None:
        if self.prazo is not None and time.monotonic() > self.prazo:
            raise TransferenciaInterrompida("prazo_total_excedido", self.recebidos)
        if self.recebidos + len(bloco) > self.limite:
            raise LimiteExcedido(f"tamanho_maximo_excedido limite={self.limite}", self.recebidos)
        self.destino.write(bloco)
        self.recebidos += len(bloco)

    def copiar(self, ler: Callable[[int], bytes]) -> None:
        while bloco := ler(_BLOCO):
            self(bloco)


def _falha(erro: Exception, recebidos: int) -> ErroTransporte:
    if isinstance(erro, ErroTransporte):
        return erro
    if recebidos:
        return TransferenciaInterrompida(f"transferencia_interrompida erro={erro}", recebidos)
    return ErroTransporte(f"falha_transporte erro={erro}")


def _instante_iso(segundos: float) -> str:
    return datetime.fromtimestamp(segundos, UTC).isoformat()


def _prazo(segundos: float | None) -> float | None:
    return None if segundos is None else time.monotonic() + segundos


class TransporteArquivo:
    """Cópia local (`file://`), para testes e importação manual.

    Recusa link simbólico; com `raiz`, recusa caminho que resolva fora dela.
    """

    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = raiz

    def _caminho(self, localizador: str) -> Path:
        caminho = Path(unquote(urlsplit(localizador).path))
        if caminho.is_symlink():
            raise ErroTransporte(f"link_simbolico_recusado caminho={caminho}")
        if self.raiz is not None and not caminho.resolve().is_relative_to(self.raiz.resolve()):
            raise ErroTransporte(f"caminho_fora_da_raiz caminho={caminho}")
        return caminho

    def baixar(self, localizador: str, destino: Escrita, limite: int) -> Recebimento:
        caminho = self._caminho(localizador)
        if not caminho.is_file():
            raise RecursoNaoEncontrado(f"arquivo_inexistente caminho={caminho}")
        info = caminho.stat()
        gravador = _Gravador(destino, limite)
        with caminho.open("rb") as origem:
            gravador.copiar(origem.read)
        metadados = {"tamanho": str(info.st_size), "mtime": _instante_iso(info.st_mtime)}
        return Recebimento(gravador.recebidos, info.st_size, metadados)

    def listar(self, localizador: str) -> list[str]:
        caminho = self._caminho(localizador)
        if not caminho.is_dir():
            raise RecursoNaoEncontrado(f"diretorio_inexistente caminho={caminho}")
        return sorted(os.listdir(caminho))


class TransporteFTP:
    """FTP anônimo em modo passivo e binário, com prazo total por transferência."""

    def __init__(self, timeout: float = 60.0, prazo_total: float | None = PRAZO_TOTAL) -> None:
        self.timeout = timeout
        self.prazo_total = prazo_total

    def _conectar(self, localizador: str) -> tuple[ftplib.FTP, str]:
        partes = urlsplit(localizador)
        cliente = ftplib.FTP(timeout=self.timeout)  # noqa: S321
        cliente.connect(partes.hostname or "", partes.port or 21)
        cliente.login()
        cliente.set_pasv(True)
        cliente.voidcmd("TYPE I")
        return cliente, unquote(partes.path)

    @staticmethod
    def _metadados(cliente: ftplib.FTP, caminho: str) -> tuple[int | None, dict[str, str]]:
        metadados: dict[str, str] = {}
        tamanho: int | None = None
        try:
            tamanho = cliente.size(caminho)
        except ftplib.error_perm as erro:
            if str(erro).startswith("550"):
                raise RecursoNaoEncontrado(
                    f"ftp_inexistente caminho={caminho} resposta={erro}"
                ) from erro
        if tamanho is not None:
            metadados["tamanho"] = str(tamanho)
        with contextlib.suppress(ftplib.error_perm, ftplib.error_reply):
            metadados["mdtm"] = cliente.voidcmd(f"MDTM {caminho}").split(" ", 1)[-1]
        return tamanho, metadados

    @staticmethod
    def _transferir(
        cliente: ftplib.FTP, caminho: str, gravador: _Gravador
    ) -> tuple[int | None, dict[str, str]]:
        """RETR sem QUIT no fim: o fechamento não troca a causa (limite, prazo) por um 426."""
        try:
            tamanho, metadados = TransporteFTP._metadados(cliente, caminho)
            if tamanho is not None and tamanho > gravador.limite:
                raise LimiteExcedido(
                    f"tamanho_maximo_excedido limite={gravador.limite} anunciado={tamanho}"
                )
            cliente.retrbinary(f"RETR {caminho}", gravador, blocksize=_BLOCO)
        finally:
            cliente.close()
        return tamanho, metadados

    def baixar(self, localizador: str, destino: Escrita, limite: int) -> Recebimento:
        gravador = _Gravador(destino, limite, prazo=_prazo(self.prazo_total))
        try:
            cliente, caminho = self._conectar(localizador)
            tamanho, metadados = self._transferir(cliente, caminho, gravador)
        except ErroTransporte:
            raise
        except (OSError, EOFError, ftplib.Error) as erro:
            raise _falha(erro, gravador.recebidos) from erro
        return Recebimento(gravador.recebidos, tamanho, metadados)

    def listar(self, localizador: str) -> list[str]:
        try:
            cliente, caminho = self._conectar(localizador)
            with cliente:
                nomes = cliente.nlst(caminho)
        except ftplib.error_perm as erro:
            if str(erro).startswith("550"):
                raise RecursoNaoEncontrado(f"ftp_diretorio_inexistente erro={erro}") from erro
            raise ErroTransporte(f"ftp_recusou_listagem erro={erro}") from erro
        except (OSError, EOFError, ftplib.Error) as erro:
            raise _falha(erro, 0) from erro
        return sorted(nome.rsplit("/", 1)[-1] for nome in nomes)


class RedirecionamentoSoHTTPS(urllib.request.HTTPRedirectHandler):
    """Segue redirecionamento só para outro endereço https; recusa rebaixamento de canal."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlsplit(newurl).scheme != "https":
            raise ErroTransporte(f"redirecionamento_fora_de_https destino={newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class TransporteHTTPS:
    """HTTPS com timeout; não lista diretórios; a URL final fica nos metadados."""

    def __init__(self, timeout: float = 60.0, prazo_total: float | None = PRAZO_TOTAL) -> None:
        self.timeout = timeout
        self.prazo_total = prazo_total
        self._abridor = urllib.request.build_opener(RedirecionamentoSoHTTPS())

    def _abrir(self, requisicao: urllib.request.Request) -> Any:
        return self._abridor.open(requisicao, timeout=self.timeout)

    def baixar(self, localizador: str, destino: Escrita, limite: int) -> Recebimento:
        if urlsplit(localizador).scheme != "https":
            raise ErroTransporte(f"esquema_nao_https localizador={localizador}")
        gravador = _Gravador(destino, limite, prazo=_prazo(self.prazo_total))
        requisicao = urllib.request.Request(localizador, method="GET")  # noqa: S310
        try:
            with self._abrir(requisicao) as resposta:
                cabecalhos = resposta.headers
                metadados = {c: cabecalhos[c] for c in _CABECALHOS_HTTP if c in cabecalhos}
                metadados["url_final"] = resposta.geturl()
                gravador.copiar(resposta.read)
        except urllib.error.HTTPError as erro:
            if erro.code in _HTTP_AUSENTE:
                raise RecursoNaoEncontrado(f"http_ausente codigo={erro.code}") from erro
            raise _falha(erro, gravador.recebidos) from erro
        except (OSError, EOFError) as erro:
            raise _falha(erro, gravador.recebidos) from erro
        anunciado = metadados.get("Content-Length")
        tamanho = int(anunciado) if anunciado and anunciado.isdigit() else None
        return Recebimento(gravador.recebidos, tamanho, metadados)

    def listar(self, localizador: str) -> list[str]:
        raise ErroTransporte(f"https_nao_lista_diretorio localizador={localizador}")


def transportes_padrao() -> dict[str, Transporte]:
    return {"ftp": TransporteFTP(), "https": TransporteHTTPS(), "file": TransporteArquivo()}
