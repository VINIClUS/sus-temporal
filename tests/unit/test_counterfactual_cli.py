"""CLI `sustemporal counterfactual` (T09) sobre uma execução SINTETICA; nada aqui é empírico."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.counterfactual import CounterfactualSearchResult, Executabilidade
from sustemporal.explanation.cli import localizar_execucao
from sustemporal.explanation.counterfactual import search_counterfactuals
from sustemporal.explanation.counterfactual_cli import (
    diretorio_contrafactual,
    executar_counterfactual,
)
from sustemporal.explanation.explain import montar_explicacao
from sustemporal.rules.cli import EntradaValidacao
from tests.fixtures.contrafactual_execucao import (
    ARQUIVO_ENTRADA,
    Execucao,
    executar_validacao_sintetica,
)

_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"


@pytest.fixture(scope="module")
def execucao(tmp_path_factory: pytest.TempPathFactory) -> Execucao:
    return executar_validacao_sintetica(tmp_path_factory.mktemp("cli_contrafactual"))


def _rodar(execucao: Execucao, row: str, run: str | None = None) -> int:
    args = argparse.Namespace(run=run or execucao.run_id, row=row)
    return executar_counterfactual(args, execucao.config)


def _saidas(execucao: Execucao) -> Path:
    return Path(execucao.config.runtime.raiz_saidas)


def _destino(execucao: Execucao, row: str) -> Path:
    return diretorio_contrafactual(_saidas(execucao), execucao.run_id, row)


def _resultado(execucao: Execucao, row: str) -> CounterfactualSearchResult:
    texto = (_destino(execucao, row) / "contrafactual.json").read_text(encoding="utf-8")
    return CounterfactualSearchResult.model_validate_json(texto)


def test_ausencia_pela_cli_publica_hipotese_sem_aprovacao(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia) == 0
    resultado = _resultado(execucao, execucao.ausencia)
    assert [[o.op_id for o in s.operacoes] for s in resultado.solucoes] == [[_INCLUIR]]
    assert resultado.solucoes[0].executabilidade is Executabilidade.HIPOTESE_PASSADA
    assert resultado.aprovacao_garantida is False
    bruto = json.loads((_destino(execucao, execucao.ausencia) / "contrafactual.json").read_text())
    assert bruto["aprovacao_garantida"] is False


def test_saida_e_imutavel_e_derivada_de_run_e_row(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia) == 0
    destino = _destino(execucao, execucao.ausencia)
    antes = {p.name: p.read_bytes() for p in destino.iterdir()}
    assert _rodar(execucao, execucao.ausencia) == 0
    assert {p.name: p.read_bytes() for p in destino.iterdir()} == antes
    assert destino.parent == _saidas(execucao) / "contrafactuais" / execucao.run_id
    assert not list(destino.parent.glob(".*parcial*"))


@pytest.mark.parametrize("linha", ["mes_faltante", "borda_2018"])
def test_linha_sem_violacao_nao_gera_contrafactual_nem_usa_mes_vizinho(
    execucao: Execucao, linha: str
) -> None:
    row = getattr(execucao, linha)
    assert _rodar(execucao, row) == 2
    assert not _destino(execucao, row).exists()


def test_run_inexistente_da_saida_2(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia, run="val_inexistente") == 2


def test_row_inexistente_da_saida_2(execucao: Execucao) -> None:
    row = execucao.ausencia.replace("#0", "#99")
    assert _rodar(execucao, row) == 2
    assert not _destino(execucao, row).exists()


def test_argumento_invalido_da_saida_2(execucao: Execucao) -> None:
    assert _rodar(execucao, "nao_e_row_id") == 2


def _pasta_da_execucao(execucao: Execucao) -> Path:
    return _saidas(execucao) / "runs" / execucao.run_id


def test_entrada_da_execucao_ausente_da_saida_2(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    (_pasta_da_execucao(execucao) / ARQUIVO_ENTRADA).unlink()
    assert _rodar(execucao, execucao.ausencia) == 2


def test_entrada_divergente_do_run_id_da_saida_2(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    caminho = _pasta_da_execucao(execucao) / ARQUIVO_ENTRADA
    entrada = EntradaValidacao.model_validate_json(caminho.read_text(encoding="utf-8"))
    alterada = dict(entrada.integridade) | dict.fromkeys(
        entrada.integridade, EstadoIntegridade.NAO_VERIFICADO
    )
    caminho.write_text(
        entrada.model_copy(update={"integridade": alterada}).model_dump_json(), encoding="utf-8"
    )
    assert _rodar(execucao, execucao.ausencia) == 2
    assert not _destino(execucao, execucao.ausencia).exists()


def test_busca_de_dois_argumentos_resolve_pela_execucao(execucao: Execucao) -> None:
    run = localizar_execucao(_saidas(execucao), execucao.run_id)
    bundle = montar_explicacao(run, execucao.ausencia, runtime=execucao.config.runtime).bundle
    resultado = search_counterfactuals(bundle, execucao.config)
    assert [[o.op_id for o in s.operacoes] for s in resultado.solucoes] == [[_INCLUIR]]
    assert resultado.aprovacao_garantida is False
