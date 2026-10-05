"""CNES ST no contexto do `validate --ingest` (SINTETICO): só os contrafactuais o leem.

As regras exigem o CNES PF e o SIGTAP; as precondições das operações de `catalog/operations.yaml`
leem também o CNES ST. Quando a pasta do ingest traz CNES ST, ele entra nos auxiliares da execução
(e no `entrada_validacao.json`), sem mudar o resultado das regras.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq
import pytest

from sustemporal import cli
from sustemporal.contracts.experiment import RunResult
from sustemporal.errors import ExitCode
from sustemporal.explanation.counterfactual_operacoes import carregar_operacoes
from sustemporal.rules.catalog import carregar_regras, requisito_auxiliar
from sustemporal.rules.cli import EntradaValidacao
from sustemporal.rules.ingest import CADASTROS_DO_CONTEXTO
from tests.fixtures.regras_ingest import montar_ingest

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.regras_ingest import MundoIngest

_ST = "cnes_estabelecimento.v1"


def _validar(mundo: MundoIngest, politica: str = "processamento") -> int:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", politica]
    return cli.main([*argumentos, "--ingest", str(mundo.pasta), "--saida", str(mundo.saida)])


def _gravados(mundo: MundoIngest) -> list[tuple[RunResult, EntradaValidacao]]:
    gravados = []
    for caminho in sorted(mundo.saida.glob("*/run_result.json")):
        run = RunResult.model_validate_json(caminho.read_text(encoding="utf-8"))
        texto = (caminho.parent / "entrada_validacao.json").read_text(encoding="utf-8")
        gravados.append((run, EntradaValidacao.model_validate_json(texto)))
    return gravados


def _gravado(mundo: MundoIngest) -> tuple[RunResult, EntradaValidacao]:
    gravados = _gravados(mundo)
    assert len(gravados) == 1
    return gravados[0]


def _linhas_da_pasta(mundo: MundoIngest) -> list[dict[str, Any]]:
    texto = (mundo.pasta / "datasets.jsonl").read_text(encoding="utf-8")
    return [json.loads(linha) for linha in texto.splitlines()]


def _regravar(mundo: MundoIngest, linhas: list[dict[str, Any]]) -> None:
    conteudo = "".join(f"{json.dumps(linha)}\n" for linha in linhas)
    (mundo.pasta / "datasets.jsonl").write_text(conteudo, encoding="utf-8")


def _sem_st_na_pasta(mundo: MundoIngest) -> None:
    """A mesma pasta sem as linhas do CNES ST: o ingest sem a família."""
    linhas = _linhas_da_pasta(mundo)
    mantidas = [linha for linha in linhas if linha["schema_id"] != _ST]
    assert len(mantidas) < len(linhas)
    _regravar(mundo, mantidas)


def _conteudo(run: RunResult, schema_id: str) -> list[str]:
    """Linhas da saída sem o `run_id` (que muda com qualquer insumo), em ordem estável."""
    caminho = next(s.caminho for s in run.saidas if s.schema_id == schema_id)
    linhas = pq.read_table(caminho).to_pylist()
    sem_run = ({k: v for k, v in linha.items() if k != "run_id"} for linha in linhas)
    return sorted(json.dumps(linha, sort_keys=True, default=str) for linha in sem_run)


def test_pasta_com_cnes_st_grava_o_st_derivado_no_contexto(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, com_cnes_st=True)
    st_da_pasta = [ref for ref in _linhas_da_pasta(mundo) if ref["schema_id"] == _ST]
    artefatos_st = {artefato for ref in st_da_pasta for artefato in ref["artifact_ids"]}
    assert len(artefatos_st) == 2

    assert _validar(mundo) == ExitCode.OK

    run, entrada = _gravado(mundo)
    derivados = [d for d in entrada.auxiliares if d.schema_id == _ST]
    assert len(derivados) == 1
    st = derivados[0]
    assert st.dataset_id in {e.dataset_id for e in run.entradas}
    assert st.produzido_por == "validate_ingest"
    assert set(st.artifact_ids) == artefatos_st
    linhas = pq.read_table(st.caminho).to_pylist()
    assert {(linha["competencia_arquivo"], linha["cnes"]) for linha in linhas} == {
        ("202301", "1234567"),
        ("202302", "1234567"),
    }


def test_pasta_sem_cnes_st_so_traz_os_auxiliares_das_regras(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)

    assert _validar(mundo) == ExitCode.OK

    _, entrada = _gravado(mundo)
    exigidos = {requisito_auxiliar(regra).schema_id for regra in carregar_regras()}
    assert {d.schema_id for d in entrada.auxiliares} == exigidos


@pytest.mark.parametrize("politica", ["atendimento", "processamento"])
def test_cnes_st_nao_muda_o_resultado_das_regras_so_acrescenta_um_insumo(
    tmp_path: Path, politica: str
) -> None:
    mundo = montar_ingest(tmp_path, com_cnes_st=True)
    assert _validar(mundo, politica) == ExitCode.OK
    run_com, entrada_com = _gravado(mundo)
    _sem_st_na_pasta(mundo)
    assert _validar(mundo, politica) == ExitCode.OK
    gravados = _gravados(mundo)
    assert len(gravados) == 2
    run_sem = next(run for run, _ in gravados if run.run_id != run_com.run_id)

    saidas = ("avaliacoes.v1", "evidencias.v1", "selecao_versoes.v1", "agregados_registro.v1")
    for schema_id in saidas:
        assert _conteudo(run_com, schema_id) == _conteudo(run_sem, schema_id)
    st = next(d for d in entrada_com.auxiliares if d.schema_id == _ST)
    com, sem = ({e.dataset_id for e in run.entradas} for run in (run_com, run_sem))
    assert com - sem == {st.dataset_id}
    assert sem <= com


def test_cnes_st_divergente_do_dataset_recusa_o_ingest_sem_gravar_nada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, com_cnes_st=True)
    linhas = _linhas_da_pasta(mundo)
    for linha in linhas:
        if linha["schema_id"] == _ST:
            linha["linhas"] += 1
    _regravar(mundo, linhas)

    assert _validar(mundo) == ExitCode.CONFIG_INVALIDA

    assert not list(mundo.saida.glob("*/run_result.json"))
    assert not (mundo.saida / "entradas").exists()


def test_cadastros_do_contexto_cobrem_o_que_as_operacoes_do_catalogo_alteram() -> None:
    exigidos = {requisito_auxiliar(regra).schema_id for regra in carregar_regras()}
    alvos = {operacao.alvo.schema_id for operacao in carregar_operacoes()}
    assert alvos <= exigidos | set(CADASTROS_DO_CONTEXTO)
    assert exigidos.isdisjoint(CADASTROS_DO_CONTEXTO)
