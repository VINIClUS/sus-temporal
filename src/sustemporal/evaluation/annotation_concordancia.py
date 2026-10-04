"""Concordância antes da adjudicação, referência humana e comparação com o motor (T12).

A adjudicação recebe só as respostas dos avaliadores, nunca explicações do motor. A comparação com
o motor só existe sobre referência FECHADA; indeterminação e evidência insuficiente ficam em
categorias próprias e nunca viram acerto ou erro do motor.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    AvaliacaoCaso,
    ConclusaoCaso,
    EstadoReferencia,
    FamiliaRegra,
    ReferenciaHumana,
)
from sustemporal.errors import ErroSustemporal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sustemporal.contracts import AnnotationSample

__all__ = [
    "CATEGORIAS_COMPARACAO",
    "ReferenciaNaoFechada",
    "RelatorioConcordancia",
    "comparar_com_motor",
    "concordancia",
    "estimar_horas",
    "fechar_referencia",
    "kappa_cohen",
]

logger = logging.getLogger(__name__)

CATEGORIAS_COMPARACAO = (
    "IGUAL",
    "PARCIAL",
    "DIVERGENTE",
    "MOTOR_SEM_FAMILIA",
    "MOTOR_SEM_RESULTADO",
    "CONCORDA_FORA_DE_ESCOPO",
    "MOTOR_ATRIBUI_FAMILIA_FORA_DE_ESCOPO",
    ConclusaoCaso.CAUSA_INDETERMINADA.value,
    ConclusaoCaso.EVIDENCIA_INSUFICIENTE.value,
)
_NAO_DETERMINADAS = {ConclusaoCaso.CAUSA_INDETERMINADA, ConclusaoCaso.EVIDENCIA_INSUFICIENTE}


class ReferenciaNaoFechada(ErroSustemporal):
    """Comparação com o motor tentada antes de a referência humana ser fechada."""


@dataclass(frozen=True)
class RelatorioConcordancia:
    casos: int
    bruta: Fraction
    kappa: Fraction | None
    por_familia: dict[str, tuple[Fraction, Fraction | None]]


def kappa_cohen(pares: Sequence[tuple[str, str]]) -> Fraction | None:
    """κ de Cohen exato; None quando a concordância esperada é 1."""
    total = len(pares)
    if total == 0:
        raise ValueError("kappa_sem_casos")
    observada = Fraction(sum(1 for a, b in pares if a == b), total)
    marg_a = Counter(a for a, _ in pares)
    marg_b = Counter(b for _, b in pares)
    esperada = sum(
        (Fraction(marg_a[c], total) * Fraction(marg_b[c], total) for c in marg_a), Fraction(0)
    )
    if esperada == 1:
        return None
    return (observada - esperada) / (1 - esperada)


def _por_caso(
    amostra: AnnotationSample, mapa: Mapping[str, str], avaliacoes: Iterable[AvaliacaoCaso]
) -> dict[str, AvaliacaoCaso]:
    finais, treino = set(amostra.casos), set(amostra.casos_treino)
    respostas: dict[str, AvaliacaoCaso] = {}
    for avaliacao in avaliacoes:
        row_id = mapa.get(avaliacao.caso_id)
        if row_id in treino:
            raise ValueError(f"caso_de_treino_na_avaliacao_final caso={avaliacao.caso_id}")
        if row_id not in finais:
            raise ValueError(f"caso_fora_da_amostra caso={avaliacao.caso_id}")
        if avaliacao.caso_id in respostas:
            raise ValueError(f"avaliacao_repetida caso={avaliacao.caso_id}")
        respostas[avaliacao.caso_id] = avaliacao
    return respostas


def _pareadas(
    amostra: AnnotationSample,
    mapa: Mapping[str, str],
    avaliador_a: Iterable[AvaliacaoCaso],
    avaliador_b: Iterable[AvaliacaoCaso],
) -> list[tuple[AvaliacaoCaso, AvaliacaoCaso]]:
    a = _por_caso(amostra, mapa, avaliador_a)
    b = _por_caso(amostra, mapa, avaliador_b)
    esperados = {caso for caso, row_id in mapa.items() if row_id in set(amostra.casos)}
    if set(a) != esperados or set(b) != esperados:
        raise ValueError(f"avaliacoes_incompletas esperados={len(esperados)} a={len(a)} b={len(b)}")
    avaliadores = {x.avaliador for x in a.values()} & {x.avaliador for x in b.values()}
    if avaliadores:
        raise ValueError(f"avaliador_nos_dois_lados avaliadores={sorted(avaliadores)}")
    return [(a[caso], b[caso]) for caso in sorted(esperados)]


def _categoria_familia(avaliacao: AvaliacaoCaso, familia: FamiliaRegra) -> str:
    if avaliacao.conclusao in _NAO_DETERMINADAS:
        return "NAO_DETERMINADO"
    return "PRESENTE" if familia in avaliacao.familias else "AUSENTE"


def _bruta(pares: Sequence[tuple[str, str]]) -> Fraction:
    return Fraction(sum(1 for a, b in pares if a == b), len(pares))


def concordancia(
    amostra: AnnotationSample,
    mapa: Mapping[str, str],
    avaliador_a: Iterable[AvaliacaoCaso],
    avaliador_b: Iterable[AvaliacaoCaso],
) -> RelatorioConcordancia:
    """Concordância bruta e κ, global e por família, antes da adjudicação.

    Por família, cada resposta é PRESENTE, AUSENTE ou NAO_DETERMINADO (indeterminada ou com
    evidência insuficiente); nenhuma causa única é forçada.

    Raises:
        ValueError: caso de treino, fora da amostra, repetido, avaliação incompleta ou mesmo
            avaliador dos dois lados.
    """
    pareadas = _pareadas(amostra, mapa, avaliador_a, avaliador_b)
    globais = [(a.conclusao.value, b.conclusao.value) for a, b in pareadas]
    familias = sorted({f for a, b in pareadas for f in (*a.familias, *b.familias)})
    por_familia: dict[str, tuple[Fraction, Fraction | None]] = {}
    for familia in familias:
        pares = [
            (_categoria_familia(a, familia), _categoria_familia(b, familia)) for a, b in pareadas
        ]
        por_familia[familia.value] = (_bruta(pares), kappa_cohen(pares))
    relatorio = RelatorioConcordancia(
        casos=len(pareadas),
        bruta=_bruta(globais),
        kappa=kappa_cohen(globais),
        por_familia=por_familia,
    )
    logger.info(
        "concordancia_anotacao amostra=%s casos=%d bruta=%s kappa=%s",
        amostra.sample_id,
        relatorio.casos,
        relatorio.bruta,
        relatorio.kappa,
    )
    return relatorio


def _mesma_resposta(a: AvaliacaoCaso, b: AvaliacaoCaso) -> bool:
    return a.conclusao is b.conclusao and set(a.familias) == set(b.familias)


def fechar_referencia(
    amostra: AnnotationSample,
    mapa: Mapping[str, str],
    avaliador_a: Iterable[AvaliacaoCaso],
    avaliador_b: Iterable[AvaliacaoCaso],
    adjudicacoes: Iterable[AvaliacaoCaso] = (),
) -> ReferenciaHumana:
    """Consenso ou adjudicação cega por caso; pendências deixam a referência ABERTA.

    Raises:
        ValueError: avaliações inválidas (ver `concordancia`) ou adjudicação de caso sem
            divergência ou fora da amostra.
    """
    pareadas = _pareadas(amostra, mapa, avaliador_a, avaliador_b)
    adjudicadas = _por_caso(amostra, mapa, adjudicacoes)
    casos: dict[str, AvaliacaoCaso] = {}
    pendentes: list[str] = []
    for a, b in pareadas:
        caso = a.caso_id
        if _mesma_resposta(a, b):
            if caso in adjudicadas:
                raise ValueError(f"adjudicacao_sem_divergencia caso={caso}")
            casos[mapa[caso]] = a
        elif caso in adjudicadas:
            casos[mapa[caso]] = adjudicadas[caso]
        else:
            pendentes.append(caso)
    estado = EstadoReferencia.ABERTA if pendentes else EstadoReferencia.FECHADA
    logger.info(
        "referencia_anotacao amostra=%s estado=%s pendentes=%d",
        amostra.sample_id,
        estado,
        len(pendentes),
    )
    return ReferenciaHumana(
        sample_id=amostra.sample_id, estado=estado, casos=casos, pendentes=tuple(pendentes)
    )


def _categoria_comparacao(referencia: AvaliacaoCaso, motor: frozenset[FamiliaRegra] | None) -> str:
    if referencia.conclusao in _NAO_DETERMINADAS:
        return referencia.conclusao.value
    if motor is None:
        return "MOTOR_SEM_RESULTADO"
    if referencia.conclusao is ConclusaoCaso.CAUSA_FORA_DE_ESCOPO_DOCUMENTADA:
        return "MOTOR_ATRIBUI_FAMILIA_FORA_DE_ESCOPO" if motor else "CONCORDA_FORA_DE_ESCOPO"
    humanas = set(referencia.familias)
    if not motor:
        return "MOTOR_SEM_FAMILIA"
    if motor == humanas:
        return "IGUAL"
    return "PARCIAL" if motor & humanas else "DIVERGENTE"


def comparar_com_motor(
    referencia: ReferenciaHumana, familias_motor: Mapping[str, frozenset[FamiliaRegra]]
) -> dict[str, int]:
    """Contagens por categoria de comparação, por row_id; recusa referência ABERTA.

    Raises:
        ReferenciaNaoFechada: referência ainda com casos pendentes de adjudicação.
    """
    if referencia.estado is not EstadoReferencia.FECHADA:
        raise ReferenciaNaoFechada(
            f"referencia_nao_fechada amostra={referencia.sample_id} "
            f"pendentes={len(referencia.pendentes)}"
        )
    contagens = dict.fromkeys(CATEGORIAS_COMPARACAO, 0)
    for row_id, avaliacao in sorted(referencia.casos.items()):
        contagens[_categoria_comparacao(avaliacao, familias_motor.get(row_id))] += 1
    return contagens


def estimar_horas(
    minutos_por_caso: Fraction, *, casos: int = 400, avaliadores: int = 2
) -> Fraction:
    """Planejamento: avaliadores × casos × minutos / 60, sem a adjudicação."""
    if minutos_por_caso < 0 or casos < 0 or avaliadores < 1:
        raise ValueError(f"estimativa_invalida minutos={minutos_por_caso} casos={casos}")
    return Fraction(avaliadores * casos) * Fraction(minutos_por_caso) / 60
