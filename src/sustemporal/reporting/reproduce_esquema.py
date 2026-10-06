"""Leiaute físico de um Parquet contra o esquema canônico (T14).

O hash lógico projeta as colunas do esquema que o arquivo tem. Sem conferir antes o leiaute
completo, a coluna que falta (inclusive a de identidade que o hash ignora), a que sobra, a de outro
tipo ou fora de ordem some da comparação e o hash sai igual com um arquivo incompatível. O leiaute
do esquema é o de `catalog/schemas`: os nomes na ordem do esquema (todo escritor os grava nessa
ordem) e o tipo físico de cada tipo canônico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb

    from sustemporal.contracts.records import EsquemaCanonico

__all__ = ["Leiaute", "colunas_que_diferem", "colunas_que_diferem_entre", "leiaute_do_arquivo"]

Leiaute = tuple[tuple[str, str], ...]


def leiaute_do_arquivo(con: duckdb.DuckDBPyConnection, caminho: Path) -> Leiaute:
    """`(nome, tipo físico)` de cada coluna do Parquet, na ordem do arquivo."""
    raise NotImplementedError


def colunas_que_diferem(esquema: EsquemaCanonico, leiaute: Leiaute) -> list[str]:
    """Colunas em que o leiaute não é o do esquema, sem repetir: ausentes, a mais, de outro tipo
    e, se só a ordem difere, as que estão fora de posição."""
    raise NotImplementedError


def colunas_que_diferem_entre(esperado: Leiaute, obtido: Leiaute) -> list[str]:
    """Colunas em que dois leiautes físicos diferem (nome, tipo ou posição); vazio se são iguais."""
    raise NotImplementedError
