"""E2E: `validate` sem `--saida` grava em `<raiz_saidas>/runs` e o `explain` o encontra.

Entrada SINTETICA, sem rede e sem mock do motor: o `validate` roda pela CLI nos dois modos
(`--entrada` e `--ingest`) e o `explain` pela CLI descobre a execução só em `runs/`. Nada aqui é
resultado empírico.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.contrafactual_e2e import (
    ExecucaoReal,
    validar_entrada_pela_cli,
    validar_ingest_pela_cli,
)

from sustemporal import cli
from sustemporal.config import load_config
from sustemporal.execucoes import raiz_execucoes
from sustemporal.explanation.cli import diretorio_explicacao

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _log_isolado() -> Iterator[None]:
    """`cli.main` reconfigura o log da raiz; o handler dele não sobrevive ao teste."""
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    yield
    for handler in [h for h in raiz.handlers if h not in antes]:
        raiz.removeHandler(handler)
    raiz.setLevel(nivel)


def _explain(execucao: ExecucaoReal, row: str) -> int:
    argumentos = ["explain", "--config", str(execucao.config), "--run", execucao.run_id]
    return cli.main([*argumentos, "--row", row])


def _destino(execucao: ExecucaoReal, row: str) -> Path:
    return diretorio_explicacao(execucao.saidas, execucao.run_id, row)


def _exigir_so_em_runs(execucao: ExecucaoReal) -> None:
    runs = raiz_execucoes(load_config(execucao.config))
    assert runs == execucao.saidas / "runs"
    pasta = runs / execucao.run_id
    assert (pasta / "run_result.json").is_file()
    assert (pasta / "entrada_validacao.json").is_file()
    assert not (execucao.saidas / "validacao").exists()


def test_entrada_sem_saida_grava_em_runs_e_o_explain_encontra(tmp_path: Path) -> None:
    execucao = validar_entrada_pela_cli(tmp_path)
    _exigir_so_em_runs(execucao)
    linha = execucao.linha_com_violacao()

    assert _explain(execucao, linha) == 0

    assert (_destino(execucao, linha) / "bundle.json").is_file()


def test_ingest_sem_saida_grava_em_runs_e_o_explain_encontra(tmp_path: Path) -> None:
    execucao = validar_ingest_pela_cli(tmp_path, "processamento")
    _exigir_so_em_runs(execucao)
    linha = execucao.linha_com_violacao()

    assert _explain(execucao, linha) == 0

    assert (_destino(execucao, linha) / "bundle.json").is_file()


def test_execucao_gravada_fora_de_runs_nao_e_encontrada_pelo_explain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    execucao = validar_entrada_pela_cli(tmp_path)
    fora = execucao.saidas / "validacao"
    fora.mkdir()
    (execucao.saidas / "runs" / execucao.run_id).rename(fora / execucao.run_id)
    linha = execucao.linha_com_violacao()
    capsys.readouterr()

    assert _explain(execucao, linha) == 2

    erro = f"explain_recusado erro=execucao_inexistente run={execucao.run_id}"
    assert erro in capsys.readouterr().err
    assert not _destino(execucao, linha).exists()
