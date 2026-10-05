"""`evaluate` só avalia as execuções do protocolo pedido (T11, SINTETICO).

A pasta `runs/` pode trazer execuções de outras configs, de outros splits, de outro modo ou de
outro congelamento, e nomes de método diferentes não disparam a guarda de método repetido.
Cenário sintético rotulado REAL só nos contratos; decisões G0 só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.fixtures.protocolo_avaliacao import run_agregados
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
    como_real,
    run_compativel,
    sia_pa_desconhecido,
)

from sustemporal.config import load_config
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import ModoExecucao, Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import DatasetRef, RunResult

OUTRA_CONFIG = "1" * 64
OUTRO_FREEZE = f"frz_{'1' * 64}"
IGNORADA = "evaluate_execucao_ignorada"


def _execucao(
    cenario: Cenario,
    raiz: Path,
    metodo: MetodoId,
    config_hash: str,
    entradas: tuple[DatasetRef, ...],
    **campos: Any,
) -> RunResult:
    """Execução do método sobre a CALIBRACAO, com a config e as entradas dadas (exploratória)."""
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    resultados = {lp.row_id: "ALERTA" if lp.cnes == "0000000" else "ABSTENCAO" for lp in calibracao}
    return run_agregados(
        metodo,
        resultados,
        raiz / "saidas" / "runs",
        origem=OrigemDados.REAL,
        config_hash=config_hash,
        entradas=entradas,
        **campos,
    )


def _avaliar_exploratorio(raiz: Path, freeze: str) -> int:
    argumentos = ["evaluate", "--config", str(config_yaml(raiz)), "--freeze", freeze]
    return executar_cli([*argumentos, "--exploratory"])


def _avaliar_confirmatorio(raiz: Path, freeze: str) -> int:
    config = config_confirmatoria_yaml(raiz, freeze)
    return executar_cli(["evaluate", "--config", str(config), "--freeze", freeze])


def test_cli_exploratorio_so_avalia_execucoes_da_mesma_config_e_das_entradas_do_congelamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    config_hash = load_config(config_yaml(tmp_path)).config_hash
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    propria = _execucao(cenario, tmp_path, MetodoId.M_TEMP, config_hash, (calibracao,))
    de_outra_config = _execucao(cenario, tmp_path, MetodoId.B_ATEND, OUTRA_CONFIG, (calibracao,))
    desconhecida = (sia_pa_desconhecido(tmp_path),)
    de_outro_split = _execucao(cenario, tmp_path, MetodoId.B_PROC, config_hash, desconhecida)
    sem_entradas = _execucao(cenario, tmp_path, MetodoId.B_ML, config_hash, ())
    gravar_runs(tmp_path, [propria, de_outra_config, de_outro_split, sem_entradas])
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert entrada["runs"] == [propria.run_id]
    erro = capsys.readouterr().err
    for ignorada in (de_outra_config, de_outro_split, sem_entradas):
        assert f"{IGNORADA} run={ignorada.run_id} modo=EXPLORATORIO" in erro
    assert f"{IGNORADA} run={propria.run_id}" not in erro


def test_cli_exploratorio_ignora_outro_modo_e_entradas_so_em_parte_do_congelamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    config_hash = load_config(config_yaml(tmp_path)).config_hash
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    propria = _execucao(cenario, tmp_path, MetodoId.M_TEMP, config_hash, (calibracao,))
    confirmatoria = _execucao(
        cenario,
        tmp_path,
        MetodoId.B_ATEND,
        config_hash,
        (calibracao,),
        modo=ModoExecucao.CONFIRMATORIO,
        freeze_id=freeze,
    )
    misturadas = (calibracao, sia_pa_desconhecido(tmp_path))
    em_parte = _execucao(cenario, tmp_path, MetodoId.B_PROC, config_hash, misturadas)
    gravar_runs(tmp_path, [propria, confirmatoria, em_parte])
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert entrada["runs"] == [propria.run_id]
    erro = capsys.readouterr().err
    assert f"{IGNORADA} run={confirmatoria.run_id} modo=CONFIRMATORIO" in erro
    assert f"{IGNORADA} run={em_parte.run_id} modo=EXPLORATORIO" in erro


def test_cli_exploratorio_com_so_execucoes_de_outro_protocolo_nao_registra_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    de_outra_config = _execucao(cenario, tmp_path, MetodoId.M_TEMP, OUTRA_CONFIG, (calibracao,))
    gravar_runs(tmp_path, [de_outra_config])
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.CONFIG_INVALIDA
    pasta = tmp_path / "saidas" / "runs"
    assert f"avaliacao_sem_execucoes pasta={pasta} modo=EXPLORATORIO" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()


def test_cli_confirmatorio_so_avalia_as_execucoes_confirmatorias_do_congelamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    config = load_config(config_confirmatoria_yaml(tmp_path, freeze))
    manifesto = manifesto_da_cli(tmp_path, freeze)
    saida = tmp_path / "saidas" / "runs"
    outra = run_compativel(cenario, manifesto, config, saida, MetodoId.B_PROC, uniforme="ALERTA")
    de_outro_freeze = outra.model_copy(update={"freeze_id": OUTRO_FREEZE})
    exploratoria = _execucao(
        cenario, tmp_path, MetodoId.CONTROLE_TRIVIAL, config.config_hash, (), freeze_id=freeze
    )
    gravar_runs(tmp_path, [*runs, de_outro_freeze, exploratoria])
    assert _avaliar_confirmatorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert sorted(entrada["runs"]) == sorted(run.run_id for run in runs)
    erro = capsys.readouterr().err
    assert f"{IGNORADA} run={de_outro_freeze.run_id} modo=CONFIRMATORIO" in erro
    assert f"{IGNORADA} run={exploratoria.run_id} modo=EXPLORATORIO" in erro


def test_cli_confirmatorio_sem_execucao_do_congelamento_sai_com_config_invalida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    assert _avaliar_confirmatorio(tmp_path, freeze) == ExitCode.CONFIG_INVALIDA
    pasta = tmp_path / "saidas" / "runs"
    assert f"avaliacao_sem_execucoes pasta={pasta} modo=CONFIRMATORIO" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
