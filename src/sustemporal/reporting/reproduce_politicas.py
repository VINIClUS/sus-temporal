"""Política de cada método como a execução congelada a usou (T14).

O `validate` resolve a política de uma execução por `config.politica_id` (a do catálogo, só do
método dela) ou, sem ele, pela padrão do método. A reprodução não pode aplicar a mesma
`politica_id` da config aos três métodos nem deixar a padrão onde o congelamento usou outra: cada
método é refeito com a política da entrada de validação original (`split/insumos`), conferida
contra o manifesto e contra a execução registrada. Política que não se resolve ou não se confere
é um problema da política congelada (item `insumos:<politica>` inconclusivo), nunca erro de
configuração nem divergência.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.temporal.politicas import DIRETORIO_POLITICAS

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import MetodoId
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = ["DIRETORIO_POLITICAS", "PoliticasCongeladas", "politicas_congeladas"]


@dataclass(frozen=True)
class PoliticasCongeladas:
    """`config.politica_id` que refaz cada método (None: a padrão) e o motivo, por política."""

    por_metodo: Mapping[MetodoId, str | None]
    problemas: Mapping[str, str]


def politicas_congeladas(
    entradas: Mapping[str, EntradaValidacao],
    identidades: Mapping[str, Mapping[str, str]],
    registradas: Mapping[MetodoId, str | None],
    regras: Sequence[RuleSpec],
    diretorio: Path | None = None,
) -> PoliticasCongeladas:
    raise NotImplementedError
