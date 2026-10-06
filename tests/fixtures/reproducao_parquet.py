"""Parquet de `agregados_registro.v1` SINTETICO para os testes de comparação da reprodução (T14).

O hash lógico declarado vem da referência em Python puro (`hash_logico_linhas`), independente do
caminho de produção (DuckDB) que o comparador usa. Os bytes mudam com a compressão e a ordem das
linhas sem mudar o conteúdo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.hashing import hash_logico_linhas

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

SCHEMA = "agregados_registro.v1"
COLUNAS = (
    "run_id",
    "row_id",
    "violacoes",
    "conformes",
    "inconclusivas",
    "nao_aplicaveis",
    "resultado",
)
ARTEFATO = "art_" + "a" * 64


def linha(run_id: str, row_id: str, resultado: str = "SEM_VIOLACAO_VERIFICADA") -> dict[str, str]:
    alerta = resultado == "ALERTA"
    return {
        "run_id": run_id,
        "row_id": row_id,
        "violacoes": "R1" if alerta else "",
        "conformes": "" if alerta else "R1",
        "inconclusivas": "",
        "nao_aplicaveis": "",
        "resultado": resultado,
    }


def gravar(
    linhas: Sequence[dict[str, str]], destino: Path, *, compressao: str = "snappy"
) -> DatasetRef:
    """Grava o Parquet e devolve o `DatasetRef` com o hash lógico de referência."""
    tabela = pa.table({c: pa.array([item[c] for item in linhas], pa.string()) for c in COLUNAS})
    destino.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tabela, destino, compression=compressao)
    hash_logico = hash_logico_linhas(COLUNAS, [[item[c] for c in COLUNAS] for item in linhas])
    artefatos = (ARTEFATO,)
    return DatasetRef(
        dataset_id=calcular_dataset_id(SCHEMA, hash_logico, artefatos),
        schema_id=SCHEMA,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="tests.fixtures.reproducao_parquet",
    )


def reordenar_linhas(caminho: Path) -> bytes:
    """Mesmo conteúdo, outros bytes: linhas em ordem inversa e outra compressão."""
    original = caminho.read_bytes()
    tabela = pq.read_table(caminho)
    inversa = tabela.take(list(reversed(range(tabela.num_rows))))
    pq.write_table(inversa, caminho, compression="zstd")
    return original


def adulterar_coluna(caminho: Path, coluna: str, valor: object) -> bytes:
    """Muda o valor da coluna na primeira linha; devolve os bytes originais."""
    original = caminho.read_bytes()
    tabela = pq.read_table(caminho)
    indice = tabela.schema.get_field_index(coluna)
    campo = tabela.schema.field(indice)
    valores = tabela.column(indice).to_pylist()
    valores[0] = valor
    pq.write_table(tabela.set_column(indice, campo, pa.array(valores, campo.type)), caminho)
    return original


def _regravar(caminho: Path, tabela: pa.Table) -> bytes:
    original = caminho.read_bytes()
    pq.write_table(tabela, caminho)
    return original


def sem_coluna(caminho: Path, coluna: str) -> bytes:
    """Tira a coluna do arquivo (o leiaute deixa de ser o do esquema); devolve os originais."""
    return _regravar(caminho, pq.read_table(caminho).drop_columns([coluna]))


def com_coluna_a_mais(caminho: Path, nome: str = "coluna_a_mais") -> bytes:
    """Acrescenta uma coluna de texto que o esquema não tem; devolve os bytes originais."""
    tabela = pq.read_table(caminho)
    vazia = pa.array([""] * tabela.num_rows, pa.string())
    return _regravar(caminho, tabela.append_column(nome, vazia))


def com_coluna_como(caminho: Path, coluna: str, tipo: pa.DataType) -> bytes:
    """Converte a coluna para o `tipo` (os valores precisam caber nele); devolve os originais."""
    tabela = pq.read_table(caminho)
    indice = tabela.schema.get_field_index(coluna)
    convertida = pc.cast(tabela.column(indice), tipo)
    return _regravar(caminho, tabela.set_column(indice, coluna, convertida))


def com_as_duas_primeiras_colunas_trocadas(caminho: Path) -> bytes:
    """O mesmo conteúdo com a primeira e a segunda colunas na ordem inversa."""
    tabela = pq.read_table(caminho)
    nomes = tabela.column_names
    return _regravar(caminho, tabela.select([nomes[1], nomes[0], *nomes[2:]]))


def com_decimais_de_18_digitos(caminho: Path) -> bytes:
    """Mesmo valor, outro tipo físico: toda coluna DECIMAL(38,2) vira DECIMAL(18,2)."""
    tabela = pq.read_table(caminho)
    for indice, campo in enumerate(tabela.schema):
        if pa.types.is_decimal(campo.type):
            convertida = pc.cast(tabela.column(indice), pa.decimal128(18, 2))
            tabela = tabela.set_column(indice, campo.name, convertida)
    return _regravar(caminho, tabela)
