"""CLI `freeze` e `evaluate --freeze` com execuções, G2 e manifesto (T11, SINTETICO).

Cenário sintético rotulado REAL só nos contratos; decisões só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao, relogio
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
    manifesto_da_cli,
    nome_do_arquivo_da_execucao,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import run_compativel
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.cli import main
from sustemporal.config import load_config
from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro, registrar_execucao
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import RuleSpec, RunResult

OUTRO_CODIGO = CODIGO_LIMPO.model_copy(update={"commit": "b" * 40})
M_TEMP = 0


def test_cli_congela_regras_e_politicas_e_avalia_o_confirmatorio_compativel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    manifesto = manifesto_da_cli(tmp_path, freeze)
    assert manifesto.catalogo_regras_sha256 == catalogo_sha256(carregar_regras())
    assert manifesto.politicas_sha256 is not None
    assert set(manifesto.politicas_sha256) == {
        "B_ATEND",
        "B_PROC",
        "M_TEMP_PADRAO",
        "b_atend_exploratoria",
        "b_proc_exploratoria",
    }
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    config = config_confirmatoria_yaml(tmp_path, freeze)
    assert main(["evaluate", "--config", str(config), "--freeze", freeze]) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert (entrada["modo"], entrada["freeze_id"]) == ("CONFIRMATORIO", freeze)
    assert len(entrada["runs"]) == len(runs)


def test_cli_avalia_execucoes_do_motor_gravadas_como_run_result_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    pasta = tmp_path / "saidas" / "runs"
    gravados = {arquivo.parent.name: arquivo.name for arquivo in pasta.glob("*/*.json")}
    assert gravados == {run.run_id: nome_do_arquivo_da_execucao(run) for run in runs}
    assert set(gravados.values()) == {"run.json", "run_result.json"}
    config = config_confirmatoria_yaml(tmp_path, freeze)
    assert main(["evaluate", "--config", str(config), "--freeze", freeze]) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert sorted(entrada["runs"]) == sorted(run.run_id for run in runs)


def test_cli_recusa_execucao_com_run_json_e_run_result_json_no_mesmo_diretorio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    pasta = tmp_path / "saidas" / "runs" / runs[M_TEMP].run_id
    (pasta / "run.json").write_text(runs[M_TEMP].model_dump_json(), encoding="utf-8")
    config = config_confirmatoria_yaml(tmp_path, freeze)
    codigo = main(["evaluate", "--config", str(config), "--freeze", freeze])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert f"execucao_ambigua pasta={pasta} arquivos=run.json,run_result.json" in (
        capsys.readouterr().err
    )
    assert not (tmp_path / "frozen" / REGISTRO).exists()


def test_cli_recusa_o_confirmatorio_sem_execucao_de_b_proc_e_nao_registra_rodada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    b_proc = [run for run in runs if run.metodo is MetodoId.B_PROC]
    gravar_runs(tmp_path, [run for run in runs if run not in b_proc])
    config = config_confirmatoria_yaml(tmp_path, freeze)
    argumentos = ["evaluate", "--config", str(config), "--freeze", freeze]
    assert main(argumentos) == ExitCode.PORTAO_RECUSADO
    esperado = "avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias metodos=B_PROC"
    assert esperado in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
    gravar_runs(tmp_path, b_proc)
    assert main(argumentos) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert len(entrada["runs"]) == len(runs)


def test_cli_freeze_com_catalogo_de_regras_ilegivel_sai_como_config_invalida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario_baseline(tmp_path / "saidas")
    monkeypatch.chdir(tmp_path)
    escrever_decisao(tmp_path / "experiments" / "decisions", "G0", "CONTINUAR")

    def catalogo_ilegivel() -> list[RuleSpec]:
        raise FileNotFoundError("catalog/familias.yaml")

    monkeypatch.setattr("sustemporal.evaluation.cli.carregar_regras", catalogo_ilegivel)
    codigo = main(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert not (tmp_path / "frozen").exists()


def test_cli_recusa_o_confirmatorio_com_execucao_de_outro_codigo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    runs[M_TEMP] = runs[M_TEMP].model_copy(update={"codigo": OUTRO_CODIGO})
    gravar_runs(tmp_path, runs)
    config = config_confirmatoria_yaml(tmp_path, freeze)
    codigo = main(["evaluate", "--config", str(config), "--freeze", freeze])
    assert codigo == ExitCode.PORTAO_RECUSADO
    esperado = f"run_incompativel_com_congelamento run={runs[M_TEMP].run_id} campo=codigo"
    assert esperado in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()


@dataclass(frozen=True)
class PrimeiraRodada:
    """Protocolo congelado, rodada confirmatória já registrada e as execuções avaliadas."""

    cenario: Cenario
    argumentos: list[str]
    freeze: str
    report_id: str
    runs: list[RunResult]


def _primeira_rodada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PrimeiraRodada:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    config = config_confirmatoria_yaml(tmp_path, freeze)
    argumentos = ["evaluate", "--config", str(config), "--freeze", freeze]
    assert executar_cli(argumentos) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    return PrimeiraRodada(cenario, argumentos, freeze, entrada["report_id"], runs)


def _trocar_b_proc(tmp_path: Path, rodada: PrimeiraRodada) -> RunResult:
    """Substitui a execução do B_PROC por outra com resultado diferente (outro `run_id`)."""
    (antiga,) = [run for run in rodada.runs if run.metodo is MetodoId.B_PROC]
    config = load_config(config_confirmatoria_yaml(tmp_path, rodada.freeze))
    manifesto = manifesto_da_cli(tmp_path, rodada.freeze)
    saidas = tmp_path / "saidas" / "runs"
    corrigida = run_compativel(
        rodada.cenario, manifesto, config, saidas, MetodoId.B_PROC, uniforme="ALERTA"
    )
    assert corrigida.run_id != antiga.run_id
    shutil.rmtree(saidas / antiga.run_id)
    gravar_runs(tmp_path, [corrigida])
    return corrigida


def test_cli_recusa_a_segunda_rodada_confirmatoria_sem_correcao_declarada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _primeira_rodada(tmp_path, monkeypatch)
    _trocar_b_proc(tmp_path, rodada)
    capsys.readouterr()
    assert executar_cli(rodada.argumentos) == ExitCode.PORTAO_RECUSADO
    assert "reabertura_do_teste_sem_correcao_declarada" in capsys.readouterr().err
    assert len(ler_registro(tmp_path / "frozen" / REGISTRO)) == 1


def test_cli_aceita_a_correcao_declarada_e_registra_a_relacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rodada = _primeira_rodada(tmp_path, monkeypatch)
    corrigida = _trocar_b_proc(tmp_path, rodada)
    declaracao = "bug na leitura do B_PROC corrigido; rodada anterior preservada"
    extra = ["--corrige", rodada.report_id, "--declaracao", declaracao]
    assert executar_cli([*rodada.argumentos, *extra]) == ExitCode.OK
    anterior, correcao = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert anterior["report_id"] == rodada.report_id
    assert correcao["report_id"] != rodada.report_id
    assert (correcao["corrige"], correcao["declaracao"]) == (rodada.report_id, declaracao)
    assert corrigida.run_id in correcao["runs"]
    assert corrigida.run_id not in anterior["runs"]


def test_cli_recusa_correcao_com_so_um_dos_argumentos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _primeira_rodada(tmp_path, monkeypatch)
    _trocar_b_proc(tmp_path, rodada)
    for extra in (["--corrige", rodada.report_id], ["--declaracao", "bug"]):
        capsys.readouterr()
        assert executar_cli([*rodada.argumentos, *extra]) == ExitCode.CONFIG_INVALIDA
        assert "correcao_exige_corrige_e_declaracao" in capsys.readouterr().err
    assert len(ler_registro(tmp_path / "frozen" / REGISTRO)) == 1


def _registrar_confirmatorio_de_outro_freeze(tmp_path: Path) -> str:
    outro = EvaluationReport.model_validate(
        {
            "report_id": "rep_de_outro_freeze",
            "modo": "CONFIRMATORIO",
            "origem_dados": "REAL",
            "freeze_id": f"frz_{'9' * 64}",
            "decisao_g2": "experiments/decisions/g2_teste.yaml",
            "criado_em": "2026-01-01T00:00:00Z",
        }
    )
    registrar_execucao(tmp_path / "frozen" / REGISTRO, outro, relogio=relogio)
    return outro.report_id


def test_cli_recusa_correcao_de_alvo_inexistente_ou_de_outro_congelamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rodada = _primeira_rodada(tmp_path, monkeypatch)
    _trocar_b_proc(tmp_path, rodada)
    de_outro_freeze = _registrar_confirmatorio_de_outro_freeze(tmp_path)
    alvos = {
        "rep_inexistente": "correcao_de_execucao_inexistente",
        de_outro_freeze: "correcao_de_outro_congelamento",
    }
    for alvo, motivo in alvos.items():
        capsys.readouterr()
        codigo = executar_cli([*rodada.argumentos, "--corrige", alvo, "--declaracao", "bug"])
        assert codigo == ExitCode.CONFIG_INVALIDA
        assert motivo in capsys.readouterr().err
    assert len(ler_registro(tmp_path / "frozen" / REGISTRO)) == 2


def test_cli_recusa_correcao_na_avaliacao_exploratoria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    argumentos = ["evaluate", "--config", str(config_yaml(tmp_path)), "--freeze", freeze]
    capsys.readouterr()
    extra = ["--exploratory", "--corrige", "rep_x", "--declaracao", "x"]
    assert executar_cli([*argumentos, *extra]) == ExitCode.CONFIG_INVALIDA
    assert "correcao_so_no_confirmatorio" in capsys.readouterr().err
