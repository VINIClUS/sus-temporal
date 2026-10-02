"""Escritor DBF dBASE III determinístico, só para testes (SINTETICO)."""

from __future__ import annotations

import datetime
import re
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

TIPOS_SUPORTADOS = frozenset("CNDL")
_LARGURA_FIXA = {"D": 8, "L": 1}
_TERMINADOR = b"\x0d"
_EOF = b"\x1a"
_NOME_CAMPO = re.compile(r"[A-Z0-9_]{1,10}")


@dataclass(frozen=True)
class CampoDbf:
    nome: str
    tipo: str
    largura: int
    decimais: int = 0


def _validar_campo(campo: CampoDbf) -> None:
    if not _NOME_CAMPO.fullmatch(campo.nome):
        raise ValueError(f"campo_nome_invalido nome={campo.nome}")
    if campo.tipo not in TIPOS_SUPORTADOS:
        raise ValueError(f"campo_tipo_invalido nome={campo.nome} tipo={campo.tipo}")
    fixa = _LARGURA_FIXA.get(campo.tipo)
    if not 1 <= campo.largura <= 254 or (fixa is not None and campo.largura != fixa):
        raise ValueError(f"campo_largura_invalida nome={campo.nome} largura={campo.largura}")
    limite = campo.largura if campo.tipo == "N" else 1
    if not 0 <= campo.decimais < limite:
        raise ValueError(f"campo_decimais_invalido nome={campo.nome} decimais={campo.decimais}")


def _validar_arquivo(data: tuple[int, int, int], byte_driver: int, truncar_bytes: int) -> None:
    ano, mes, dia = data
    try:
        datetime.date(ano, mes, dia)
    except ValueError as erro:
        raise ValueError(f"data_invalida data={data}") from erro
    if not 1900 <= ano <= 2155:
        raise ValueError(f"data_fora_do_intervalo data={data}")
    if not 0 <= byte_driver <= 255:
        raise ValueError(f"byte_driver_invalido byte_driver={byte_driver}")
    if truncar_bytes < 0:
        raise ValueError(f"truncar_bytes_negativo truncar_bytes={truncar_bytes}")


def _descritor(campo: CampoDbf) -> bytes:
    nome = campo.nome.encode("ascii").ljust(11, b"\x00")
    tipo = campo.tipo.encode("ascii")
    return nome + tipo + bytes(4) + bytes([campo.largura, campo.decimais]) + bytes(14)


def _valor(campo: CampoDbf, valor: str | bytes) -> bytes:
    bruto = valor if isinstance(valor, bytes) else valor.encode("latin-1", errors="strict")
    if len(bruto) > campo.largura:
        raise ValueError(f"valor_excede_largura nome={campo.nome} largura={campo.largura}")
    if campo.tipo == "N":
        return bruto.rjust(campo.largura, b" ")
    return bruto.ljust(campo.largura, b" ")


def _codificar_valor(campo: CampoDbf, valor: str | bytes) -> bytes:
    try:
        return _valor(campo, valor)
    except UnicodeEncodeError as erro:
        raise ValueError(f"valor_fora_de_latin1 nome={campo.nome}") from erro


def _registro(campos: Sequence[CampoDbf], valores: Sequence[str | bytes], deletado: bool) -> bytes:
    if len(valores) != len(campos):
        raise ValueError(f"registro_aridade_invalida esperado={len(campos)} obtido={len(valores)}")
    flag = b"*" if deletado else b" "
    return flag + b"".join(_codificar_valor(c, v) for c, v in zip(campos, valores, strict=True))


def _cabecalho(
    campos: Sequence[CampoDbf], n_registros: int, byte_driver: int, data: tuple[int, int, int]
) -> bytes:
    ano, mes, dia = data
    tam_cabecalho = 32 + 32 * len(campos) + 1
    tam_registro = 1 + sum(c.largura for c in campos)
    inicio = struct.pack(
        "<B3BIHH", 0x03, ano - 1900, mes, dia, n_registros, tam_cabecalho, tam_registro
    )
    fixo = inicio + bytes(17) + bytes([byte_driver]) + bytes(2)
    return fixo + b"".join(_descritor(c) for c in campos) + _TERMINADOR


def escrever_dbf(
    campos: Sequence[CampoDbf],
    registros: Sequence[Sequence[str | bytes]],
    *,
    deletados: Collection[int] = (),
    byte_driver: int = 0x00,
    data: tuple[int, int, int] = (2026, 1, 1),
    com_eof: bool = True,
    truncar_bytes: int = 0,
) -> bytes:
    """Monta um DBF dBASE III em memória; valores em latin-1, sem conversão."""
    _validar_arquivo(data, byte_driver, truncar_bytes)
    for campo in campos:
        _validar_campo(campo)
    fora = [i for i in deletados if not 0 <= i < len(registros)]
    if fora:
        raise ValueError(f"deletado_fora_do_intervalo indices={sorted(fora)}")
    corpo = b"".join(_registro(campos, r, i in deletados) for i, r in enumerate(registros))
    dbf = _cabecalho(campos, len(registros), byte_driver, data) + corpo
    if com_eof:
        dbf += _EOF
    if truncar_bytes > len(dbf):
        raise ValueError(f"truncar_bytes_excede_arquivo truncar_bytes={truncar_bytes}")
    return dbf[: len(dbf) - truncar_bytes]
