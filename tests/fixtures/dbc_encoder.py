"""Codificador PKWARE DCL "só literais" para montar DBC sintéticos em testes.

Segue o formato descrito nos comentários de ``contrib/blast/blast.c`` (Mark Adler, licença
zlib). Não comprime: emite apenas literais sem código e o código de fim. Não usar em produção.
"""

from __future__ import annotations


def comprimir_dcl_literais(dados: bytes, dicionario: int = 6) -> bytes:
    """Fluxo DCL com literais sem código seguidos do código de fim (comprimento 519)."""
    raise NotImplementedError


def dbf_para_dbc(dbf: bytes, dicionario: int = 6) -> bytes:
    """DBC = cabeçalho DBF [0, H) + 4 bytes de CRC zerados + fluxo DCL do restante."""
    raise NotImplementedError
