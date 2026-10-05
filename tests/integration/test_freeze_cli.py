"""CLI `freeze` e `evaluate --freeze` com execuções, G2 e manifesto (T11, SINTETICO).

Cenário sintético rotulado REAL só nos contratos; decisões só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    gravar_runs,
    manifesto_da_cli,
    nome_do_arquivo_da_execucao,
    runs_da_cli,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.cli import main
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from sustemporal.contracts import RuleSpec

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
