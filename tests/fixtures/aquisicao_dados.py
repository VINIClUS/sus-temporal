"""Conteúdos, transportes e servidor FTP sintéticos para os testes de aquisição (SINTETICO)."""

from __future__ import annotations

import contextlib
import io
import stat
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from sustemporal.acquisition.transport import Recebimento
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

HTML_DE_ERRO = b"\n  <!DOCTYPE html>\n<html><head><title>Erro</title></head><body>404</body></html>"
INICIO = datetime(2026, 9, 1, 12, tzinfo=UTC)


def dbf_sintetico(valor: str = "A", *, truncar_bytes: int = 0) -> bytes:
    campos = [CampoDbf("PA_CMP", "C", 6), CampoDbf("PA_X", "C", 1)]
    return escrever_dbf(campos, [("201801", valor)], truncar_bytes=truncar_bytes)


def dbc_sintetico(valor: str = "A") -> bytes:
    return dbf_para_dbc(dbf_sintetico(valor))


def zip_sintetico(membros: dict[str, bytes], *, links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        for nome, conteudo in membros.items():
            arquivo.writestr(nome, conteudo)
        for nome, alvo in (links or {}).items():
            info = zipfile.ZipInfo(nome)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            arquivo.writestr(info, alvo)
    return buffer.getvalue()


@dataclass
class Relogio:
    """Relógio injetado: avança um minuto por leitura."""

    atual: datetime = INICIO
    leituras: list[datetime] = field(default_factory=list)

    def __call__(self) -> datetime:
        self.leituras.append(self.atual)
        self.atual += timedelta(minutes=1)
        return self.leituras[-1]


@dataclass
class TransporteFalso:
    """Fronteira de rede simulada: grava `conteudo` e então levanta `erro`, se houver."""

    conteudo: bytes = b""
    erro: BaseException | None = None
    anunciado: int | None = None
    metadados: dict[str, str] = field(default_factory=dict)
    nomes: list[str] = field(default_factory=list)
    chamadas: int = 0

    def baixar(self, localizador: str, destino: BinaryIO, limite: int) -> Recebimento:
        self.chamadas += 1
        destino.write(self.conteudo)
        if self.erro is not None:
            raise self.erro
        return Recebimento(len(self.conteudo), self.anunciado, dict(self.metadados))

    def listar(self, localizador: str) -> list[str]:
        self.chamadas += 1
        if self.erro is not None:
            raise self.erro
        return list(self.nomes)


@contextlib.contextmanager
def servidor_ftp(raiz: Path) -> Iterator[int]:
    """Servidor FTP anônimo, só leitura, em loopback; devolve a porta."""
    autorizador = DummyAuthorizer()
    autorizador.add_anonymous(str(raiz))
    manipulador = type("Manipulador", (FTPHandler,), {"authorizer": autorizador})
    servidor = FTPServer(("127.0.0.1", 0), manipulador)
    porta = servidor.socket.getsockname()[1]
    linha = threading.Thread(
        target=servidor.serve_forever, kwargs={"timeout": 0.05, "blocking": True}, daemon=True
    )
    linha.start()
    try:
        yield porta
    finally:
        servidor.close_all()
        linha.join(timeout=5)
