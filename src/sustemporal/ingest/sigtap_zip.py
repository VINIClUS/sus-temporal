"""Leitura segura do zip TabelaUnificada do SIGTAP e do leiaute embutido em cada competência."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import zipfile
    from collections.abc import Sequence

    from sustemporal.contracts import CampoLeiaute, LayoutSpec

__all__ = [
    "CATALOGO_LEIAUTES",
    "LIMITE_MEMBRO_PADRAO",
    "ColunaZip",
    "carregar_leiautes_sigtap",
    "conferir_leiaute",
    "fatiar",
    "ler_leiaute_zip",
    "ler_membro",
    "tabela_do_leiaute",
]

CATALOGO_LEIAUTES = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "sigtap.yaml"
LIMITE_MEMBRO_PADRAO = 256 * 1024 * 1024


@dataclass(frozen=True)
class ColunaZip:
    nome: str
    tamanho: int
    inicio: int
    fim: int
    tipo: str


def carregar_leiautes_sigtap(caminho: Path = CATALOGO_LEIAUTES) -> dict[str, LayoutSpec]:
    """Leiautes do catálogo por tabela."""
    raise NotImplementedError


def tabela_do_leiaute(layout: LayoutSpec) -> str:
    """Tabela identificada pelo `layout_id` `sigtap.<tabela>`."""
    raise NotImplementedError


def ler_membro(arquivo: zipfile.ZipFile, nome: str, limite: int) -> bytes:
    """Bytes de um membro do zip, com nome validado e tamanho descomprimido limitado."""
    raise NotImplementedError


def ler_leiaute_zip(dados: bytes) -> tuple[ColunaZip, ...]:
    """Colunas do `*_layout.txt` embutido, conferidas quanto a posições contíguas."""
    raise NotImplementedError


def conferir_leiaute(
    colunas: Sequence[ColunaZip], layout: LayoutSpec
) -> tuple[tuple[ColunaZip, CampoLeiaute], ...]:
    """Casa o leiaute do zip com o do catálogo; divergência vai para quarentena."""
    raise NotImplementedError


def fatiar(dados: bytes, colunas: Sequence[ColunaZip]) -> tuple[list[str], ...]:
    """Recorta os registros de largura fixa em colunas de texto latin-1."""
    raise NotImplementedError
