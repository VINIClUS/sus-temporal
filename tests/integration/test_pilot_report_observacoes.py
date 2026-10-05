"""T05: classe da ausência segundo o resultado conhecido das observações (SINTETICO)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_relatorio import coorte_piloto, linhas_tabela
from tests.fixtures.piloto_selecao import selecao_sintetica

from sustemporal.contracts import ResultadoTentativa
from sustemporal.reporting.report import build_pilot_report

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

SEM_RESULTADO = "ausente_tentativa_sem_resultado_conhecido"
NAO_ENCONTRADO = "ausente_nao_encontrado_na_listagem"


@pytest.mark.parametrize(
    ("observacoes", "citadas", "classe"),
    [
        (None, "obs_x", SEM_RESULTADO),
        ({"obs_y": ResultadoTentativa.NAO_ENCONTRADO}, "obs_x", SEM_RESULTADO),
        (None, "obs_x;obs_y", SEM_RESULTADO),
        ({"obs_x": ResultadoTentativa.NAO_ENCONTRADO}, "obs_x;obs_y", NAO_ENCONTRADO),
        ({"obs_x": ResultadoTentativa.NAO_ENCONTRADO}, "obs_x", NAO_ENCONTRADO),
        ({"obs_x": ResultadoTentativa.FALHA_TRANSPORTE}, "obs_x", "ausente_tentativa_sem_bytes"),
        (None, "", "ausente_sem_tentativa"),
    ],
)
def test_ausencia_so_vira_sem_tentativa_quando_a_selecao_nao_cita_observacao(
    tmp_path: Path,
    observacoes: Mapping[str, ResultadoTentativa] | None,
    citadas: str,
    classe: str,
) -> None:
    dataset = conjunto_sia_pa(tmp_path, [registro("C", "201801", "201801")])
    saida = tmp_path / "relatorio"
    saida.mkdir()
    entradas = [
        dataset,
        cobertura_sintetica(tmp_path, [dataset]),
        selecao_sintetica(tmp_path, dataset, observation_ids=citadas),
    ]
    relatorio = build_pilot_report(entradas, coorte_piloto(), saida, observacoes=observacoes)
    classes = {str(lin["classe"]) for lin in linhas_tabela(relatorio, "piloto_inconclusivos.v1")}
    assert classes == {classe}
