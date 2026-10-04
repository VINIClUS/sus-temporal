"""Evidências reexecutáveis: consulta parametrizada, fonte, cobertura e integridade (T08)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts.explanation import Evidence
    from sustemporal.contracts.records import DatasetRef


class EvidenciaDivergente(ValueError):
    """Reexecução da consulta da evidência não reproduz o resultado ou o hash."""


def sql_reexecucao(query_id: str) -> str:
    raise NotImplementedError


def ler_evidencia(linha: Mapping[str, object]) -> Evidence:
    raise NotImplementedError


def reexecutar_evidencia(evidencia: Evidence, conjuntos: Mapping[str, DatasetRef]) -> object:
    raise NotImplementedError
