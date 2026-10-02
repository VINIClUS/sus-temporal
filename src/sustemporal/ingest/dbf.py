"""Parser DBF dBASE III estrito e vetorizado (ADR 0002)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from pathlib import Path

    import pyarrow as pa

    from sustemporal.contracts import EstadoIntegridade, LayoutSpec

COLUNA_INDICE = "_indice_fisico"
COLUNA_DELETADO = "_deletado"
TAMANHO_BLOCO_PADRAO = 100_000


class QuarentenaLeitura(FalhaOperacionalErro):
    """Arquivo que não pode ser lido com segurança; nunca vira conjunto vazio."""

    def __init__(self, estado: EstadoIntegridade, motivo: str) -> None:
        super().__init__(f"quarentena estado={estado} motivo={motivo}")
        self.estado = estado
        self.motivo = motivo


@dataclass(frozen=True)
class DescritorCampo:
    nome: str
    tipo: str
    largura: int
    decimais: int
    inicio: int


@dataclass(frozen=True)
class CabecalhoDbf:
    versao: int
    data_atualizacao: bytes
    n_registros: int
    tam_cabecalho: int
    tam_registro: int
    byte_driver: int
    campos: tuple[DescritorCampo, ...]


@dataclass(frozen=True)
class LeituraDbf:
    cabecalho: CabecalhoDbf
    tabela: pa.Table
    n_deletados: int
    tem_eof: bool
    tamanho_bytes: int


def ler_cabecalho(dados: bytes) -> CabecalhoDbf:
    """Lê cabeçalho e descritores; recusa estrutura incoerente com quarentena."""
    raise NotImplementedError


def ler_dbf(dados: bytes, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbf:
    """Lê todos os registros, inclusive deletados, como texto bruto latin-1."""
    raise NotImplementedError


def ler_dbf_arquivo(caminho: Path, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbf:
    """Como `ler_dbf`, mapeando o arquivo em memória (memmap) e lendo em blocos."""
    raise NotImplementedError


def conferir_leiaute(cabecalho: CabecalhoDbf, layout: LayoutSpec) -> None:
    """Descritores devem coincidir com o leiaute (nome, tipo, largura, decimais, ordem)."""
    raise NotImplementedError
