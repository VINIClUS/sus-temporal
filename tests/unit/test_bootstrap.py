"""Bootstrap por conglomerado do T11 (SINTETICO): conglomerado inteiro, nunca linha isolada."""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from sustemporal.contracts.experiment import BootstrapSpec
from sustemporal.evaluation.bootstrap import intervalo_razao, reamostrar_razao

SPEC = BootstrapSpec(reamostragens=500, semente=2027, correcao="HOLM")


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


def test_um_unico_conglomerado_nao_finge_variabilidade() -> None:
    intervalo = intervalo_razao([1, 0, 1], [1, 1, 1], ["A", "A", "A"], SPEC)
    assert intervalo is not None
    assert intervalo.inferior == intervalo.superior


def test_sem_denominador_positivo_nao_ha_intervalo() -> None:
    assert intervalo_razao([0, 0], [0, 0], ["A", "B"], SPEC) is None
