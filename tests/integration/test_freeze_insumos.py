"""Entradas não populacionais das execuções de regras: congeladas e conferidas (T11, SINTETICO).

Uma execução de regras confirmatória com outros auxiliares (CNES, SIGTAP), outras seleções
temporais, outra cobertura ou outro `SnapshotSet` passava desde que citasse a população TESTE
congelada, o que acontece sem má-fé ao reingerir depois de chegar uma versão nova do SIGTAP.
Cenário sintético rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_insumos,
    gravar_runs,
    manifesto_da_cli,
    preparar_cli,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    ESQUEMA_CNES,
    ESQUEMA_COBERTURA,
    ESQUEMA_SELECAO,
    ESQUEMA_SIGTAP,
    POLITICAS_DO_PROTOCOLO,
    Confirmatorio,
    com_conjunto_trocado,
    como_real,
    conjunto_sintetico,
    entrada_da_politica,
    insumos_do_teste,
    montar_confirmatorio,
    snapshots_sinteticos,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.base import conteudo_identidade
from sustemporal.contracts.experiment import FreezeManifest, Particao
from sustemporal.errors import ConfigInvalida, ExitCode, PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import (
    verificar_congelamento_completo,
    verificar_execucao,
)
from sustemporal.evaluation.metrics import evaluate_runs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport, RunResult
    from sustemporal.rules.entrada import EntradaValidacao

OUTRA_VERSAO = "2099-12"
M_TEMP, B_ATEND, B_PROC, B_ML = 0, 1, 2, 3


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _outro_conjunto(esquema: str) -> Callable[[RunResult], RunResult]:
    return lambda run: com_conjunto_trocado(run, esquema, conjunto_sintetico(esquema, OUTRA_VERSAO))


def _sem_cnes(run: RunResult) -> RunResult:
    entradas = tuple(d for d in run.entradas if d.schema_id != ESQUEMA_CNES)
    return run.model_copy(update={"entradas": entradas})


def _com_auxiliar_a_mais(run: RunResult) -> RunResult:
    a_mais = conjunto_sintetico("cnes_estab_cbo.v1", OUTRA_VERSAO)
    return run.model_copy(update={"entradas": (*run.entradas, a_mais)})


def _com_snapshot(snapshot_id: str | None) -> Callable[[RunResult], RunResult]:
    return lambda run: run.model_copy(update={"snapshot_set_id": snapshot_id})


VARIANTES: dict[str, tuple[Callable[[RunResult], RunResult], str]] = {
    "sigtap_de_outra_versao": (_outro_conjunto(ESQUEMA_SIGTAP), "auxiliares"),
    "cnes_de_outra_versao": (_outro_conjunto(ESQUEMA_CNES), "auxiliares"),
    "outra_cobertura": (_outro_conjunto(ESQUEMA_COBERTURA), "auxiliares"),
    "outras_selecoes": (_outro_conjunto(ESQUEMA_SELECAO), "auxiliares"),
    "sem_cnes": (_sem_cnes, "auxiliares"),
    "auxiliar_a_mais": (_com_auxiliar_a_mais, "auxiliares"),
    "outro_snapshot": (_com_snapshot(snapshots_sinteticos(OUTRA_VERSAO).snapshot_id), "snapshots"),
    "sem_snapshot": (_com_snapshot(None), "snapshots"),
}


def _mensagem(run: RunResult, campo: str, conf: Confirmatorio) -> str:
    base = f"run_incompativel_com_congelamento run={run.run_id} campo={campo}"
    return f"^{re.escape(base)} freeze={conf.manifesto.freeze_id}$"


def _ids_nao_populacionais(entrada: EntradaValidacao) -> tuple[str, ...]:
    refs = (*entrada.auxiliares, entrada.selecoes, entrada.cobertura)
    return tuple(sorted(d.dataset_id for d in refs if d is not None))


def _exigir_identidades(manifesto: FreezeManifest, insumos: dict[str, EntradaValidacao]) -> None:
    """O manifesto traz, por política, os ids não populacionais e o `snapshot_id` dos insumos."""
    assert set(insumos) == set(POLITICAS_DO_PROTOCOLO)
    assert manifesto.auxiliares == {p: _ids_nao_populacionais(e) for p, e in insumos.items()}
    assert manifesto.snapshots == {p: e.snapshots.snapshot_id for p, e in insumos.items()}


def _avaliar(conf: Confirmatorio, out: Path, runs: list[RunResult]) -> EvaluationReport:
    return evaluate_runs(
        runs,
        conf.rotulos,
        conf.cenario.split,
        out,
        bootstrap=conf.manifesto.bootstrap,
        congelamento=conf.referencia(),
    )


def test_manifesto_grava_as_identidades_dos_insumos_de_cada_politica(
    cenario: Cenario, confirmatorio: Confirmatorio
) -> None:
    _exigir_identidades(confirmatorio.manifesto, insumos_do_teste(cenario))


def test_execucoes_com_os_insumos_congelados_passam(confirmatorio: Confirmatorio) -> None:
    verificar_congelamento_completo(
        confirmatorio.manifesto, confirmatorio.estado, confirmatorio.runs
    )


@pytest.mark.parametrize("indice", [M_TEMP, B_ATEND, B_PROC], ids=["m_temp", "b_atend", "b_proc"])
@pytest.mark.parametrize("variante", sorted(VARIANTES))
def test_execucao_de_regras_com_insumo_diferente_do_congelado_e_recusada(
    confirmatorio: Confirmatorio, indice: int, variante: str
) -> None:
    alterar, campo = VARIANTES[variante]
    alterada = alterar(confirmatorio.runs[indice])
    runs = [*confirmatorio.runs[:indice], alterada, *confirmatorio.runs[indice + 1 :]]
    with pytest.raises(PortaoRecusado, match=_mensagem(alterada, campo, confirmatorio)):
        verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado, runs)


def test_insumos_de_outra_politica_sao_recusados_nos_dois_campos(
    cenario: Cenario, confirmatorio: Confirmatorio
) -> None:
    de_m_temp = entrada_da_politica(cenario, "M_TEMP_PADRAO")
    assert de_m_temp.selecoes is not None
    run = com_conjunto_trocado(confirmatorio.runs[B_ATEND], ESQUEMA_SELECAO, de_m_temp.selecoes)
    run = run.model_copy(update={"snapshot_set_id": de_m_temp.snapshots.snapshot_id})
    runs = [confirmatorio.runs[M_TEMP], run, *confirmatorio.runs[B_PROC:]]
    mensagem = _mensagem(run, "auxiliares,snapshots", confirmatorio)
    with pytest.raises(PortaoRecusado, match=mensagem):
        verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado, runs)


def test_execucao_com_outro_sigtap_e_recusada_antes_de_ler_dados_e_de_gravar(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    alterada = _outro_conjunto(ESQUEMA_SIGTAP)(confirmatorio.runs[M_TEMP])
    runs = [alterada, *confirmatorio.runs[1:]]
    with pytest.raises(PortaoRecusado, match=_mensagem(alterada, "auxiliares", confirmatorio)):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_baseline_nao_e_conferido_nos_insumos_de_regras(confirmatorio: Confirmatorio) -> None:
    baseline = _com_auxiliar_a_mais(confirmatorio.runs[B_ML])
    baseline = _com_snapshot(snapshots_sinteticos(OUTRA_VERSAO).snapshot_id)(baseline)
    runs = [*confirmatorio.runs[:B_ML], baseline]
    verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado, runs)


def test_manifesto_sem_insumos_recusa_toda_execucao_de_regras(
    tmp_path: Path, cenario: Cenario
) -> None:
    conf = montar_confirmatorio(tmp_path, cenario, insumos={})
    assert conf.manifesto.auxiliares is None
    assert conf.manifesto.snapshots is None
    mensagem = _mensagem(conf.runs[M_TEMP], "auxiliares,snapshots", conf)
    with pytest.raises(PortaoRecusado, match=mensagem):
        verificar_congelamento_completo(conf.manifesto, conf.estado, conf.runs)


def test_politica_sem_insumos_congelados_recusa_so_as_execucoes_dela(
    tmp_path: Path, cenario: Cenario
) -> None:
    insumos = {k: v for k, v in insumos_do_teste(cenario).items() if k != "B_PROC"}
    conf = montar_confirmatorio(tmp_path, cenario, insumos=insumos)
    for run in conf.runs[:B_PROC]:
        verificar_execucao(conf.manifesto, run, config=conf.config)
    mensagem = _mensagem(conf.runs[B_PROC], "auxiliares,snapshots", conf)
    with pytest.raises(PortaoRecusado, match=mensagem):
        verificar_execucao(conf.manifesto, conf.runs[B_PROC], config=conf.config)


def test_manifesto_sem_insumos_nao_leva_os_campos_novos_na_identidade(
    tmp_path: Path, cenario: Cenario
) -> None:
    manifesto = montar_confirmatorio(tmp_path, cenario, insumos={}).manifesto
    identidade = conteudo_identidade(manifesto, excluir={"freeze_id"})
    conteudo = identidade["conteudo"]
    assert isinstance(conteudo, dict)
    assert not {"auxiliares", "snapshots"} & set(conteudo)
    assert manifesto.freeze_id == FreezeManifest.calcular_id(identidade)


def test_congelar_recusa_insumos_de_outra_populacao(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.particoes is not None
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    de_outra = entrada_da_politica(cenario, "B_ATEND").model_copy(update={"dataset": calibracao})
    insumos = {**insumos_do_teste(cenario), "B_ATEND": de_outra}
    with pytest.raises(ConfigInvalida, match="congelamento_insumos_de_outra_populacao") as erro:
        montar_confirmatorio(tmp_path, cenario, insumos=insumos)
    assert "politicas=B_ATEND" in str(erro.value)


def test_cli_congela_as_identidades_dos_insumos_da_convencao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    _exigir_identidades(manifesto_da_cli(tmp_path, freeze), insumos_do_teste(cenario))


def test_cli_freeze_sem_insumos_sai_com_config_invalida_e_nao_congela(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preparar_cli(tmp_path, monkeypatch)
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    pasta = tmp_path / "saidas" / "split" / "insumos"
    assert f"freeze_sem_insumos_das_execucoes pasta={pasta}" in capsys.readouterr().err
    assert not (tmp_path / "frozen").exists()


def test_cli_freeze_recusa_insumo_ilegivel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario = preparar_cli(tmp_path, monkeypatch)
    arquivo = gravar_insumos(tmp_path, cenario) / "B_ATEND.json"
    arquivo.write_text("{", encoding="utf-8")
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert f"freeze_insumos_ilegiveis arquivo={arquivo}" in capsys.readouterr().err
    assert not (tmp_path / "frozen").exists()


def test_cli_freeze_recusa_insumo_de_outra_populacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario = preparar_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    arquivo = gravar_insumos(tmp_path, cenario) / "B_ATEND.json"
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    de_outra = entrada_da_politica(cenario, "B_ATEND").model_copy(update={"dataset": calibracao})
    arquivo.write_text(de_outra.model_dump_json(), encoding="utf-8")
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert "congelamento_insumos_de_outra_populacao politicas=B_ATEND" in capsys.readouterr().err


def test_cli_recusa_o_confirmatorio_com_execucao_de_outro_sigtap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    alterada = _outro_conjunto(ESQUEMA_SIGTAP)(runs[B_ATEND])
    gravar_runs(tmp_path, [r for r in runs if r.run_id != alterada.run_id] + [alterada])
    config = config_confirmatoria_yaml(tmp_path, freeze)
    codigo = executar_cli(["evaluate", "--config", str(config), "--freeze", freeze])
    assert codigo == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert f"run_incompativel_com_congelamento run={alterada.run_id} campo=auxiliares" in erro
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
