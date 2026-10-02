"""Codificador PKWARE DCL "só literais" para montar DBC sintéticos em testes.

Segue o formato descrito nos comentários de ``contrib/blast/blast.c`` (Mark Adler, licença
zlib). Não comprime: emite apenas literais sem código e o código de fim. Não usar em produção.
"""

from __future__ import annotations

import struct

LENLEN = (2, 35, 36, 53, 38, 23)
BASE_COMPRIMENTO = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
EXTRA_COMPRIMENTO = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)
COMPRIMENTO_FIM = 519
SIMBOLO_FIM = 15
DICIONARIOS = (4, 5, 6)


def _comprimentos(rep: tuple[int, ...]) -> list[int]:
    comprimentos: list[int] = []
    for valor in rep:
        comprimentos.extend([valor & 0x0F] * ((valor >> 4) + 1))
    return comprimentos


def _codigos_canonicos(rep: tuple[int, ...]) -> dict[int, tuple[int, int]]:
    """Símbolo -> (código, nº de bits), na construção canônica que o ``decode`` do blast lê."""
    comprimentos = _comprimentos(rep)
    codigos: dict[int, tuple[int, int]] = {}
    primeiro = 0
    for bits in range(1, max(comprimentos) + 1):
        simbolos = [s for s, n in enumerate(comprimentos) if n == bits]
        for deslocamento, simbolo in enumerate(simbolos):
            codigos[simbolo] = (primeiro + deslocamento, bits)
        primeiro = (primeiro + len(simbolos)) << 1
    return codigos


class _EscritorBits:
    """Acumula bits LSB-first, como ``bits()`` do blast os consome."""

    def __init__(self) -> None:
        self._saida = bytearray()
        self._buffer = 0
        self._contagem = 0

    def escrever(self, valor: int, n: int) -> None:
        self._buffer |= (valor & ((1 << n) - 1)) << self._contagem
        self._contagem += n
        while self._contagem >= 8:
            self._saida.append(self._buffer & 0xFF)
            self._buffer >>= 8
            self._contagem -= 8

    def escrever_huffman(self, codigo: int, n: int) -> None:
        for posicao in range(n - 1, -1, -1):
            self.escrever(((codigo >> posicao) & 1) ^ 1, 1)

    def finalizar(self) -> bytes:
        if self._contagem:
            self._saida.append(self._buffer & 0xFF)
        return bytes(self._saida)


def comprimir_dcl_literais(dados: bytes, dicionario: int = 6) -> bytes:
    """Fluxo DCL com literais sem código seguidos do código de fim (comprimento 519)."""
    if dicionario not in DICIONARIOS:
        raise ValueError(f"dicionario_invalido dicionario={dicionario}")
    escritor = _EscritorBits()
    escritor.escrever(0, 8)
    escritor.escrever(dicionario, 8)
    for byte in dados:
        escritor.escrever(0, 1)
        escritor.escrever(byte, 8)
    codigo, bits = _codigos_canonicos(LENLEN)[SIMBOLO_FIM]
    extra = COMPRIMENTO_FIM - BASE_COMPRIMENTO[SIMBOLO_FIM]
    escritor.escrever(1, 1)
    escritor.escrever_huffman(codigo, bits)
    escritor.escrever(extra, EXTRA_COMPRIMENTO[SIMBOLO_FIM])
    return escritor.finalizar()


def dbf_para_dbc(dbf: bytes, dicionario: int = 6) -> bytes:
    """DBC = cabeçalho DBF [0, H) + 4 bytes de CRC zerados + fluxo DCL do restante."""
    (tam_cabecalho,) = struct.unpack_from("<H", dbf, 8)
    return dbf[:tam_cabecalho] + bytes(4) + comprimir_dcl_literais(dbf[tam_cabecalho:], dicionario)
