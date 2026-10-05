"""T05: versões concorrentes do SIA-PA e população do relatório (SINTETICO; nenhum resultado)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.piloto_relatorio import (
    coorte_piloto,
    linhas_tabela,
    metrica,
    relatorio_gravado,
)
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap
from tests.integration.test_pilot_report import PF

from sustemporal import cli
from sustemporal.contracts import CanalPublicacao, ChaveArtefato, FamiliaFonte
from sustemporal.errors import ExitCode
from sustemporal.reporting.report import build_pilot_report

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion, DatasetRef, EvaluationReport

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


def _chave(competencia: str, parte: str) -> ChaveArtefato:
    return ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf="SP",
        competencia_arquivo=competencia,
        parte=parte,
        canal=CanalPublicacao.ATUAL,
        nome_original=f"PASP{competencia[2:]}{parte}.dbc",
    )


def _versoes_publicadas(pasta: Path) -> tuple[list[DatasetRef], dict[str, ChaveArtefato]]:
    """Duas versões divergentes de 201801/a (uma com linha de 201712) e uma de 201802/a."""
    primeira = conjunto_sia_pa(
        pasta, [registro("C", "201801", "201801"), registro("C", "201712", "201712")]
    )
    segunda = conjunto_sia_pa(pasta, [registro("C", "201801", "201801", PA_INDICA="6")])
    outra = conjunto_sia_pa(pasta, [registro("I", "201802", "201802")], competencia="201802")
    chaves = {
        primeira.artifact_ids[0]: _chave("201801", "a"),
        segunda.artifact_ids[0]: _chave("201801", "a"),
        outra.artifact_ids[0]: _chave("201802", "a"),
    }
    return [primeira, segunda, outra], chaves


def _publicar(
    pasta: Path, nome: str, entradas: list[DatasetRef], **opcoes: dict[str, ChaveArtefato]
) -> EvaluationReport:
    saida = pasta / nome
    saida.mkdir()
    return build_pilot_report(
        entradas, coorte_piloto(inicio="201712", fim="201812"), saida, **opcoes
    )


def test_chaves_decidem_a_deteccao_e_mudam_o_id_do_relatorio(tmp_path: Path) -> None:
    sia_pa, chaves = _versoes_publicadas(tmp_path)
    cobertura = cobertura_sintetica(tmp_path, sia_pa, ("201712", "201801", "201802"))
    sem = _publicar(tmp_path, "sem_chaves", [*sia_pa, cobertura])
    com = _publicar(tmp_path, "com_chaves", [*sia_pa, cobertura], chaves=chaves)
    assert _exclusoes(sem) == {}
    assert _exclusoes(com) == {"versoes_concorrentes": 3}
    sem_deteccao = metrica(sem, "fracao_registros_incluidos")
    assert (sem_deteccao.numerador, sem_deteccao.denominador) == (4, 4)
    com_deteccao = metrica(com, "fracao_registros_incluidos")
    assert (com_deteccao.numerador, com_deteccao.denominador) == (1, 4)
    assert sem.report_id != com.report_id


def test_competencias_das_linhas_excluidas_ficam_incompletas_na_disponibilidade(
    tmp_path: Path,
) -> None:
    sia_pa, chaves = _versoes_publicadas(tmp_path)
    cobertura = cobertura_sintetica(tmp_path, sia_pa, ("201712", "201801", "201802"))
    relatorio = _publicar(tmp_path, "relatorio", [*sia_pa, cobertura], chaves=chaves)
    motivos: dict[str, set[str]] = {}
    for linha in linhas_tabela(relatorio, "piloto_disponibilidade.v1"):
        motivos.setdefault(str(linha["competencia"]), set()).add(str(linha["motivo"]))
    for competencia in ("201712", "201801"):
        marca = (
            f"sia_pa_incompleto competencia={competencia} "
            "motivo=versoes_concorrentes competencia_arquivo=201801 partes=a"
        )
        assert all(motivo.startswith(marca) for motivo in motivos[competencia])
    assert not any("versoes_concorrentes" in motivo for motivo in motivos["201802"])
