"""Bootstrap por conglomerado do T11 (SINTETICO): conglomerado inteiro, nunca linha isolada."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from sustemporal.contracts.experiment import BootstrapSpec
from sustemporal.evaluation.bootstrap import intervalo_diferenca, intervalo_razao, reamostrar_razao

SPEC = BootstrapSpec(reamostragens=500, semente=2027, correcao="HOLM")
SPEC_DO_PLANO = BootstrapSpec(reamostragens=2000, semente=2027)
VINTE_ESTABELECIMENTOS = [f"E{e:02d}" for e in range(20) for _ in range(10)]


def test_reamostra_estabelecimento_inteiro_e_nao_linhas() -> None:
    numeradores = [1] * 5 + [0] * 5
    denominadores = [1] * 10
    grupos = ["A"] * 5 + ["B"] * 5
    razoes = reamostrar_razao(numeradores, denominadores, grupos, SPEC)
    assert set(np.round(razoes, 6).tolist()) <= {0.0, 0.5, 1.0}
    assert len(razoes) == SPEC.reamostragens


def test_mesma_semente_mesmas_reamostragens() -> None:
    dados = ([1, 0, 1, 1, 0, 0], [1] * 6, ["A", "A", "B", "C", "C", "D"])
    primeira = reamostrar_razao(*dados, SPEC)
    segunda = reamostrar_razao(*dados, SPEC)
    assert np.array_equal(primeira, segunda)


def test_intervalo_contem_a_estimativa_e_respeita_o_nivel() -> None:
    numeradores = [1, 0, 1, 1, 0, 0, 1, 0]
    denominadores = [1] * 8
    grupos = ["A", "A", "B", "B", "C", "C", "D", "D"]
    intervalo = intervalo_razao(numeradores, denominadores, grupos, SPEC)
    assert intervalo is not None
    assert intervalo.nivel == Decimal("0.95")
    assert intervalo.inferior <= Decimal("0.5") <= intervalo.superior
    assert getattr(intervalo, "replicas_validas", None) == SPEC.reamostragens


def test_um_unico_conglomerado_nao_finge_variabilidade() -> None:
    assert intervalo_razao([1, 0, 1], [1, 1, 1], ["A", "A", "A"], SPEC) is None


def test_um_so_estabelecimento_com_denominador_positivo_nao_tem_intervalo() -> None:
    """Auditoria final, D3: toda réplica válida repetia a estimativa (largura zero)."""
    grupos = VINTE_ESTABELECIMENTOS
    denominadores = [int(g == "E00" and i % 10 < 3) for i, g in enumerate(grupos)]
    numeradores = [int(d == 1 and i % 10 < 2) for i, d in enumerate(denominadores)]
    assert intervalo_razao(numeradores, denominadores, grupos, SPEC_DO_PLANO) is None


def test_diferenca_com_um_so_estabelecimento_de_denominador_positivo_nao_tem_intervalo() -> None:
    grupos = VINTE_ESTABELECIMENTOS
    denominadores = [int(g == "E00") for g in grupos]
    sem_sinal = [0] * len(grupos)
    assert (
        intervalo_diferenca(denominadores, sem_sinal, denominadores, grupos, SPEC_DO_PLANO) is None
    )


def test_intervalo_registra_as_replicas_validas() -> None:
    """Réplicas com denominador zero ficam fora dos percentis; o intervalo diz quantas sobram."""
    grupos = VINTE_ESTABELECIMENTOS
    denominadores = [int(g in {"E00", "E01"}) for g in grupos]
    numeradores = [int(g == "E00") for g in grupos]
    replicas = reamostrar_razao(numeradores, denominadores, grupos, SPEC_DO_PLANO)
    validas = int(np.count_nonzero(~np.isnan(replicas)))
    assert 0 < validas < SPEC_DO_PLANO.reamostragens
    razao = intervalo_razao(numeradores, denominadores, grupos, SPEC_DO_PLANO)
    sem_sinal = [0] * len(grupos)
    diferenca = intervalo_diferenca(numeradores, sem_sinal, denominadores, grupos, SPEC_DO_PLANO)
    assert razao is not None
    assert diferenca is not None
    assert getattr(razao, "replicas_validas", None) == validas
    assert getattr(diferenca, "replicas_validas", None) == validas


def test_sem_denominador_positivo_nao_ha_intervalo() -> None:
    assert intervalo_razao([0, 0], [0, 0], ["A", "B"], SPEC) is None
