"""Rodada registrada do congelamento como o registro a descreve (T14); SINTETICO.

O relatório lido em `avaliacao/<freeze_id>/<report_id>.json` só vale se bate com a entrada do
registro de rodadas (`report_id`, `freeze_id`, modo, origem dos dados, lista de execuções e a
contagem das métricas); um relatório válido que não é o registrado é original indisponível.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.evaluation import EvaluationReport, ValorMetrica
from sustemporal.contracts.experiment import ModoExecucao
from sustemporal.evaluation.cli import REGISTRO
from sustemporal.evaluation.freeze_registro import registrar_execucao
from sustemporal.reporting.reproduce_original import (
    Original,
    campos_que_nao_conferem,
    ler_original,
)

if TYPE_CHECKING:
    from pathlib import Path

FREEZE = "frz_" + "a" * 64
OUTRO_FREEZE = "frz_" + "b" * 64
REPORT = "rep_" + "c" * 64
G2 = "experiments/decisions/g2.yaml"
INSTANTE = datetime(2026, 1, 1, tzinfo=UTC)


def _metrica(nome: str, *, nula: bool = False) -> ValorMetrica:
    if nula:
        return ValorMetrica(nome=nome, numerador=0, denominador=0)
    return ValorMetrica(nome=nome, numerador=1, denominador=2, valor=Decimal("0.5"))


def _relatorio(**trocas: Any) -> EvaluationReport:
    campos: dict[str, Any] = {
        "report_id": REPORT,
        "modo": ModoExecucao.EXPLORATORIO,
        "origem_dados": OrigemDados.SINTETICO,
        "freeze_id": FREEZE,
        "runs": ("run_a", "run_b"),
        "metricas": (_metrica("m1"), _metrica("m2", nula=True), _metrica("m3")),
        "notas": ("particao=CALIBRACAO",),
        "criado_em": INSTANTE,
        **trocas,
    }
    return EvaluationReport(**campos)


def _config(tmp_path: Path) -> RunConfig:
    runtime = {
        "raiz_saidas": str(tmp_path / "saidas"),
        "dir_congelamentos": str(tmp_path / "congelamentos"),
    }
    return RunConfig.model_validate({"versao": "1", "runtime": runtime})


def _registrar(tmp_path: Path, registrada: EvaluationReport) -> None:
    registrar_execucao(tmp_path / "congelamentos" / REGISTRO, registrada)


def _gravar(tmp_path: Path, relatorio: EvaluationReport, nome: str = REPORT) -> None:
    pasta = tmp_path / "saidas" / "avaliacao" / FREEZE
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome}.json").write_text(relatorio.model_dump_json(), encoding="utf-8")


def _lido(tmp_path: Path, relatorio: EvaluationReport) -> Original:
    """Registra `_relatorio()` e deixa em seu lugar o `relatorio` que o arquivo traz."""
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, relatorio)
    return ler_original(_config(tmp_path), FREEZE)


def test_relatorio_que_bate_com_a_entrada_do_registro_e_o_original(tmp_path: Path) -> None:
    original = _lido(tmp_path, _relatorio())
    assert original.relatorio == _relatorio()
    assert original.observacoes == ()


def test_sem_registro_de_rodadas_nao_ha_original(tmp_path: Path) -> None:
    _gravar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, dict(original.execucoes), original.observacoes) == (None, {}, ())


def test_rodada_de_outro_congelamento_ou_modo_nao_e_a_deste(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio(freeze_id=OUTRO_FREEZE))
    _gravar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert original.relatorio is None
    assert original.observacoes == ()


def test_relatorio_ausente_nao_e_relatorio_diferente_do_registrado(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, original.observacoes) == (None, ())


TROCAS = {
    "report_id": {"report_id": "rep_" + "d" * 64},
    "freeze_id": {"freeze_id": OUTRO_FREEZE},
    "modo": {
        "modo": ModoExecucao.CONFIRMATORIO,
        "origem_dados": OrigemDados.REAL,
        "decisao_g2": G2,
    },
    "origem_dados": {"origem_dados": OrigemDados.REAL},
    "runs": {"runs": ("run_a", "run_c")},
    "metricas": {"metricas": (_metrica("m1"), _metrica("m2", nula=True))},
    "metricas_nulas": {"metricas": (_metrica("m1"), _metrica("m2"), _metrica("m3"))},
}


@pytest.mark.parametrize("campo", list(TROCAS))
def test_relatorio_que_nao_e_o_registrado_vira_original_indisponivel(
    tmp_path: Path, campo: str
) -> None:
    original = _lido(tmp_path, _relatorio(**TROCAS[campo]))
    assert original.relatorio is None
    esperado = {"modo": "modo,origem_dados"}.get(campo, campo)
    assert original.observacoes == (
        f"relatorio_original_nao_confere_com_o_registro campos={esperado}",
    )


def test_execucoes_em_outra_ordem_nao_conferem(tmp_path: Path) -> None:
    original = _lido(tmp_path, _relatorio(runs=("run_b", "run_a")))
    assert original.relatorio is None
    assert original.observacoes[0].endswith("campos=runs")


def test_varios_campos_diferentes_saem_todos_na_ordem_do_registro(tmp_path: Path) -> None:
    trocas = {**TROCAS["freeze_id"], **TROCAS["runs"], **TROCAS["origem_dados"]}
    original = _lido(tmp_path, _relatorio(**trocas))
    assert original.observacoes == (
        "relatorio_original_nao_confere_com_o_registro campos=freeze_id,origem_dados,runs",
    )


def test_campos_que_nao_conferem_so_olha_o_que_o_registro_traz() -> None:
    relatorio = _relatorio()
    entrada: dict[str, Any] = {
        "report_id": REPORT,
        "freeze_id": FREEZE,
        "modo": "EXPLORATORIO",
        "origem_dados": "SINTETICO",
        "runs": ["run_a", "run_b"],
        "metricas": 3,
        "metricas_nulas": 1,
    }
    assert campos_que_nao_conferem(relatorio, entrada) == []
    assert campos_que_nao_conferem(relatorio, {**entrada, "metricas_nulas": 0}) == [
        "metricas_nulas"
    ]
    assert campos_que_nao_conferem(relatorio, {**entrada, "runs": ["run_a"]}) == ["runs"]


def test_entrada_sem_um_campo_do_registro_nao_confere_com_o_relatorio() -> None:
    entrada: dict[str, Any] = {"report_id": REPORT}
    campos = campos_que_nao_conferem(_relatorio(), entrada)
    assert campos == ["freeze_id", "modo", "origem_dados", "runs", "metricas", "metricas_nulas"]
