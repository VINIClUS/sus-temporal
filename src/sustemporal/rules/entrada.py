"""Entrada explícita da validação, gravada com as saídas de cada execução."""

from __future__ import annotations

from pydantic import Field

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import ContratoBase
from sustemporal.contracts.records import DatasetRef
from sustemporal.contracts.temporal import PoliticaTemporal, SnapshotSet

__all__ = ["ARQUIVO_ENTRADA", "EntradaValidacao"]

ARQUIVO_ENTRADA = "entrada_validacao.json"


class EntradaValidacao(ContratoBase):
    """Insumos explícitos da validação; nenhum diretório "latest" é resolvido implicitamente.

    `politica` é a política resolvida da execução (gravada por toda execução do `validate`);
    `politica_documentada` continua aceita na entrada para M_TEMP.
    """

    dataset: DatasetRef
    snapshots: SnapshotSet
    auxiliares: tuple[DatasetRef, ...] = ()
    selecoes: DatasetRef | None = None
    cobertura: DatasetRef | None = None
    integridade: dict[str, EstadoIntegridade] = Field(default_factory=dict)
    politica_documentada: PoliticaTemporal | None = None
    politica: PoliticaTemporal | None = None
