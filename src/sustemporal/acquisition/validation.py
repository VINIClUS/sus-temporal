"""Validação de conteúdo baixado sem executar nem extrair nada."""

from __future__ import annotations

import re
import stat
import struct
import zipfile
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade, FormatoArquivo, MembroArquivo

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["LimitesZip", "Veredito", "parece_html", "validar_conteudo"]

_AMOSTRA = 4096
_INICIO_HTML = (b"<!doctype html", b"<html", b"<head", b"<body", b"<?xml", b"<!--")
_BOM = b"\xef\xbb\xbf"
# Versões dBASE aceitas: III sem (0x03) e com memo (0x83); outras ficam A_CONFIRMAR.
_VERSOES_DBF = {0x03, 0x83}
_TERMINADOR_DBF = 0x0D
_CABECALHO_DBF_MINIMO = 33
_CAUDA_PDF = 1024
_ASSINATURAS_ZIP = (b"PK\x03\x04", b"PK\x05\x06")
_DRIVE = re.compile(r"^[A-Za-z]:")
_CRIPTOGRAFADO = 0x1
_TIPOS_PERMITIDOS = {0, stat.S_IFREG, stat.S_IFDIR}


@dataclass(frozen=True)
class LimitesZip:
    """Tetos conferidos no diretório central antes de descompactar qualquer membro."""

    descompactado_bytes: int = 8 * 1024**3
    razao: int = 200
    membros: int = 10_000


@dataclass(frozen=True)
class _Amostra:
    caminho: Path
    inicio: bytes
    tamanho: int


@dataclass(frozen=True)
class Veredito:
    integridade: EstadoIntegridade
    membros: tuple[MembroArquivo, ...] = ()
    motivo: str | None = None

    @property
    def em_quarentena(self) -> bool:
        return self.integridade.name.startswith("QUARENTENA")


_OK = Veredito(EstadoIntegridade.OK)


def _inesperado(motivo: str) -> Veredito:
    return Veredito(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, motivo=motivo)


def _truncado(motivo: str) -> Veredito:
    return Veredito(EstadoIntegridade.QUARENTENA_TRUNCADO, motivo=motivo)


def parece_html(inicio: bytes) -> bool:
    """Os primeiros bytes parecem uma página HTML/XML (erro de portal, login, índice)."""
    texto = inicio.removeprefix(_BOM).lstrip().lower()
    return texto.startswith(_INICIO_HTML) or b"<html" in texto[:1024]


def _cabecalho_dbf(inicio: bytes, tamanho: int) -> tuple[int, int, int] | Veredito:
    if len(inicio) < 12:
        return _truncado("cabecalho_dbf_incompleto")
    if inicio[0] not in _VERSOES_DBF:
        return _inesperado(f"versao_dbf_desconhecida byte={inicio[0]:#04x}")
    registros, cabecalho, registro = struct.unpack_from("<IHH", inicio, 4)
    if cabecalho < _CABECALHO_DBF_MINIMO or registro < 1:
        return _inesperado(f"cabecalho_dbf_invalido cabecalho={cabecalho} registro={registro}")
    if tamanho < cabecalho:
        return _truncado(f"cabecalho_dbf_truncado cabecalho={cabecalho} tamanho={tamanho}")
    if cabecalho <= len(inicio) and inicio[cabecalho - 1] != _TERMINADOR_DBF:
        return _inesperado("cabecalho_dbf_sem_terminador")
    return registros, cabecalho, registro


def _validar_dbf(amostra: _Amostra) -> Veredito:
    tamanho = amostra.tamanho
    cabecalho = _cabecalho_dbf(amostra.inicio, tamanho)
    if isinstance(cabecalho, Veredito):
        return cabecalho
    registros, tam_cabecalho, tam_registro = cabecalho
    esperado = tam_cabecalho + registros * tam_registro
    if tamanho < esperado:
        return _truncado(f"dbf_truncado esperado={esperado} tamanho={tamanho}")
    return _OK


def _validar_dbc(amostra: _Amostra) -> Veredito:
    """Cabeçalho DBF + 4 bytes + fluxo DCL (ADR 0002); o fluxo só é conferido na ingestão."""
    tamanho = amostra.tamanho
    cabecalho = _cabecalho_dbf(amostra.inicio, tamanho)
    if isinstance(cabecalho, Veredito):
        return cabecalho
    _, tam_cabecalho, _ = cabecalho
    fluxo = tam_cabecalho + 4
    if tamanho < fluxo + 2:
        return _truncado(f"dbc_sem_fluxo cabecalho={tam_cabecalho} tamanho={tamanho}")
    with amostra.caminho.open("rb") as arquivo:
        arquivo.seek(fluxo)
        literais, dicionario = arquivo.read(2)
    if literais not in {0, 1} or dicionario not in {4, 5, 6}:
        return _inesperado(f"dbc_fluxo_invalido bytes={literais:#04x}{dicionario:02x}")
    return _OK


def _nome_inseguro(nome: str) -> bool:
    partes = nome.split("/")
    return (
        not nome
        or "\\" in nome
        or "\x00" in nome
        or nome.startswith("/")
        or bool(_DRIVE.match(nome))
        or ".." in partes
    )


def _membro(info: zipfile.ZipInfo, vistos: set[str]) -> MembroArquivo:
    tipo = stat.S_IFMT(info.external_attr >> 16)
    seguro = not _nome_inseguro(info.orig_filename) and tipo in _TIPOS_PERMITIDOS
    seguro = seguro and info.filename not in vistos
    vistos.add(info.filename)
    return MembroArquivo(nome=info.orig_filename, tamanho_bytes=info.file_size, seguro=seguro)


def _validar_zip(amostra: _Amostra) -> Veredito:
    if not amostra.inicio.startswith(_ASSINATURAS_ZIP):
        return _inesperado("assinatura_zip_ausente")
    try:
        with zipfile.ZipFile(amostra.caminho) as arquivo:
            infos = arquivo.infolist()
    except zipfile.BadZipFile as erro:
        return _truncado(f"zip_sem_diretorio_central erro={erro}")
    vistos: set[str] = set()
    membros = tuple(_membro(info, vistos) for info in infos)
    if not membros:
        return _inesperado("zip_vazio")
    if not all(m.seguro for m in membros):
        return Veredito(EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO, membros, "membro_inseguro")
    return _conteudo_dos_membros(amostra.caminho, infos, membros)


def _conteudo_dos_membros(
    caminho: Path, infos: list[zipfile.ZipInfo], membros: tuple[MembroArquivo, ...]
) -> Veredito:
    if any(info.flag_bits & _CRIPTOGRAFADO for info in infos):
        return Veredito(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, membros, "zip_cifrado")
    corrompido = _membro_corrompido(caminho)
    if corrompido is not None:
        return Veredito(EstadoIntegridade.QUARENTENA_TRUNCADO, membros, corrompido)
    return Veredito(EstadoIntegridade.OK, membros)


def _membro_corrompido(caminho: Path) -> str | None:
    """Lê cada membro em memória (sem gravar em disco) e confere limites e CRC."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            ruim = arquivo.testzip()
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError) as erro:
        return f"zip_membro_ilegivel erro={erro}"
    return None if ruim is None else f"zip_crc_divergente membro={ruim}"


def _validar_pdf(amostra: _Amostra) -> Veredito:
    if not amostra.inicio.startswith(b"%PDF-"):
        return _inesperado("assinatura_pdf_ausente")
    with amostra.caminho.open("rb") as arquivo:
        arquivo.seek(max(0, amostra.tamanho - _CAUDA_PDF))
        cauda = arquivo.read()
    return _OK if b"%%EOF" in cauda else _truncado("pdf_sem_marcador_final")


_VALIDADORES: dict[FormatoArquivo, Callable[[_Amostra], Veredito]] = {
    FormatoArquivo.DBC: _validar_dbc,
    FormatoArquivo.DBF: _validar_dbf,
    FormatoArquivo.ZIP: _validar_zip,
    FormatoArquivo.PDF: _validar_pdf,
}


def validar_conteudo(
    caminho: Path, formato: FormatoArquivo, *, limites: LimitesZip | None = None
) -> Veredito:
    """Confere assinatura e estrutura mínima do formato esperado; ZIP só é listado.

    Formatos sem assinatura conferível (TXT, CSV, YAML, HTML, OUTRO) ficam NAO_VERIFICADO.
    """
    tamanho = caminho.stat().st_size
    if tamanho == 0:
        return _truncado("arquivo_vazio")
    with caminho.open("rb") as arquivo:
        inicio = arquivo.read(_AMOSTRA)
    if formato is not FormatoArquivo.HTML and parece_html(inicio):
        return _inesperado("html_no_lugar_de_dados")
    validador = _VALIDADORES.get(formato)
    if validador is None:
        return Veredito(EstadoIntegridade.NAO_VERIFICADO)
    return validador(_Amostra(caminho, inicio, tamanho))
