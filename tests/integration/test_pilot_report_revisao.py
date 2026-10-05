"""T05: correções da revisão do #31 (SINTETICO; nenhum resultado empírico)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow.parquet as pq
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_relatorio import coorte_piloto, linhas_tabela, metrica

from sustemporal.reporting.report import build_pilot_report

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport

FORA_DO_DRS_XI = "355030"
CAMPOS_DE_ERRO = ("pa_codoco", "pa_flqt", "pa_fler")
FISICOS_OMITIDOS = ("PA_INDICA", "PA_CODOCO", "PA_FLQT", "PA_FLER")
AUSENCIA_ESPERADA = {
    "quantidade_apresentada": (2, 3),
    "valor_apresentado": (1, 3),
    "quantidade_aprovada": (0, 3),
    "valor_aprovado": (0, 3),
    "pa_indica": (3, 3),
    "pa_codoco": (3, 3),
    "pa_flqt": (3, 3),
    "pa_fler": (3, 3),
}


def _relatorio_sem_campos_do_g0(tmp_path: Path) -> EvaluationReport:
    registros = [
        registro("C", "201801", "201801", PA_QTDPRO="", PA_VALPRO=""),
        registro("C", "201801", "201801", PA_QTDPRO=""),
        registro("I", "201802", "201802"),
        registro("C", "201801", "201801", PA_UFMUN=FORA_DO_DRS_XI, PA_QTDPRO="", PA_VALPRO=""),
    ]
    dataset = conjunto_sia_pa(tmp_path, registros, sem_campos=FISICOS_OMITIDOS)
    saida = tmp_path / "relatorio"
    saida.mkdir()
    entradas = [dataset, cobertura_sintetica(tmp_path, [dataset])]
    return build_pilot_report(entradas, coorte_piloto(), saida)


def test_campos_do_g0_ausentes_entram_na_taxa_com_denominador_explicito(tmp_path: Path) -> None:
    relatorio = _relatorio_sem_campos_do_g0(tmp_path)
    estratos = {m.estrato for m in relatorio.metricas if m.nome == "taxa_ausencia_campo"}
    assert estratos >= set(AUSENCIA_ESPERADA)
    for campo, (ausentes, denominador) in AUSENCIA_ESPERADA.items():
        taxa = metrica(relatorio, "taxa_ausencia_campo", campo)
        assert (taxa.numerador, taxa.denominador) == (ausentes, denominador)
    tabela = {str(lin["campo"]): lin for lin in linhas_tabela(relatorio, "piloto_campos.v1")}
    assert {c: (tabela[c]["ausentes"], tabela[c]["denominador"]) for c in AUSENCIA_ESPERADA} == (
        AUSENCIA_ESPERADA
    )


def test_campos_de_erro_so_entram_na_tabela_de_ausencia_de_campos(tmp_path: Path) -> None:
    relatorio = _relatorio_sem_campos_do_g0(tmp_path)
    campos = {str(lin["campo"]) for lin in linhas_tabela(relatorio, "piloto_campos.v1")}
    assert set(CAMPOS_DE_ERRO) <= campos
    dimensoes = {str(lin["dimensao"]) for lin in linhas_tabela(relatorio, "piloto_contagens.v1")}
    assert dimensoes == {"competencia_processamento", "instrumento", "cnes"}
    for tabela in relatorio.tabelas:
        assert not set(CAMPOS_DE_ERRO) & set(pq.read_schema(tabela.caminho).names)
    outras = {m.estrato for m in relatorio.metricas if m.nome != "taxa_ausencia_campo"}
    assert not outras & set(CAMPOS_DE_ERRO)
