"""Leiaute físico de um Parquet contra o esquema canônico (T14).

O hash lógico projeta as colunas do esquema que o arquivo tem. Sem conferir antes o leiaute
completo, a coluna que falta (inclusive a de identidade que o hash ignora), a que sobra, a de outro
tipo ou fora de ordem some da comparação e o hash sai igual com um arquivo incompatível. O leiaute
do esquema é o de `catalog/schemas`: os nomes na ordem do esquema (todo escritor os grava nessa
ordem) e o tipo físico de cada tipo canônico.
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING

from sustemporal.contracts.records import TipoCanonico

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import duckdb

    from sustemporal.contracts.records import EsquemaCanonico

__all__ = ["Leiaute", "colunas_que_diferem", "colunas_que_diferem_entre", "leiaute_do_arquivo"]

Leiaute = tuple[tuple[str, str], ...]

_FISICO = {
    TipoCanonico.TEXTO.value: "VARCHAR",
    TipoCanonico.INTEIRO.value: "BIGINT",
    TipoCanonico.BOOLEANO.value: "BOOLEAN",
    TipoCanonico.DATA.value: "DATE",
}


def leiaute_do_arquivo(con: duckdb.DuckDBPyConnection, caminho: Path) -> Leiaute:
    """`(nome, tipo físico)` de cada coluna do Parquet, na ordem do arquivo."""
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": str(caminho)}
    ).fetchall()
    return tuple((str(linha[0]), str(linha[1])) for linha in descricao)


def _compativel(fisico: str, canonico: str) -> bool:
    if canonico == TipoCanonico.DECIMAL.value:
        return fisico.startswith("DECIMAL(")
    return fisico == _FISICO[canonico]


def _diferencas(esperado: Leiaute, obtido: Leiaute, igual: Callable[[str, str], bool]) -> list[str]:
    tipos = dict(obtido)
    nomes_esperados = [nome for nome, _ in esperado]
    nomes_obtidos = [nome for nome, _ in obtido]
    faltando = [nome for nome in nomes_esperados if nome not in tipos]
    a_mais = [nome for nome in nomes_obtidos if nome not in set(nomes_esperados)]
    de_outro_tipo = [n for n, tipo in esperado if n in tipos and not igual(tipos[n], tipo)]
    fora_de_posicao: list[str] = []
    if not (faltando or a_mais) and nomes_obtidos != nomes_esperados:
        pares = zip(nomes_obtidos, nomes_esperados, strict=True)
        fora_de_posicao = [obtida for obtida, esperada in pares if obtida != esperada]
    return list(dict.fromkeys([*faltando, *a_mais, *de_outro_tipo, *fora_de_posicao]))


def colunas_que_diferem(esquema: EsquemaCanonico, leiaute: Leiaute) -> list[str]:
    """Colunas em que o leiaute não é o do esquema, sem repetir.

    Saem primeiro as que faltam, depois as que sobram e as de outro tipo; se nenhuma falta nem
    sobra e a ordem difere, saem também as colunas fora de posição. `DECIMAL` vale com qualquer
    precisão e escala.
    """
    esperado = tuple((coluna.nome, coluna.tipo.value) for coluna in esquema.colunas)
    return _diferencas(esperado, leiaute, _compativel)


def colunas_que_diferem_entre(esperado: Leiaute, obtido: Leiaute) -> list[str]:
    """Colunas em que dois leiautes físicos diferem (nome, tipo ou posição); vazio se são iguais."""
    return _diferencas(esperado, obtido, operator.eq)
