"""Comando `sustemporal validate`: mesmo motor, só a política temporal muda (SINTETICO)."""

import json
from pathlib import Path

import pytest

from sustemporal import cli
from sustemporal.contracts.experiment import RunResult
from sustemporal.errors import ExitCode
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_exemplos import cenario_base, registro


def _entrada(tmp_path: Path) -> Path:
    dataset, insumos = materializar(cenario_base(registro(0), registro(1, cbo="999999")), tmp_path)
    conteudo = {
        "dataset": dataset.model_dump(mode="json"),
        "snapshots": snapshot_vazio().model_dump(mode="json"),
        "auxiliares": [d.model_dump(mode="json") for d in insumos.auxiliares],
        "selecoes": None,
        "cobertura": insumos.cobertura.model_dump(mode="json") if insumos.cobertura else None,
        "integridade": {a: str(e) for a, e in insumos.integridade.items()},
    }
    caminho = tmp_path / "entrada.json"
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    return caminho


@pytest.mark.parametrize(
    ("politica", "metodo"),
    [("documented", "M_TEMP"), ("atendimento", "B_ATEND"), ("processamento", "B_PROC")],
)
def test_validate_muda_so_a_politica(tmp_path: Path, politica: str, metodo: str) -> None:
    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\nmodo: EXPLORATORIO\n', encoding="utf-8")
    saida = tmp_path / "saida"
    argumentos = ["validate", "--config", str(config), "--policy", politica]
    argumentos += ["--entrada", str(_entrada(tmp_path / "in")), "--saida", str(saida)]
    assert cli.main(argumentos) == ExitCode.OK
    gravado = next(saida.rglob("run_result.json"))
    resultado = RunResult.model_validate_json(gravado.read_text(encoding="utf-8"))
    assert resultado.metodo is not None
    assert resultado.metodo.value == metodo


def test_validate_com_entrada_invalida_retorna_config_invalida(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\n', encoding="utf-8")
    entrada = tmp_path / "entrada.json"
    entrada.write_text("{}", encoding="utf-8")
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    assert cli.main([*argumentos, "--entrada", str(entrada)]) == ExitCode.CONFIG_INVALIDA


def test_validate_com_entrada_grava_a_entrada_da_validacao(tmp_path: Path) -> None:
    from sustemporal.rules.cli import EntradaValidacao

    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\n', encoding="utf-8")
    saida = tmp_path / "saida"
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    argumentos += ["--entrada", str(_entrada(tmp_path / "in")), "--saida", str(saida)]
    assert cli.main(argumentos) == ExitCode.OK
    gravado = next(saida.rglob("run_result.json"))
    resultado = RunResult.model_validate_json(gravado.read_text(encoding="utf-8"))
    entrada = EntradaValidacao.model_validate_json(
        (gravado.parent / "entrada_validacao.json").read_text(encoding="utf-8")
    )
    refs = [entrada.dataset, *entrada.auxiliares, entrada.selecoes, entrada.cobertura]
    assert sorted(r.dataset_id for r in refs if r is not None) == sorted(
        e.dataset_id for e in resultado.entradas
    )
    assert entrada.politica is not None
    assert entrada.politica.politica_id == resultado.politica_id
