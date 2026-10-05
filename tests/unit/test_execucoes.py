"""Lugar único das execuções do `validate` (SINTETICO)."""

from __future__ import annotations

from pathlib import Path

from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.execucoes import DIRETORIO_EXECUCOES, raiz_execucoes


def test_diretorio_das_execucoes_e_runs() -> None:
    assert DIRETORIO_EXECUCOES == "runs"


def test_raiz_das_execucoes_e_runs_sob_a_raiz_de_saidas(tmp_path: Path) -> None:
    config = RunConfig(versao="1", runtime=RuntimeConfig(raiz_saidas=str(tmp_path / "saidas")))
    assert raiz_execucoes(config) == tmp_path / "saidas" / "runs"


def test_raiz_das_execucoes_com_a_raiz_de_saidas_padrao() -> None:
    assert raiz_execucoes(RunConfig(versao="1")) == Path("outputs") / "runs"
