"""Rótulos do PA_INDICA separados dos atributos (T03)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, RuntimeConfig


CONTRADICOES = (
    "APROVADO_PARCIAL_SEM_REDUCAO",
    "APROVADO_SEM_QUANTIDADE_APROVADA",
    "APROVADO_TOTAL_COM_QUANTIDADE_DIVERGENTE",
    "APROVADO_TOTAL_COM_VALOR_DIVERGENTE",
    "NAO_APROVADO_COM_QUANTIDADE_APROVADA",
    "NAO_APROVADO_COM_VALOR_APROVADO",
    "QUANTIDADE_APROVADA_MAIOR_QUE_APRESENTADA",
    "VALOR_APROVADO_MAIOR_QUE_APRESENTADO",
)


def label_pa(
    dataset: DatasetRef, codebook: Path, out: Path, *, runtime: RuntimeConfig | None = None
) -> DatasetRef:
    """Gera a tabela de rótulos preservando o valor bruto e a origem do código."""
    raise NotImplementedError
