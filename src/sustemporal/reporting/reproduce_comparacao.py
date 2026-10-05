"""Comparação do refeito com o congelado: hash lógico, contagens e métricas (T14)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts.evaluation import ValorMetrica
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = [
    "Comparacao",
    "Identidade",
    "Situacao",
    "comparar_insumos",
    "comparar_metricas",
    "comparar_referencia",
    "comparar_saida",
    "divergentes",
    "identidade_do_arquivo",
]


class Situacao(StrEnum):
    IGUAL = "IGUAL"
    BYTES_DIFERENTES = "BYTES_DIFERENTES_HASH_LOGICO_IGUAL"
    DIVERGENTE = "DIVERGENTE"
    INCONCLUSIVO = "INCONCLUSIVO"


@dataclass(frozen=True)
class Identidade:
    """Contagem, hash lógico e SHA-256 dos bytes de um Parquet."""

    linhas: int
    hash_logico: str
    sha256: str


@dataclass(frozen=True)
class Comparacao:
    """Um item comparado: o que se esperava, o que se obteve e a situação."""

    item: str
    situacao: Situacao
    esperado: str | None = None
    obtido: str | None = None
    detalhe: str = ""

    def como_dict(self) -> dict[str, Any]:
        raise NotImplementedError


def identidade_do_arquivo(
    caminho: Path, schema_id: str, *, sem_colunas: Collection[str] = ()
) -> Identidade:
    raise NotImplementedError


def comparar_referencia(item: str, esperada: DatasetRef, obtida: DatasetRef) -> Comparacao:
    raise NotImplementedError


def comparar_saida(
    item: str,
    original: DatasetRef | None,
    obtida: DatasetRef,
    *,
    sem_colunas: Collection[str] = ("run_id",),
) -> Comparacao:
    raise NotImplementedError


def comparar_metricas(
    item: str, esperadas: Sequence[ValorMetrica] | None, obtidas: Sequence[ValorMetrica]
) -> Comparacao:
    raise NotImplementedError


def comparar_insumos(
    item: str, congeladas: Mapping[str, str] | None, entrada: EntradaValidacao
) -> Comparacao:
    raise NotImplementedError


def divergentes(comparacoes: Iterable[Comparacao]) -> list[Comparacao]:
    raise NotImplementedError
