"""Sensibilidade por blocos temporais para cada métrica com intervalo (T11, SINTETICO).

O plano pede o bootstrap por estabelecimento e a análise de sensibilidade por blocos temporais.
O relatório só trazia a segunda nas diferenças pareadas; as quatro métricas com intervalo (cobertura
de rejeições, cobertura de verificabilidade, precisão dos alertas e falsos alertas em aprovações)
só levavam o intervalo por estabelecimento. Cada uma, por método, passa a ter a contrapartida no
estrato `sensibilidade_blocos_temporais`, com a mesma estimativa, a mesma máquina de reamostragem
e a mesma semente. Cenário SINTETICO, só CALIBRACAO; nenhum resultado empírico.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_avaliacao import run_agregados
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.experiment import BootstrapSpec, Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.evaluation.bootstrap import intervalo_razao
from sustemporal.evaluation.metrics import evaluate_runs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport
    from sustemporal.contracts.evaluation import ValorMetrica

BLOCOS = "sensibilidade_blocos_temporais"
METRICAS = (
    "cobertura_rejeicoes",
    "cobertura_verificabilidade",
    "precisao_alertas",
    "falsos_alertas_aprovacoes",
)
BLOCO_A, BLOCO_B = "202301", "202302"
ALERTA, SEM_ALERTA, ABSTENCAO = "ALERTA", "SEM_VIOLACAO_VERIFICADA", "ABSTENCAO"
SPEC = BootstrapSpec(reamostragens=1000, semente=2027)

# Por (método, métrica): o valor e o intervalo por estabelecimento e por blocos, contas à mão.
# No bloco A o M_TEMP sinaliza só as rejeições e no B se abstém; o B_ATEND sinaliza só as
# rejeições no A e todos os registros no B. Cada estabelecimento tem os mesmos registros nos dois
# blocos, então a razão por estabelecimento não varia (intervalo de um ponto só), e a por blocos
# varia entre os extremos de cada bloco (cada extremo sai em 1/4 das réplicas de dois blocos).
ESPERADO: dict[tuple[str, str], tuple[str, tuple[str, str] | None, tuple[str, str]]] = {
    ("M_TEMP", "cobertura_rejeicoes"): ("0.5", ("0.5", "0.5"), ("0", "1")),
    ("M_TEMP", "cobertura_verificabilidade"): ("0.5", ("0.5", "0.5"), ("0", "1")),
    ("M_TEMP", "precisao_alertas"): ("1", ("1", "1"), ("1", "1")),
    ("M_TEMP", "falsos_alertas_aprovacoes"): ("0", ("0", "0"), ("0", "0")),
    ("B_ATEND", "cobertura_rejeicoes"): ("1", ("1", "1"), ("1", "1")),
    ("B_ATEND", "cobertura_verificabilidade"): ("1", ("1", "1"), ("1", "1")),
    ("B_ATEND", "precisao_alertas"): ("0.470588", None, ("0.307692", "1")),
    ("B_ATEND", "falsos_alertas_aprovacoes"): ("0.5", ("0.5", "0.5"), ("0", "1")),
}


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    competencias = ("202201", BLOCO_A, BLOCO_B, "202401")
    return cenario_baseline(tmp_path_factory.mktemp("cenario"), competencias=competencias)


def _m_temp(competencia: str, rotulo: str) -> str:
    if competencia != BLOCO_A:
        return ABSTENCAO
    return ALERTA if rotulo == "NAO_APROVADO" else SEM_ALERTA


def _b_atend(competencia: str, rotulo: str) -> str:
    if competencia != BLOCO_A:
        return ALERTA
    return ALERTA if rotulo == "NAO_APROVADO" else SEM_ALERTA


def _resultados(cenario: Cenario, regra: Callable[[str, str], str]) -> dict[str, str]:
    return {
        linha.row_id: regra(
            linha.competencia_processamento or "", cenario.rotulo_por_row[linha.row_id]
        )
        for linha in cenario.linhas
        if linha.competencia_processamento in {BLOCO_A, BLOCO_B}
    }


def _avaliar(cenario: Cenario, raiz: Path, spec: BootstrapSpec = SPEC) -> EvaluationReport:
    runs = [
        run_agregados(MetodoId.M_TEMP, _resultados(cenario, _m_temp), raiz / "runs"),
        run_agregados(MetodoId.B_ATEND, _resultados(cenario, _b_atend), raiz / "runs"),
    ]
    assert cenario.split.rotulos_por_particao is not None
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    return evaluate_runs(runs, rotulos, cenario.split, raiz / "avaliacao", bootstrap=spec)


def _por_chave(relatorio: EvaluationReport) -> dict[tuple[str, str], ValorMetrica]:
    return {(m.nome, m.estrato): m for m in relatorio.metricas}


def test_relatorio_traz_os_dois_intervalos_para_cada_metrica_com_intervalo(
    tmp_path: Path, cenario: Cenario
) -> None:
    metricas = _por_chave(_avaliar(cenario, tmp_path))
    for metodo in ("M_TEMP", "B_ATEND"):
        for nome in METRICAS:
            chave = f"{metodo}.{nome}"
            assert (chave, "TOTAL") in metricas, chave
            assert (chave, BLOCOS) in metricas, chave
            total, blocos = metricas[(chave, "TOTAL")], metricas[(chave, BLOCOS)]
            assert total.ic is not None, chave
            assert blocos.ic is not None, chave
            estimativa = (total.numerador, total.denominador, total.valor)
            assert (blocos.numerador, blocos.denominador, blocos.valor) == estimativa, chave


def test_so_as_metricas_com_intervalo_e_as_diferencas_levam_o_estrato_de_blocos(
    tmp_path: Path, cenario: Cenario
) -> None:
    relatorio = _avaliar(cenario, tmp_path)
    com_blocos = sorted(m.nome for m in relatorio.metricas if m.estrato == BLOCOS)
    esperado = sorted(
        [f"{metodo}.{nome}" for metodo in ("M_TEMP", "B_ATEND") for nome in METRICAS]
        + ["diferenca.M_TEMP_x_B_ATEND.cobertura_rejeicoes"]
    )
    assert com_blocos == esperado


@pytest.mark.parametrize(("metodo", "nome"), sorted(ESPERADO))
def test_intervalo_por_blocos_sorteia_competencias_inteiras_contra_contas_a_mao(
    tmp_path: Path, cenario: Cenario, metodo: str, nome: str
) -> None:
    valor, por_estabelecimento, por_blocos = ESPERADO[(metodo, nome)]
    metricas = _por_chave(_avaliar(cenario, tmp_path))
    total, blocos = (
        metricas[(f"{metodo}.{nome}", "TOTAL")],
        metricas.get((f"{metodo}.{nome}", BLOCOS)),
    )
    assert blocos is not None
    assert total.valor == Decimal(valor)
    assert total.ic is not None
    assert blocos.ic is not None
    assert (blocos.ic.inferior, blocos.ic.superior) == tuple(Decimal(x) for x in por_blocos)
    assert blocos.ic.nivel == SPEC.confianca
    if por_estabelecimento is not None:
        esperado = tuple(Decimal(x) for x in por_estabelecimento)
        assert (total.ic.inferior, total.ic.superior) == esperado


def _cobertura_de_rejeicoes_do_m_temp(
    cenario: Cenario,
) -> tuple[list[int], list[int], list[str]]:
    """Numerador, denominador e bloco (competência) de cada registro, feitos à mão."""
    linhas = [
        linha for linha in cenario.linhas if linha.competencia_processamento in {BLOCO_A, BLOCO_B}
    ]
    rotulos = [cenario.rotulo_por_row[linha.row_id] for linha in linhas]
    blocos = [linha.competencia_processamento or "" for linha in linhas]
    dens = [int(rotulo == "NAO_APROVADO") for rotulo in rotulos]
    nums = [
        int(den == 1 and _m_temp(bloco, rotulo) == ALERTA)
        for den, bloco, rotulo in zip(dens, blocos, rotulos, strict=True)
    ]
    return nums, dens, blocos


def _sementes_de_intervalos_diferentes(
    nums: list[int], dens: list[int], blocos: list[str]
) -> list[int]:
    """Duas sementes cujos intervalos por blocos, à confiança de 50%, diferem."""
    vistos: dict[tuple[object, object], int] = {}
    for semente in range(1, 60):
        spec = BootstrapSpec(reamostragens=1000, semente=semente, confianca=Decimal("0.5"))
        ic = intervalo_razao(nums, dens, blocos, spec)
        assert ic is not None
        vistos.setdefault((ic.inferior, ic.superior), semente)
    assert len(vistos) >= 2
    return sorted(vistos.values())[:2]


def test_intervalo_por_blocos_e_a_reamostragem_de_competencias_com_a_semente_da_especificacao(
    tmp_path: Path, cenario: Cenario
) -> None:
    nums, dens, blocos = _cobertura_de_rejeicoes_do_m_temp(cenario)
    obtidos = []
    for semente in _sementes_de_intervalos_diferentes(nums, dens, blocos):
        spec = BootstrapSpec(reamostragens=1000, semente=semente, confianca=Decimal("0.5"))
        relatorio = _avaliar(cenario, tmp_path / f"semente_{semente}", spec)
        metrica = _por_chave(relatorio).get(("M_TEMP.cobertura_rejeicoes", BLOCOS))
        assert metrica is not None
        assert metrica.ic == intervalo_razao(nums, dens, blocos, spec)
        assert (
            _avaliar(cenario, tmp_path / f"repetida_{semente}", spec).metricas == relatorio.metricas
        )
        obtidos.append(metrica.ic)
    assert obtidos[0] != obtidos[1]
