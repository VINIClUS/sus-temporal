"""Lote de seleção (T06) lido e conferido pelo motor (T07) com as políticas do catálogo."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest
from tests.fixtures.temporal_registro import observar, registro_producao, regra

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.records import OrigemDados
from sustemporal.rules.coerencia import conferir_selecoes, criar_regras_fontes
from sustemporal.rules.preparo import carregar_selecoes
from sustemporal.temporal.lote import gravar_selecoes, selecionar_lote
from sustemporal.temporal.politicas import carregar_politica
from sustemporal.temporal.registry import registro_de

if TYPE_CHECKING:
    from pathlib import Path

PF = FamiliaFonte.CNES_PF
_LINHAS = [
    ("201801", "201801"),
    ("201712", "201801"),
    ("201801", "201802"),
    (None, "201801"),
    ("201813", None),
]


def _config() -> RunConfig:
    piloto = {
        "uf": "SP",
        "competencias_processamento": ["201801"],
        "territorio": "catalog/territorio/drs_xi.yaml",
        "familias_fontes": ["SIA_PA", "CNES_PF"],
    }
    return RunConfig.model_validate({"versao": "1", "piloto": piloto})


def _registro():
    itens = [
        observar(PF, "201801", "A", 1),
        observar(PF, "201712", "B", 1),
        observar(PF, "201712", "C", 2),
        observar(PF, "201802", "D", 1, uf="MG"),
    ]
    return registro_de([o for o, _ in itens], [v for _, v in itens if v is not None])


@pytest.mark.parametrize("politica_id", ["B_ATEND", "B_PROC", "M_TEMP_PADRAO"])
def test_lote_passa_pela_conferencia_do_motor(tmp_path: Path, politica_id: str) -> None:
    politica = carregar_politica(politica_id)
    regras = [regra()]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    con.executemany(
        "INSERT INTO registros VALUES (?, ?, ?)",
        [(registro_producao(None, None, i).row_id, a, p) for i, (a, p) in enumerate(_LINHAS)],
    )
    selecionar_lote(con, "registros", regras, politica, _registro(), run_id="r", config=_config())
    dataset = gravar_selecoes(con, tmp_path / "selecao", run_id="r", origem=OrigemDados.SINTETICO)
    carregar_selecoes(con, dataset)
    criar_regras_fontes(con, regras, politica)
    conferir_selecoes(con)
    estados = {e for (e,) in con.execute("SELECT DISTINCT estado FROM selecoes").fetchall()}
    if politica_id == "M_TEMP_PADRAO":
        assert estados == {"NAO_RESOLVIDA"}
    else:
        assert "SELECIONADA" in estados
        assert len(estados) > 1
