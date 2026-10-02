"""Validação de conteúdo baixado sem executar nem extrair nada."""

from __future__ import annotations

import re
import stat
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.acquisition.descompressao import DesfechoDescompressao, descomprimir_limitado
from sustemporal.contracts.artifacts import EstadoIntegridade, FormatoArquivo, MembroArquivo

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["LIMITE_DBF_PADRAO", "LimitesZip", "Veredito", "parece_html", "validar_conteudo"]

_AMOSTRA = 4096
_INICIO_HTML = (b"<!doctype html", b"<html", b"<head", b"<body", b"<?xml", b"<!--")
_BOM = b"\xef\xbb\xbf"
# Versões dBASE aceitas: III sem (0x03) e com memo (0x83); outras ficam A_CONFIRMAR.
_VERSOES_DBF = {0x03, 0x83}
_TERMINADOR_DBF = 0x0D
_FIM_DBF = b"\x1a"
_CABECALHO_DBF_MINIMO = 33
# dBASE III: 32 bytes fixos + 32 por campo + terminador 0x0D (H = 33 + 32·n).
_DESCRITOR_DBF = 32
_CAUDA_PDF = 1024
# Teto do DBF descomprimido de um DBC (proposta; A_CONFIRMAR com os maiores PA de SP).
LIMITE_DBF_PADRAO = 8 * 1024**3
_BRANCOS_PDF = b" \t\r\n\x00\x0c"
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
    limites: LimitesZip
    limite_dbf: int


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


def _tem_assinatura(inicio: bytes) -> bool:
    return inicio.startswith((b"%PDF-", *_ASSINATURAS_ZIP)) or (
        bool(inicio) and inicio[0] in _VERSOES_DBF
    )


def parece_html(inicio: bytes) -> bool:
    """Marcação no início (após BOM e brancos), ou `<html` no começo sem assinatura conhecida.

    Um PDF/ZIP/DBF/DBC válido que cite `<html` (comentário, nome de membro) não é página.
    """
    texto = inicio.removeprefix(_BOM).lstrip().lower()
    if texto.startswith(_INICIO_HTML):
        return True
    return not _tem_assinatura(inicio) and b"<html" in texto[:1024]


def _byte_do_terminador(amostra: _Amostra, cabecalho: int) -> int:
    if cabecalho <= len(amostra.inicio):
        return amostra.inicio[cabecalho - 1]
    with amostra.caminho.open("rb") as arquivo:
        arquivo.seek(cabecalho - 1)
        return arquivo.read(1)[0]


def _cabecalho_dbf(amostra: _Amostra) -> tuple[int, int, int] | Veredito:
    """Cabeçalho dBASE (no DBF ou nos primeiros bytes do DBC), terminador conferido no arquivo."""
    inicio, tamanho = amostra.inicio, amostra.tamanho
    if len(inicio) < 12:
        return _truncado("cabecalho_dbf_incompleto")
    if inicio[0] not in _VERSOES_DBF:
        return _inesperado(f"versao_dbf_desconhecida byte={inicio[0]:#04x}")
    registros, cabecalho, registro = struct.unpack_from("<IHH", inicio, 4)
    desalinhado = (cabecalho - _CABECALHO_DBF_MINIMO) % _DESCRITOR_DBF != 0
    if cabecalho < _CABECALHO_DBF_MINIMO or desalinhado or registro < 1:
        return _inesperado(f"cabecalho_dbf_invalido cabecalho={cabecalho} registro={registro}")
    if tamanho < cabecalho:
        return _truncado(f"cabecalho_dbf_truncado cabecalho={cabecalho} tamanho={tamanho}")
    if _byte_do_terminador(amostra, cabecalho) != _TERMINADOR_DBF:
        return _inesperado("cabecalho_dbf_sem_terminador")
    return registros, cabecalho, registro


def _validar_dbf(amostra: _Amostra) -> Veredito:
    cabecalho = _cabecalho_dbf(amostra)
    if isinstance(cabecalho, Veredito):
        return cabecalho
    return _tamanho_dbf_confere(amostra.caminho, cabecalho)


def _tamanho_dbf_confere(dbf: Path, cabecalho: tuple[int, int, int]) -> Veredito:
    """Exatamente H + n×R bytes, ou um byte a mais se for o 0x1A de fim de arquivo."""
    registros, tam_cabecalho, tam_registro = cabecalho
    esperado = tam_cabecalho + registros * tam_registro
    tamanho = dbf.stat().st_size
    if tamanho < esperado:
        return _truncado(f"dbf_truncado esperado={esperado} tamanho={tamanho}")
    if tamanho > esperado + 1:
        return _inesperado(f"dbf_bytes_depois_dos_registros esperado={esperado} tamanho={tamanho}")
    if tamanho == esperado + 1:
        with dbf.open("rb") as arquivo:
            arquivo.seek(esperado)
            final = arquivo.read(1)
        if final != _FIM_DBF:
            return _inesperado(f"dbf_byte_final_invalido byte={final.hex()}")
    return _OK


def _descomprimir_dbc(caminho: Path, cabecalho: tuple[int, int, int], teto: int) -> Veredito:
    """Descomprime arquivo→arquivo num processo com teto de gravação e apaga o DBF gerado."""
    destino = caminho.with_name(f"{caminho.name}.dbf_validacao")
    try:
        resultado = descomprimir_limitado(caminho, destino, teto)
        if resultado.desfecho is DesfechoDescompressao.OK:
            return _tamanho_dbf_confere(destino, cabecalho)
        if resultado.desfecho is DesfechoDescompressao.EXCEDEU_LIMITE:
            return _inesperado(f"dbc_descomprimido_excede teto={teto}")
        if resultado.desfecho is DesfechoDescompressao.TRUNCADO:
            return _truncado(f"dbc_fluxo_truncado erro={resultado.mensagem}")
        return _inesperado(f"dbc_fluxo_invalido erro={resultado.mensagem}")
    finally:
        destino.unlink(missing_ok=True)


def _validar_dbc(amostra: _Amostra) -> Veredito:
    """Cabeçalho DBF + 4 bytes + fluxo DCL (ADR 0002), descomprimido inteiro e conferido."""
    tamanho = amostra.tamanho
    cabecalho = _cabecalho_dbf(amostra)
    if isinstance(cabecalho, Veredito):
        return cabecalho
    fluxo = cabecalho[1] + 4
    if tamanho < fluxo + 2:
        return _truncado(f"dbc_sem_fluxo cabecalho={cabecalho[1]} tamanho={tamanho}")
    with amostra.caminho.open("rb") as arquivo:
        arquivo.seek(fluxo)
        literais, dicionario = arquivo.read(2)
    if literais not in {0, 1} or dicionario not in {4, 5, 6}:
        return _inesperado(f"dbc_fluxo_invalido bytes={literais:#04x}{dicionario:02x}")
    registros, tam_cabecalho, tam_registro = cabecalho
    declarado = tam_cabecalho + registros * tam_registro + 1
    if declarado > amostra.limite_dbf:
        return _inesperado(
            f"dbc_declarado_excede declarado={declarado} limite={amostra.limite_dbf}"
        )
    return _descomprimir_dbc(amostra.caminho, cabecalho, declarado)


def _nome_inseguro(nome: str) -> bool:
    """Absoluto, unidade, barra invertida, NUL, `..`, `.` ou componente vazio (`a//b`).

    Só o diretório admite uma barra final; assim nomes iguais após normalizar não coexistem.
    """
    partes = nome.removesuffix("/").split("/")
    return (
        not nome
        or "\\" in nome
        or "\x00" in nome
        or nome.startswith("/")
        or bool(_DRIVE.match(nome))
        or any(parte in {"", ".", ".."} for parte in partes)
    )


def _nome_canonico(nome: str) -> str:
    return unicodedata.normalize("NFC", nome).casefold()


def _membro(info: zipfile.ZipInfo, vistos: set[str]) -> MembroArquivo:
    tipo = stat.S_IFMT(info.external_attr >> 16)
    canonico = _nome_canonico(info.filename)
    seguro = not _nome_inseguro(info.orig_filename) and tipo in _TIPOS_PERMITIDOS
    seguro = seguro and canonico not in vistos
    vistos.add(canonico)
    return MembroArquivo(nome=info.orig_filename, tamanho_bytes=info.file_size, seguro=seguro)


def _diretorios_implicitos(infos: list[zipfile.ZipInfo]) -> set[str]:
    diretorios: set[str] = set()
    for info in infos:
        partes = _nome_canonico(info.filename).removesuffix("/").split("/")
        fim = len(partes) if info.filename.endswith("/") else len(partes) - 1
        diretorios.update("/".join(partes[:i]) for i in range(1, fim + 1))
    return diretorios


def _marcar_conflitos(
    infos: list[zipfile.ZipInfo], membros: tuple[MembroArquivo, ...]
) -> tuple[MembroArquivo, ...]:
    """Arquivo cujo nome canônico também é diretório (explícito ou prefixo) fica inseguro."""
    diretorios = _diretorios_implicitos(infos)
    return tuple(
        membro.model_copy(update={"seguro": False})
        if not info.filename.endswith("/") and _nome_canonico(info.filename) in diretorios
        else membro
        for info, membro in zip(infos, membros, strict=True)
    )


def _listar_zip(caminho: Path) -> list[zipfile.ZipInfo] | Veredito:
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            return arquivo.infolist()
    except zipfile.BadZipFile as erro:
        return _truncado(f"zip_sem_diretorio_central erro={erro}")
    except Exception as erro:
        return _inesperado(f"zip_ilegivel erro={type(erro).__name__}")


def _excede_limites(infos: list[zipfile.ZipInfo], limites: LimitesZip) -> str | None:
    total = sum(info.file_size for info in infos)
    compactado = sum(info.compress_size for info in infos)
    if len(infos) > limites.membros:
        return f"zip_membros_excede membros={len(infos)} limite={limites.membros}"
    if total > limites.descompactado_bytes:
        return f"zip_descompactado_excede total={total} limite={limites.descompactado_bytes}"
    if total > limites.razao * max(compactado, 1):
        return f"zip_razao_excede total={total} compactado={compactado} limite={limites.razao}"
    return None


def _validar_zip(amostra: _Amostra) -> Veredito:
    if not amostra.inicio.startswith(_ASSINATURAS_ZIP):
        return _inesperado("assinatura_zip_ausente")
    infos = _listar_zip(amostra.caminho)
    if isinstance(infos, Veredito):
        return infos
    vistos: set[str] = set()
    membros = _marcar_conflitos(infos, tuple(_membro(info, vistos) for info in infos))
    if not membros:
        return _inesperado("zip_vazio")
    if not all(m.seguro for m in membros):
        return Veredito(EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO, membros, "membro_inseguro")
    excesso = _excede_limites(infos, amostra.limites)
    if excesso is not None:
        return Veredito(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, membros, excesso)
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
    """Lê cada membro em memória (sem gravar em disco) e confere limites e CRC.

    Só roda depois de `_excede_limites`, então o volume descompactado é limitado.
    """
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            ruim = arquivo.testzip()
    except Exception as erro:
        return f"zip_membro_ilegivel erro={type(erro).__name__}"
    return None if ruim is None else f"zip_crc_divergente membro={ruim}"


def _validar_pdf(amostra: _Amostra) -> Veredito:
    if not amostra.inicio.startswith(b"%PDF-"):
        return _inesperado("assinatura_pdf_ausente")
    with amostra.caminho.open("rb") as arquivo:
        arquivo.seek(max(0, amostra.tamanho - _CAUDA_PDF))
        cauda = arquivo.read()
    if cauda.rstrip(_BRANCOS_PDF).endswith(b"%%EOF"):
        return _OK
    return _truncado("pdf_sem_marcador_final")


_VALIDADORES: dict[FormatoArquivo, Callable[[_Amostra], Veredito]] = {
    FormatoArquivo.DBC: _validar_dbc,
    FormatoArquivo.DBF: _validar_dbf,
    FormatoArquivo.ZIP: _validar_zip,
    FormatoArquivo.PDF: _validar_pdf,
}


def validar_conteudo(
    caminho: Path,
    formato: FormatoArquivo,
    *,
    limites: LimitesZip | None = None,
    limite_dbf_bytes: int | None = None,
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
    teto_dbf = LIMITE_DBF_PADRAO if limite_dbf_bytes is None else limite_dbf_bytes
    amostra = _Amostra(caminho, inicio, tamanho, limites or LimitesZip(), teto_dbf)
    return validador(amostra)
