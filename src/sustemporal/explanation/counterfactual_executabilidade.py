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

__all__ = [
    "aberta_coerente",
    "classificar",
    "competencia_do_relogio",
    "competencia_fechada",
    "condicoes",
]

_FORA_DO_MUNICIPIO = frozenset({Autoridade.GESTOR_ESTADUAL, Autoridade.MINISTERIO_SAUDE})


def competencia_do_relogio(agora: datetime, recuo: int = 0) -> str:
    """Competência AAAAMM do mês do relógio, recuada `recuo` meses."""
    meses = agora.year * 12 + agora.month - 1 - recuo
    return f"{meses // 12:04d}{meses % 12 + 1:02d}"


def aberta_coerente(aberta: str | None, agora: datetime) -> bool:
    """Evidência atual só vale se a competência aberta é a do mês do relógio ou a anterior."""
    return aberta in {competencia_do_relogio(agora), competencia_do_relogio(agora, 1)}


def competencia_fechada(competencia: str, aberta: str | None, agora: datetime) -> bool | None:
    """`True` fechada, `False` aberta segundo evidência atual, `None` indeterminado.

    Competência aberta incoerente com o relógio é ignorada. Sem evidência coerente, competência
    anterior ao mês que precede o relógio é tratada como encerrada (lado conservador: nada é
    declarado executável); a do mês anterior e a do corrente ficam indeterminadas.
    """
    if aberta is not None and aberta_coerente(aberta, agora):
        if competencia < aberta:
            return True
        return False if competencia == aberta else None
    return True if competencia < competencia_do_relogio(agora, 1) else None


def classificar(operacoes: Sequence[OperationSpec], fechada: bool | None) -> Executabilidade:
    """Competência encerrada domina; sem evidência atual, indeterminado; depois a governança.

    Autoridade estadual ou federal com governança que não a declara fora do município é
    incoerente e fica indeterminada.
    """
    if fechada is True:
        return Executabilidade.HIPOTESE_PASSADA
    if fechada is None:
        return Executabilidade.INDETERMINADO
    fora = Governanca.FORA_DA_GOVERNANCA_MUNICIPAL
    if any(op.autoridade in _FORA_DO_MUNICIPIO and op.governanca is not fora for op in operacoes):
        return Executabilidade.INDETERMINADO
    if any(op.governanca is fora for op in operacoes):
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
