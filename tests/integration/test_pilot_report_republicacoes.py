"""T05: versões concorrentes do SIA-PA e população do relatório (SINTETICO; nenhum resultado)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.piloto_relatorio import linhas_tabela, metrica, relatorio_gravado
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap
from tests.integration.test_pilot_report import PF

from sustemporal import cli
from sustemporal.errors import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, EvaluationReport

OUTRO_INSTANTE = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _manifesto(pasta: Path, versoes: list[ArtifactVersion]) -> Path:
    (pasta / "manifestos").mkdir(parents=True)
    destino = pasta / "manifestos" / "aquisicao.jsonl"
    store = pasta / "dados" / "raw"
    auxiliares = [
        artefato_sigtap(store, zip_sigtap(pacote_padrao("201801"))),
        artefato_cnes(store, dbc_cnes(PF, [registro_pf("0012345", "225125")]), PF),
    ]
    registrar_versoes(destino, [*versoes, *auxiliares])
    return destino


def _relatorio(
    pasta: Path, partes: list[str], *, competencias: str = '"201801"'
) -> EvaluationReport:
    config = config_ingest(pasta, fontes_ingest(pasta, partes), competencias=competencias)
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    assert cli.main(["pilot-report", "--config", str(config)]) == ExitCode.OK
    return relatorio_gravado(pasta)


def _exclusoes(relatorio: EvaluationReport) -> dict[str, int]:
    linhas = linhas_tabela(relatorio, "piloto_exclusoes.v1")
    return {str(lin["motivo"]): int(lin["linhas"]) for lin in linhas}


def _contagens(relatorio: EvaluationReport, dimensao: str) -> dict[str, int]:
    linhas = linhas_tabela(relatorio, "piloto_contagens.v1")
    return {str(lin["valor"]): int(lin["linhas"]) for lin in linhas if lin["dimensao"] == dimensao}


def test_versoes_divergentes_da_mesma_parte_saem_da_populacao_do_relatorio(tmp_path: Path) -> None:
    store = tmp_path / "dados" / "raw"
    primeira = artefato_pa(store, dbc_pa([registro("C", "201801", "201801")] * 3, deletados=[2]))
    segunda = artefato_pa(store, dbc_pa([registro("C", "201801", "201801", PA_INDICA="6")] * 2))
    parte_b = artefato_pa(store, dbc_pa([registro("C", "201801", "201801")] * 2), parte="b")
    outra = artefato_pa(
        store, dbc_pa([registro("I", "201802", "201802")] * 2), competencia="201802"
    )
    _manifesto(tmp_path, [primeira, segunda, parte_b, outra])
    relatorio = _relatorio(tmp_path, ["a", "b"], competencias='"201801", "201802"')
    assert _exclusoes(relatorio) == {"versoes_concorrentes": 7}
    incluidos = metrica(relatorio, "fracao_registros_incluidos")
    assert (incluidos.numerador, incluidos.denominador) == (2, 9)
    assert _contagens(relatorio, "competencia_processamento") == {"201802": 2}
    notas = [nota for nota in relatorio.notas if nota.startswith("versoes_concorrentes")]
    assert len(notas) == 1
    versoes = ",".join(sorted([primeira.artifact_id, segunda.artifact_id]))
    assert notas[0].startswith(
        f"versoes_concorrentes competencia=201801 uf=SP parte=a versoes={versoes}"
    )
    linhas = [
        lin
        for lin in linhas_tabela(relatorio, "piloto_disponibilidade.v1")
        if lin["competencia"] == "201801"
    ]
    assert linhas
    assert {str(lin["estado"]) for lin in linhas} != {"DISPONIVEL"}
    assert all(
        "sia_pa_incompleto competencia=201801 motivo=" in str(lin["motivo"]) for lin in linhas
    )


def test_mesmo_conteudo_observado_duas_vezes_mantem_a_populacao(tmp_path: Path) -> None:
    store = tmp_path / "dados" / "raw"
    unica = artefato_pa(store, dbc_pa([registro("C", "201801", "201801")] * 3, deletados=[2]))
    manifesto = _manifesto(tmp_path, [unica])
    registrar_versoes(manifesto, [unica], observado_em=OUTRO_INSTANTE, rotulo="segunda_observacao")
    relatorio = _relatorio(tmp_path, ["a"])
    assert _exclusoes(relatorio) == {"deletado": 1}
    incluidos = metrica(relatorio, "fracao_registros_incluidos")
    assert (incluidos.numerador, incluidos.denominador) == (2, 3)
    assert not [nota for nota in relatorio.notas if nota.startswith("versoes_concorrentes")]
