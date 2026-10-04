"""Métricas pareadas sobre linhas já avaliadas, com denominadores explícitos (T11)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sustemporal.contracts.evaluation import ValorMetrica

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "FORA_DE_ESCOPO_DOCUMENTADA",
    "NAO_APROVADO",
    "LinhaAvaliada",
    "Situacao",
    "calcular_metricas",
    "indicadores",
    "razao",
]

NAO_APROVADO = "NAO_APROVADO"
APROVADO_TOTAL = "APROVADO_TOTAL"
APROVADO_PARCIAL = "APROVADO_PARCIAL"
FORA_DE_ESCOPO_DOCUMENTADA = "CAUSA_FORA_DE_ESCOPO_DOCUMENTADA"
_CASAS = Decimal("0.000001")
_BINARIOS = frozenset({NAO_APROVADO, APROVADO_TOTAL})


class Situacao(StrEnum):
    ALERTA = "ALERTA"
    SEM_ALERTA = "SEM_ALERTA"
    ABSTENCAO = "ABSTENCAO"


@dataclass(frozen=True)
class LinhaAvaliada:
    """Registro da população com rótulo, estratos e a situação de cada método."""

    row_id: str
    rotulo: str | None
    cnes: str | None
    competencia: str | None
    instrumento: str | None
    situacoes: Mapping[str, Situacao] = field(default_factory=dict)
    no_dominio_comum: bool = False
    causa: str | None = None


def razao(nome: str, estrato: str, numerador: int, denominador: int) -> ValorMetrica:
    """Razão com 6 casas (meio-par); denominador zero dá valor None, nunca zero."""
    valor = None
    if denominador > 0:
        valor = (Decimal(numerador) / Decimal(denominador)).quantize(
            _CASAS, rounding=ROUND_HALF_EVEN
        )
    return ValorMetrica(
        nome=nome, estrato=estrato, numerador=numerador, denominador=denominador, valor=valor
    )


def _situacao(linha: LinhaAvaliada, metodo: str) -> Situacao:
    return linha.situacoes.get(metodo, Situacao.ABSTENCAO)


def _contar(linhas: Sequence[LinhaAvaliada], condicao: Callable[[LinhaAvaliada], bool]) -> int:
    return sum(1 for linha in linhas if condicao(linha))


def _do_rotulo(linhas: Sequence[LinhaAvaliada], rotulo: str) -> list[LinhaAvaliada]:
    return [linha for linha in linhas if linha.rotulo == rotulo]


Predicado = Callable[[LinhaAvaliada], bool]


def _definicoes(metodo: str) -> dict[str, tuple[Predicado, Predicado]]:
    """Por métrica, os predicados (numerador, denominador) avaliados linha a linha."""

    def alerta(linha: LinhaAvaliada) -> bool:
        return _situacao(linha, metodo) is Situacao.ALERTA

    def rejeicao(linha: LinhaAvaliada) -> bool:
        return linha.rotulo == NAO_APROVADO

    def aprovacao(linha: LinhaAvaliada) -> bool:
        return linha.rotulo == APROVADO_TOTAL

    def parcial(linha: LinhaAvaliada) -> bool:
        return linha.rotulo == APROVADO_PARCIAL

    def sem_alerta(linha: LinhaAvaliada) -> bool:
        return rejeicao(linha) and not alerta(linha)

    def documentada(linha: LinhaAvaliada) -> bool:
        return linha.causa == FORA_DE_ESCOPO_DOCUMENTADA

    def abstencao(linha: LinhaAvaliada) -> bool:
        return _situacao(linha, metodo) is Situacao.ABSTENCAO

    def todas(_: LinhaAvaliada) -> bool:
        return True

    return {
        "cobertura_rejeicoes": (alerta, rejeicao),
        "cobertura_verificabilidade": (lambda linha: not abstencao(linha), todas),
        "precisao_alertas": (rejeicao, lambda linha: alerta(linha) and linha.rotulo in _BINARIOS),
        "falsos_alertas_aprovacoes": (alerta, aprovacao),
        "abstencao": (abstencao, todas),
        "alerta_aprovacao_parcial": (alerta, parcial),
        "rejeicoes_sem_alerta_fora_de_escopo_documentada": (documentada, sem_alerta),
        "rejeicoes_sem_alerta_causa_indeterminada": (
            lambda linha: not documentada(linha),
            sem_alerta,
        ),
    }


def indicadores(
    linhas: Sequence[LinhaAvaliada], metodo: str, nome: str
) -> tuple[list[int], list[int]]:
    """Numerador e denominador de cada linha (0 ou 1), na mesma definição da métrica."""
    numerador, denominador = _definicoes(metodo)[nome]
    dens = [int(denominador(linha)) for linha in linhas]
    nums = [int(d == 1 and numerador(linha)) for d, linha in zip(dens, linhas, strict=True)]
    return nums, dens


def _por_metodo(metodo: str, estrato: str, linhas: Sequence[LinhaAvaliada]) -> list[ValorMetrica]:
    metricas = []
    for nome in _definicoes(metodo):
        nums, dens = indicadores(linhas, metodo, nome)
        metricas.append(razao(f"{metodo}.{nome}", estrato, sum(nums), sum(dens)))
    return metricas


def _estratos(linhas: Sequence[LinhaAvaliada]) -> dict[str, list[LinhaAvaliada]]:
    estratos: dict[str, list[LinhaAvaliada]] = {
        "TOTAL": list(linhas),
        "dominio_comum": [linha for linha in linhas if linha.no_dominio_comum],
    }
    for linha in linhas:
        for chave, valor in (
            ("instrumento", linha.instrumento),
            ("competencia", linha.competencia),
        ):
            estratos.setdefault(f"{chave}={valor}", []).append(linha)
    return estratos


def _pareadas(a: str, b: str, linhas: Sequence[LinhaAvaliada]) -> list[ValorMetrica]:
    rejeicoes = _do_rotulo(linhas, NAO_APROVADO)
    so_a = _contar(
        rejeicoes,
        lambda linha: (
            _situacao(linha, a) is Situacao.ALERTA and _situacao(linha, b) is not Situacao.ALERTA
        ),
    )
    so_b = _contar(
        rejeicoes,
        lambda linha: (
            _situacao(linha, b) is Situacao.ALERTA and _situacao(linha, a) is not Situacao.ALERTA
        ),
    )
    discordantes = _contar(linhas, lambda linha: _situacao(linha, a) is not _situacao(linha, b))
    prefixo = f"divergencia.{a}_x_{b}"
    return [
        razao(f"{prefixo}.so_{a}", "TOTAL", so_a, len(rejeicoes)),
        razao(f"{prefixo}.so_{b}", "TOTAL", so_b, len(rejeicoes)),
        razao(f"{prefixo}.discordancia", "TOTAL", discordantes, len(linhas)),
    ]


def calcular_metricas(
    linhas: Sequence[LinhaAvaliada],
    metodos: Sequence[str],
    *,
    pares: Sequence[tuple[str, str]] = (),
) -> list[ValorMetrica]:
    """Métricas por método e estrato, divergências pareadas e domínio comum.

    A população inteira (inconclusivas e linhas sem situação do método inclusive) fica nos
    denominadores de cobertura; o domínio comum vem de `no_dominio_comum`, definido sem o
    resultado dos métodos; rejeição sem alerta só é fora de escopo com causa documentada.
    """
    metricas: list[ValorMetrica] = []
    for estrato, subconjunto in _estratos(linhas).items():
        metricas.append(razao("populacao.tamanho_estrato", estrato, len(subconjunto), len(linhas)))
        for metodo in metodos:
            metricas.extend(_por_metodo(metodo, estrato, subconjunto))
    for a, b in pares:
        metricas.extend(_pareadas(a, b, linhas))
    return metricas
