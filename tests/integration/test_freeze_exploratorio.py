"""`evaluate --exploratory` só avalia as execuções do protocolo pedido (T11, SINTETICO).

A pasta `runs/` pode trazer execuções exploratórias de outras configs ou de outros splits, e
nomes de método diferentes não disparam a guarda de método repetido. Cenário sintético rotulado
REAL só nos contratos; decisões G0 só em diretórios temporários. Nenhum resultado empírico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.fixtures.protocolo_avaliacao import run_agregados
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
)
from tests.fixtures.protocolo_confirmatorio import como_real, sia_pa_desconhecido

from sustemporal.config import load_config
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import DatasetRef, RunResult

OUTRA_CONFIG = "1" * 64


def _execucao(
    cenario: Cenario,
    raiz: Path,
    metodo: MetodoId,
    config_hash: str,
    entradas: tuple[DatasetRef, ...],
) -> RunResult:
    """Execução exploratória do método sobre a CALIBRACAO, com a config e as entradas dadas."""
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    resultados = {lp.row_id: "ALERTA" if lp.cnes == "0000000" else "ABSTENCAO" for lp in calibracao}
    return run_agregados(
        metodo,
        resultados,
        raiz / "saidas" / "runs",
        origem=OrigemDados.REAL,
        config_hash=config_hash,
        entradas=entradas,
    )


def _avaliar_exploratorio(raiz: Path, freeze: str) -> int:
    argumentos = ["evaluate", "--config", str(config_yaml(raiz)), "--freeze", freeze]
    return executar_cli([*argumentos, "--exploratory"])


def test_cli_exploratorio_so_avalia_execucoes_da_mesma_config_e_das_entradas_do_congelamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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


def test_cli_exploratorio_com_so_execucoes_de_outro_protocolo_nao_registra_nada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    de_outra_config = _execucao(cenario, tmp_path, MetodoId.M_TEMP, OUTRA_CONFIG, (calibracao,))
    gravar_runs(tmp_path, [de_outra_config])
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.CONFIG_INVALIDA
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
