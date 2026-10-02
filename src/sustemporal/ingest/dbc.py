"""Descompressão DBC (datasus-dbc) e verificação independente de fidelidade (ADR 0002)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.ingest.dbf import TAMANHO_BLOCO_PADRAO

if TYPE_CHECKING:
    from sustemporal.contracts import VerificacaoFidelidade
    from sustemporal.ingest.dbf import LeituraDbf


@dataclass(frozen=True)
class MetadadosDbc:
    tam_cabecalho: int
    bytes_pos_cabecalho_hex: str
    flag_literais: int
    dicionario: int
    bibliotecas: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LeituraDbc:
    leitura: LeituraDbf
    metadados: MetadadosDbc


@dataclass(frozen=True)
class RelatorioFidelidade:
    modo: VerificacaoFidelidade
    verificado: bool
    registros_comparados: int
    divergencias: tuple[str, ...]
    bibliotecas: tuple[tuple[str, str], ...]

    @property
    def fiel(self) -> bool:
        return self.verificado and not self.divergencias


def descomprimir_dbc(dados: bytes) -> tuple[bytes, MetadadosDbc]:
    """DBF descomprimido pelo datasus-dbc, sem reescrever bytes do cabeçalho."""
    raise NotImplementedError


def ler_dbc(dados: bytes, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbc:
    """Descomprime e lê o DBF com as checagens físicas do parser próprio."""
    raise NotImplementedError


def verificar_fidelidade(
    dbc: bytes,
    leitura: LeituraDbf,
    modo: VerificacaoFidelidade = "COMPLETA",
    *,
    amostra: int = 1_000,
) -> RelatorioFidelidade:
    """Compara datasus-dbc × dbc-to-dbf (bytes) e parser próprio × dbfread (registros)."""
    raise NotImplementedError
