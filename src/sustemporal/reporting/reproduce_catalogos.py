"""Catálogos que o congelamento registrou, contra os que a reprodução usa agora (T14).

O manifesto guarda o SHA-256 de cada catálogo que a config declara e o do catálogo de regras. A
reprodução usa os de agora: se diferem, a diferença vira observação (não impede a conferência: o
conteúdo refeito decide se o resultado é igual ou divergente).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sustemporal.contracts.rules import RuleSpec

__all__ = ["observacoes_dos_catalogos"]


def observacoes_dos_catalogos(
    congelados: Mapping[str, str],
    catalogos: Mapping[str, str],
    regras_congeladas: str | None,
    regras: Sequence[RuleSpec],
) -> list[str]:
    raise NotImplementedError
