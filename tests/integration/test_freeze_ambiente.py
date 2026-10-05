"""Ambiente da execução e do avaliador conferidos contra o congelado (T11, SINTETICO).

Cenário sintético rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
O ambiente é o que o `RunResult` e o `FreezeManifest` registram (Python e dependências); a
plataforma é informativa. Nenhum resultado empírico.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, run_agregados
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
    manifesto_da_cli,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    CONFIG_PROTOCOLO,
    MUTACOES_DO_AMBIENTE,
    Confirmatorio,
    config_confirmatoria,
    montar_confirmatorio,
    split_como_real,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode, PortaoRecusado
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs

if TYPE_CHECKING:
    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport, RunResult

M_TEMP, B_ML = 0, 3
CAMPOS = sorted(MUTACOES_DO_AMBIENTE)


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _avaliar(
    conf: Confirmatorio, out: Path, runs: list[RunResult] | None = None, **trocas: object
) -> EvaluationReport:
    return evaluate_runs(
        conf.runs if runs is None else runs,
        conf.rotulos,
        conf.cenario.split,
        out,
        bootstrap=conf.manifesto.bootstrap,
        congelamento=conf.referencia(**trocas),
    )


def _com_a_execucao_trocada(conf: Confirmatorio, indice: int, **trocas: object) -> list[RunResult]:
    trocada = conf.runs[indice].model_copy(update=trocas)
    return [*conf.runs[:indice], trocada, *conf.runs[indice + 1 :]]


@pytest.mark.parametrize("indice", [M_TEMP, B_ML], ids=["motor", "baseline"])
@pytest.mark.parametrize("campo", CAMPOS)
def test_confirmatorio_recusa_execucao_de_outro_ambiente(
    tmp_path: Path, confirmatorio: Confirmatorio, campo: str, indice: int
) -> None:
    alvo = confirmatorio.runs[indice]
    outro = MUTACOES_DO_AMBIENTE[campo](alvo.ambiente)
    runs = _com_a_execucao_trocada(confirmatorio, indice, ambiente=outro)
    base = f"run_incompativel_com_congelamento run={alvo.run_id} campo=ambiente"
    mensagem = f"^{re.escape(base)} freeze={confirmatorio.manifesto.freeze_id}$"
    with pytest.raises(PortaoRecusado, match=mensagem):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_execucao_que_so_difere_na_plataforma_e_avaliada(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    alvo = confirmatorio.runs[M_TEMP]
    outra = alvo.ambiente.model_copy(update={"plataforma": "Windows-10-10.0.19045"})
    runs = _com_a_execucao_trocada(confirmatorio, M_TEMP, ambiente=outra)
    relatorio = _avaliar(confirmatorio, tmp_path / "av", runs)
    assert len(relatorio.runs) == len(runs)


@pytest.mark.parametrize("campo", CAMPOS)
def test_confirmatorio_recusa_quando_o_ambiente_do_avaliador_diverge(
    tmp_path: Path, confirmatorio: Confirmatorio, campo: str
) -> None:
    estado = confirmatorio.estado_com(
        ambiente=MUTACOES_DO_AMBIENTE[campo](confirmatorio.estado.ambiente)
    )
    base = f"freeze_incompativel campos=ambiente freeze={confirmatorio.manifesto.freeze_id}"
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(base)}$"):
        _avaliar(confirmatorio, tmp_path / "av", estado=estado)
    assert not (tmp_path / "av").exists()


def test_baseline_confirmatorio_em_outro_ambiente_e_recusado_antes_de_gerar_a_execucao(
    tmp_path: Path, cenario: Cenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sustemporal.evaluation.baselines.versao_codigo", lambda _: CODIGO_LIMPO)
    runtime = {"dir_congelamentos": str(tmp_path / "frozen")}
    real = split_como_real(cenario.split)
    protocolo = RunConfig.model_validate({**CONFIG_PROTOCOLO, "runtime": runtime})
    conf = montar_confirmatorio(tmp_path, cenario, config=protocolo, split=real)
    config = config_confirmatoria(conf.manifesto.freeze_id, runtime=runtime)
    outro = MUTACOES_DO_AMBIENTE["python"](conf.manifesto.ambiente)
    monkeypatch.setattr("sustemporal.evaluation.baselines.ambiente", lambda _raiz: outro)
    base = f"freeze_incompativel campos=ambiente freeze={conf.manifesto.freeze_id}"
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(base)}$"):
        fit_baseline(
            real,
            FEATURES_PADRAO,
            config,
            tmp_path / "bml",
            decisoes=conf.decisoes,
            codigo=CODIGO_LIMPO,
        )
    assert not (tmp_path / "bml").exists()


def test_confirmatorio_recusa_bootstrap_diferente_do_congelado(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    outro = confirmatorio.manifesto.bootstrap.model_copy(update={"reamostragens": 7})
    base = (
        "avaliacao_confirmatoria_com_bootstrap_diferente_do_congelado "
        f"freeze={confirmatorio.manifesto.freeze_id}"
    )
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(base)}$"):
        evaluate_runs(
            confirmatorio.runs,
            confirmatorio.rotulos,
            confirmatorio.cenario.split,
            tmp_path / "av",
            bootstrap=outro,
            congelamento=confirmatorio.referencia(),
        )
    assert not (tmp_path / "av").exists()


def test_confirmatorio_sem_bootstrap_usa_o_do_manifesto(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    relatorio = evaluate_runs(
        confirmatorio.runs,
        confirmatorio.rotulos,
        confirmatorio.cenario.split,
        tmp_path / "av",
        congelamento=confirmatorio.referencia(),
    )
    reamostragens = confirmatorio.manifesto.bootstrap.reamostragens
    assert f"reamostragens={reamostragens}" in relatorio.notas


def test_bootstrap_diferente_e_recusado_antes_de_ler_qualquer_dado(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path / "cenario")
    conf = montar_confirmatorio(tmp_path, cenario)
    assert cenario.split.particoes is not None
    saidas = [dataset for run in conf.runs for dataset in run.saidas]
    for dataset in (cenario.split.particoes[Particao.TESTE], conf.rotulos, *saidas):
        Path(dataset.caminho).unlink()
    outro = conf.manifesto.bootstrap.model_copy(update={"reamostragens": 7})
    with pytest.raises(PortaoRecusado, match="bootstrap_diferente_do_congelado"):
        evaluate_runs(
            conf.runs,
            conf.rotulos,
            cenario.split,
            tmp_path / "av",
            bootstrap=outro,
            congelamento=conf.referencia(),
        )


def test_exploratorio_usa_o_bootstrap_recebido_mesmo_com_o_manifesto_na_referencia(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    split = confirmatorio.cenario.split
    assert split.rotulos_por_particao is not None
    calibracao = [
        lp for lp in confirmatorio.cenario.linhas if lp.competencia_processamento == "202301"
    ]
    resultados = {lp.row_id: "ALERTA" for lp in calibracao}
    run = run_agregados(MetodoId.M_TEMP, resultados, tmp_path / "runs")
    outro = confirmatorio.manifesto.bootstrap.model_copy(update={"reamostragens": 7})
    referencia = ReferenciaCongelamento(
        confirmatorio.manifesto.freeze_id, manifesto=confirmatorio.manifesto
    )
    relatorio = evaluate_runs(
        [run],
        split.rotulos_por_particao[Particao.CALIBRACAO],
        split,
        tmp_path / "av",
        bootstrap=outro,
        congelamento=referencia,
    )
    assert "reamostragens=7" in relatorio.notas


def test_cli_recusa_o_confirmatorio_com_execucao_de_outro_ambiente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    alvo = runs[M_TEMP]
    runs[M_TEMP] = alvo.model_copy(
        update={"ambiente": MUTACOES_DO_AMBIENTE["python"](alvo.ambiente)}
    )
    gravar_runs(tmp_path, runs)
    config = config_confirmatoria_yaml(tmp_path, freeze)
    assert executar_cli(["evaluate", "--config", str(config), "--freeze", freeze]) == (
        ExitCode.PORTAO_RECUSADO
    )
    esperado = f"run_incompativel_com_congelamento run={alvo.run_id} campo=ambiente"
    assert esperado in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()


def test_cli_recusa_o_confirmatorio_quando_o_ambiente_do_avaliador_diverge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    gravar_runs(tmp_path, runs_da_cli(tmp_path, cenario, freeze))
    outro = MUTACOES_DO_AMBIENTE["pacotes"](manifesto_da_cli(tmp_path, freeze).ambiente)
    monkeypatch.setattr("sustemporal.evaluation.cli.ambiente", lambda _raiz: outro)
    config = config_confirmatoria_yaml(tmp_path, freeze)
    assert executar_cli(["evaluate", "--config", str(config), "--freeze", freeze]) == (
        ExitCode.PORTAO_RECUSADO
    )
    assert f"freeze_incompativel campos=ambiente freeze={freeze}" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()


def _gravar_execucao_exploratoria(raiz: Path, cenario: Cenario) -> None:
    """Uma execução do M_TEMP sobre a CALIBRACAO, rotulada REAL como as entradas da CLI."""
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    resultados = {lp.row_id: "ALERTA" if lp.cnes == "0000000" else "ABSTENCAO" for lp in calibracao}
    run = run_agregados(
        MetodoId.M_TEMP, resultados, raiz / "saidas" / "runs", origem=OrigemDados.REAL
    )
    gravar_runs(raiz, [run])


def test_cli_exploratorio_so_registra_o_ambiente_diferente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    _gravar_execucao_exploratoria(tmp_path, cenario)
    outro = MUTACOES_DO_AMBIENTE["python"](manifesto_da_cli(tmp_path, freeze).ambiente)
    monkeypatch.setattr("sustemporal.evaluation.cli.ambiente", lambda _raiz: outro)
    argumentos = ["evaluate", "--config", str(config_yaml(tmp_path)), "--freeze", freeze]
    assert executar_cli([*argumentos, "--exploratory"]) == ExitCode.OK
    aviso = "evaluate_exploratorio_divergente_do_freeze erro=freeze_incompativel campos=ambiente"
    assert aviso in capsys.readouterr().err
