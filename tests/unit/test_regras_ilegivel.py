"""Parquet canônico ilegível é falha operacional, nunca INCONCLUSIVO (cenários SINTETICOS)."""

import json
from pathlib import Path

import pytest

from sustemporal import cli
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.contracts.records import DatasetRef
from sustemporal.errors import ExitCode
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, tabela
from tests.fixtures.regras_exemplos import cenario_base, registro

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"
VIGENCIA = "VIGENCIA_PROCEDIMENTO_SIGTAP"
MODOS = ["ausente", "truncado", "nao_parquet"]


def _estragar(caminho: Path, modo: str) -> None:
    if modo == "ausente":
        caminho.unlink()
    elif modo == "truncado":
        dados = caminho.read_bytes()
        caminho.write_bytes(dados[: len(dados) // 2])
    else:
        caminho.write_bytes(b"isto nao e parquet")


def _preparar(tmp_path: Path, schema_id: str, modo: str) -> tuple[DatasetRef, InsumosAvaliacao]:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    entradas = [*insumos.auxiliares, insumos.cobertura]
    alvo = next(d for d in entradas if d is not None and d.schema_id == schema_id)
    _estragar(Path(alvo.caminho), modo)
    return dataset, insumos


def _executar(tmp_path: Path, schema_id: str, modo: str) -> RunResult:
    dataset, insumos = _preparar(tmp_path, schema_id, modo)
    return evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )


@pytest.mark.parametrize("modo", MODOS)
def test_auxiliar_ilegivel_e_falha_so_da_regra_dependente(tmp_path: Path, modo: str) -> None:
    resultado = _executar(tmp_path, "sigtap_procedimento.v1", modo)
    assert resultado.estado is EstadoExecucao.PARCIAL
    falhas = tabela(resultado, "falhas.v1")
    assert [(f["etapa"], f["rule_id"]) for f in falhas] == [("avaliar_regra", VIGENCIA)]
    avaliacoes = avaliacoes_por_chave(resultado)
    assert (LINHA, VIGENCIA) not in avaliacoes
    assert avaliacoes[(LINHA, PROC)]["estado"] == "VIOLACAO"
    assert tabela(resultado, "agregados_registro.v1") == []


@pytest.mark.parametrize("modo", MODOS)
def test_cobertura_ilegivel_e_falha_de_carga(tmp_path: Path, modo: str) -> None:
    resultado = _executar(tmp_path, "cobertura.v1", modo)
    assert resultado.estado is EstadoExecucao.FALHOU
    falhas = tabela(resultado, "falhas.v1")
    assert [(f["etapa"], f["rule_id"]) for f in falhas] == [("carregar_insumos", None)]
    assert tabela(resultado, "avaliacoes.v1") == []


@pytest.mark.parametrize("schema_id", ["sigtap_procedimento.v1", "cobertura.v1"])
def test_validate_com_fonte_ilegivel_termina_com_codigo_de_falha(
    tmp_path: Path, schema_id: str
) -> None:
    dataset, insumos = _preparar(tmp_path / "in", schema_id, "nao_parquet")
    entrada = tmp_path / "entrada.json"
    conteudo = {
        "dataset": dataset.model_dump(mode="json"),
        "snapshots": snapshot_vazio().model_dump(mode="json"),
        "auxiliares": [d.model_dump(mode="json") for d in insumos.auxiliares],
        "cobertura": insumos.cobertura.model_dump(mode="json") if insumos.cobertura else None,
        "integridade": {a: str(e) for a, e in insumos.integridade.items()},
    }
    entrada.write_text(json.dumps(conteudo), encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\n', encoding="utf-8")
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    argumentos += ["--entrada", str(entrada), "--saida", str(tmp_path / "saida")]
    assert cli.main(argumentos) == ExitCode.FALHA_OPERACIONAL
