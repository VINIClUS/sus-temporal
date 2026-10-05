"""T05: coorte do relatório do piloto, pertença e UF do ingest (SINTETICO; nenhum resultado)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_relatorio import DRS_XI, coorte_piloto, relatorio_gravado
from tests.integration.test_pilot_report_revisao import (
    _erro_do_relatorio_recusado,
    _ingest_completo,
    _saida_do_pilot_report,
)

from sustemporal.contracts.experiment import PertencaGeografica
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.reporting.report import build_pilot_report

if TYPE_CHECKING:
    from pathlib import Path

TERRITORIO_MG = """\
territorio_id: mg_sintetico
descricao: Território sintético de MG para teste; nenhum dado real.
uf: MG
proveniencia: SECUNDARIA
confirmacao: A_CONFIRMAR
fontes:
  - doc_id: S1
    titulo: Fixture sintética
    estado: PENDENTE
    proveniencia: SECUNDARIA
    confirmacao: A_CONFIRMAR
municipios:
  - {ibge7: 3106200, ibge6: 310620, nome: Belo Horizonte, regiao: Metropolitana}
"""


def _com_coorte(
    config: Path, *, uf: str = "SP", territorio: Path = DRS_XI, pertenca: str | None = None
) -> None:
    """Acrescenta à configuração do ingest uma coorte explícita (por padrão, SP e o DRS XI)."""
    linhas = [
        "coorte:",
        "  cohort_id: coorte_explicita",
        f"  uf: {uf}",
        f"  territorio: {territorio}",
        '  inicio: "201801"',
        '  fim: "201812"',
        *([f"  pertenca: {pertenca}"] if pertenca else []),
    ]
    with config.open("a", encoding="utf-8") as saida:
        saida.write("\n".join(linhas) + "\n")


def test_pertenca_historica_e_recusada_sem_publicar_nada(tmp_path: Path) -> None:
    dataset = conjunto_sia_pa(tmp_path, [registro("C", "201801", "201801")])
    saida = tmp_path / "relatorio"
    saida.mkdir()
    entradas = [dataset, cobertura_sintetica(tmp_path, [dataset])]
    historica = coorte_piloto().model_copy(update={"pertenca": PertencaGeografica.HISTORICA})
    esperado = "pertenca_historica_nao_implementada coorte=piloto_sintetico"
    with pytest.raises(ConfigInvalida, match=esperado):
        build_pilot_report(entradas, historica, saida)
    assert list(saida.iterdir()) == []


def test_pilot_report_com_pertenca_historica_recusa_antes_de_criar_a_saida(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    _com_coorte(config, pertenca="HISTORICA")
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert "pertenca_historica_nao_implementada coorte=coorte_explicita" in erro


@pytest.mark.parametrize("pertenca", ["FIXA", "A_DEFINIR"])
def test_pertenca_fixa_ou_a_definir_gera_o_relatorio_e_cita_a_pertenca(
    tmp_path: Path, pertenca: str
) -> None:
    config = _ingest_completo(tmp_path)
    _com_coorte(config, pertenca=pertenca)
    assert _saida_do_pilot_report(config) == ExitCode.OK
    assert any(f"pertenca={pertenca}" in nota for nota in relatorio_gravado(tmp_path).notas)


def test_coorte_com_uf_diferente_da_do_ingest_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    territorio = tmp_path / "territorio_mg.yaml"
    territorio.write_text(TERRITORIO_MG, encoding="utf-8")
    _com_coorte(config, uf="MG", territorio=territorio)
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert "coorte_com_uf_divergente coorte=MG piloto=SP cohort_id=coorte_explicita" in erro
