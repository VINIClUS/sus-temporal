"""Classificação de executabilidade e condições pendentes de um candidato (T09).

Executabilidade não é aprovação: mesmo `POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES` só diz que a
operação poderia ser feita hoje no CNES se as condições listadas forem verdadeiras.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts.counterfactual import Autoridade, Executabilidade, Governanca

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sustemporal.contracts import OperationSpec

__all__ = ["classificar", "competencia_fechada", "condicoes"]


def competencia_fechada(competencia: str, aberta: str | None, agora: datetime) -> bool | None:
    """`True` fechada, `False` aberta segundo evidência atual, `None` indeterminado.

    Sem evidência da competência aberta, toda competência anterior ao mês do relógio é tratada
    como encerrada (lado conservador: não declara nada executável); a do mês corrente fica
    indeterminada.
    """
    if aberta is not None:
        if competencia < aberta:
            return True
        return False if competencia == aberta else None
    corrente = f"{agora.year:04d}{agora.month:02d}"
    return True if competencia < corrente else None


def classificar(operacoes: Sequence[OperationSpec], fechada: bool | None) -> Executabilidade:
    """Competência encerrada domina; sem evidência atual, indeterminado; depois a governança."""
    if fechada is True:
        return Executabilidade.HIPOTESE_PASSADA
    if fechada is None:
        return Executabilidade.INDETERMINADO
    if any(op.governanca is Governanca.FORA_DA_GOVERNANCA_MUNICIPAL for op in operacoes):
        return Executabilidade.FORA_DA_GOVERNANCA
    desconhecida = any(
        op.governanca is Governanca.DESCONHECIDA or op.autoridade is Autoridade.DESCONHECIDA
        for op in operacoes
    )
    if desconhecida:
        return Executabilidade.INDETERMINADO
    return Executabilidade.POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES


def condicoes(
    operacoes: Sequence[OperationSpec], executabilidade: Executabilidade, competencia: str
) -> tuple[str, ...]:
    """Condições que a hipótese supõe e, se executável, as que a execução atual exige."""
    saida: list[str] = []
    for op in operacoes:
        saida.append(f"verdade_factual op={op.op_id}")
        saida.extend(f"precondicao op={op.op_id} nome={nome}" for nome in op.precondicoes)
    if executabilidade is Executabilidade.POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES:
        saida.append(f"competencia_aberta competencia={competencia}")
        saida.extend(f"autoridade op={op.op_id} autoridade={op.autoridade}" for op in operacoes)
    return tuple(dict.fromkeys(saida))
