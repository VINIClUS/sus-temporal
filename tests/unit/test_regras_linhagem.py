"""Linhagem dos registros e erros semânticos na fronteira da CLI (cenários SINTETICOS)."""

import json
from pathlib import Path

import pytest

from sustemporal import cli
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.errors import ExitCode
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao
from tests.fixtures.regras_cenario import artefato, materializar, snapshot_vazio
from tests.fixtures.regras_execucao import executar, tabela
from tests.fixtures.regras_exemplos import ART_SIA, cenario_base, registro


@pytest.mark.parametrize(
    "row_id", [f"{ART_SIA}#0", f"{ART_SIA}/PASP1801.dbf#7"], ids=["simples", "com_membro"]
)
def test_linhagem_aceita_as_duas_formas_de_row_id(tmp_path: Path, row_id: str) -> None:
    resultado = executar(tmp_path, cenario_base(registro(row_id=row_id)))
    assert resultado.estado is EstadoExecucao.CONCLUIDA


def test_linhagem_recusa_membro_de_outro_artefato(tmp_path: Path) -> None:
    linha = registro(row_id=f"{artefato(5)}/PASP1801.dbf#7")
    resultado = executar(tmp_path, cenario_base(linha))
    assert resultado.estado is EstadoExecucao.FALHOU
    assert "linhagem_incoerente" in tabela(resultado, "falhas.v1")[0]["erro"]


def test_artefato_do_registro_fora_do_dataset_e_falha_de_carga(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    outros = (artefato(6),)
    dataset = dataset.model_copy(
        update={
            "artifact_ids": outros,
            "dataset_id": calcular_dataset_id(dataset.schema_id, dataset.hash_logico, outros),
        }
    )
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.FALHOU
    falha = tabela(resultado, "falhas.v1")[0]
    assert (falha["etapa"], "linhagem_fora_do_dataset" in falha["erro"]) == (
        "carregar_insumos",
        True,
    )


def _entrada(tmp_path: Path, dataset: DatasetRef, insumos: InsumosAvaliacao) -> Path:
    conteudo = {
        "dataset": dataset.model_dump(mode="json"),
        "snapshots": snapshot_vazio().model_dump(mode="json"),
        "auxiliares": [d.model_dump(mode="json") for d in insumos.auxiliares],
        "integridade": {a: str(e) for a, e in insumos.integridade.items()},
    }
    caminho = tmp_path / "entrada.json"
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    return caminho


@pytest.mark.parametrize("defeito", ["schema", "origem"])
def test_validate_traduz_erro_semantico_do_preflight(tmp_path: Path, defeito: str) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "in")
    if defeito == "schema":
        dataset = dataset.model_copy(
            update={
                "schema_id": "cobertura.v1",
                "dataset_id": calcular_dataset_id(
                    "cobertura.v1", dataset.hash_logico, dataset.artifact_ids
                ),
            }
        )
    else:
        auxiliares = tuple(
            d.model_copy(update={"origem_dados": OrigemDados.REAL}) for d in insumos.auxiliares
        )
        insumos = InsumosAvaliacao(auxiliares=auxiliares, integridade=insumos.integridade)
    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\n', encoding="utf-8")
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    argumentos += ["--entrada", str(_entrada(tmp_path, dataset, insumos))]
    argumentos += ["--saida", str(tmp_path / "saida")]
    assert cli.main(argumentos) == ExitCode.CONFIG_INVALIDA
