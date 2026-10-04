"""T04: conjuntos SIGTAP normalizados passam pelas funções reais do motor (SINTETICO)."""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING

import duckdb
import pytest
from tests.fixtures.sigtap_apoio import normalizar, pacote
from tests.fixtures.sigtap_zip import (
    pacote_padrao,
)

from sustemporal.contracts import (
    DatasetRef,
    FamiliaFonte,
    calcular_dataset_id,
)
from sustemporal.ingest.sigtap import TABELAS
from sustemporal.rules.auxiliares import preparar_auxiliar
from sustemporal.rules.catalog import carregar_regras, requisito_auxiliar
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.rules import RuleSpec


def _regras_sigtap() -> list[RuleSpec]:
    return [r for r in carregar_regras() if requisito_auxiliar(r).fonte is FamiliaFonte.SIGTAP]


def test_motor_real_aceita_os_conjuntos_sigtap_de_cada_regra(tmp_path: Path) -> None:
    regras = _regras_sigtap()
    assert {requisito_auxiliar(r).schema_id for r in regras} >= {
        "sigtap_procedimento.v1",
        "sigtap_proc_ocupacao.v1",
        "sigtap_proc_registro.v1",
    }
    artefato = pacote(tmp_path, pacote_padrao())
    por_schema = {
        f"{esquema}.v1": normalizar(tmp_path, artefato, tabela)
        for tabela, esquema in TABELAS.items()
    }
    for regra in regras:
        dataset = por_schema[requisito_auxiliar(regra).schema_id]
        with closing(duckdb.connect()) as con:
            verificar_conteudo(con, dataset)
            auxiliar = preparar_auxiliar(con, regra, (dataset,))
        assert auxiliar.leiaute == "OK", regra.rule_id


def test_motor_real_recusa_conjunto_sigtap_com_hash_adulterado(tmp_path: Path) -> None:
    dataset = normalizar(tmp_path, pacote(tmp_path, pacote_padrao()), "tb_registro")
    falso = "lh1:" + "0" * 64
    adulterado = DatasetRef(
        **{
            **dataset.model_dump(),
            "hash_logico": falso,
            "dataset_id": calcular_dataset_id(dataset.schema_id, falso, dataset.artifact_ids),
        }
    )
    with closing(duckdb.connect()) as con, pytest.raises(ConteudoDivergente):
        verificar_conteudo(con, adulterado)
