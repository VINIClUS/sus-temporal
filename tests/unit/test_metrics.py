"""Métricas do T11 contra tabelas pequenas calculadas à mão (SINTETICO)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from sustemporal.evaluation.metrics_calculo import LinhaAvaliada, Situacao, calcular_metricas

if TYPE_CHECKING:
    from sustemporal.contracts.evaluation import ValorMetrica

    Metricas = dict[tuple[str, str], ValorMetrica]

A, S, X = Situacao.ALERTA, Situacao.SEM_ALERTA, Situacao.ABSTENCAO

# row_id, rótulo, instrumento, situação de M, situação de B, domínio comum, causa anotada
TABELA = [
    ("r1", "NAO_APROVADO", "C", A, S, True, None),
    ("r2", "NAO_APROVADO", "C", S, A, True, "CAUSA_FORA_DE_ESCOPO_DOCUMENTADA"),
    ("r3", "NAO_APROVADO", "C", X, A, False, None),
    ("r4", "APROVADO_TOTAL", "C", A, A, True, None),
    ("r5", "APROVADO_TOTAL", "I", S, S, True, None),
    ("r6", "APROVADO_TOTAL", "I", S, S, False, None),
    ("r7", "APROVADO_PARCIAL", "I", A, A, False, None),
    ("r8", "DESCONHECIDO", "I", X, X, False, None),
]


def _linhas() -> list[LinhaAvaliada]:
    return [
        LinhaAvaliada(
            row_id=row_id,
            rotulo=rotulo,
            cnes=f"000000{i % 2}",
            competencia="202401",
            instrumento=instrumento,
            situacoes={"M": m, "B": b},
            no_dominio_comum=dominio,
            causa=causa,
        )
        for i, (row_id, rotulo, instrumento, m, b, dominio, causa) in enumerate(TABELA)
    ]


@pytest.fixture(scope="module")
def metricas() -> Metricas:
    valores = calcular_metricas(_linhas(), ["M", "B"], pares=[("M", "B")])
    return {(v.nome, v.estrato): v for v in valores}


def _razao(
    metricas: Metricas, nome: str, estrato: str = "TOTAL"
) -> tuple[int, int, Decimal | None]:
    valor = metricas[(nome, estrato)]
    return valor.numerador, valor.denominador, valor.valor


def test_cobertura_de_rejeicoes_inclui_inconclusivas_no_denominador(metricas: Metricas) -> None:
    assert _razao(metricas, "M.cobertura_rejeicoes") == (1, 3, Decimal("0.333333"))


def test_cobertura_de_verificabilidade_sobre_toda_a_populacao(metricas: Metricas) -> None:
    assert _razao(metricas, "M.cobertura_verificabilidade") == (6, 8, Decimal("0.75"))


def test_precisao_dos_alertas(metricas: Metricas) -> None:
    assert _razao(metricas, "M.precisao_alertas") == (1, 2, Decimal("0.5"))


def test_falsos_alertas_em_aprovacoes(metricas: Metricas) -> None:
    assert _razao(metricas, "M.falsos_alertas_aprovacoes") == (1, 3, Decimal("0.333333"))


def test_abstencao(metricas: Metricas) -> None:
    assert _razao(metricas, "M.abstencao") == (2, 8, Decimal("0.25"))


def test_aprovacao_parcial_reportada_a_parte(metricas: Metricas) -> None:
    assert _razao(metricas, "M.alerta_aprovacao_parcial") == (1, 1, Decimal("1"))
    assert _razao(metricas, "M.precisao_alertas")[1] == 2


def test_causa_fora_de_escopo_documentada_distinta_de_indeterminada(metricas: Metricas) -> None:
    assert _razao(metricas, "M.rejeicoes_sem_alerta_fora_de_escopo_documentada") == (
        1,
        2,
        Decimal("0.5"),
    )
    assert _razao(metricas, "M.rejeicoes_sem_alerta_causa_indeterminada") == (
        1,
        2,
        Decimal("0.5"),
    )


def test_divergencias_pareadas(metricas: Metricas) -> None:
    assert _razao(metricas, "divergencia.M_x_B.so_M") == (1, 3, Decimal("0.333333"))
    assert _razao(metricas, "divergencia.M_x_B.so_B") == (2, 3, Decimal("0.666667"))
    assert _razao(metricas, "divergencia.M_x_B.discordancia") == (3, 8, Decimal("0.375"))


def test_dominio_comum_definido_sem_resultado_dos_metodos(metricas: Metricas) -> None:
    assert _razao(metricas, "M.cobertura_rejeicoes", "dominio_comum") == (1, 2, Decimal("0.5"))
    assert _razao(metricas, "B.cobertura_rejeicoes", "dominio_comum") == (1, 2, Decimal("0.5"))


def test_tamanho_dos_estratos(metricas: Metricas) -> None:
    assert _razao(metricas, "populacao.tamanho_estrato", "instrumento=C") == (
        4,
        8,
        Decimal("0.5"),
    )
    assert _razao(metricas, "M.cobertura_rejeicoes", "instrumento=C") == (
        1,
        3,
        Decimal("0.333333"),
    )


def test_denominador_zero_da_valor_none() -> None:
    linhas = [
        LinhaAvaliada(
            row_id="r1",
            rotulo="APROVADO_TOTAL",
            cnes="0000001",
            competencia="202401",
            instrumento="C",
            situacoes={"M": S},
        )
    ]
    valores = {(v.nome, v.estrato): v for v in calcular_metricas(linhas, ["M"])}
    precisao = valores[("M.precisao_alertas", "TOTAL")]
    rejeicoes = valores[("M.cobertura_rejeicoes", "TOTAL")]
    assert (precisao.denominador, precisao.valor) == (0, None)
    assert (rejeicoes.denominador, rejeicoes.valor) == (0, None)


def test_linha_sem_situacao_do_metodo_conta_como_abstencao() -> None:
    linhas = [
        LinhaAvaliada(
            row_id="r1",
            rotulo="NAO_APROVADO",
            cnes="0000001",
            competencia="202401",
            instrumento="C",
            situacoes={},
        )
    ]
    valores = {(v.nome, v.estrato): v for v in calcular_metricas(linhas, ["M"])}
    assert valores[("M.abstencao", "TOTAL")].numerador == 1
    assert valores[("M.cobertura_verificabilidade", "TOTAL")].numerador == 0
