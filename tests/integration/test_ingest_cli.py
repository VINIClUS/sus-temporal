"""T04: `sustemporal ingest` sobre manifesto e armazenamento locais sintéticos (SINTETICO)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf, registro_st
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.contracts import ArtifactVersion, DatasetRef, FamiliaFonte, OrigemDados
from sustemporal.errors import ExitCode

DRS_XI = Path(__file__).resolve().parents[2] / "catalog" / "territorio" / "drs_xi.yaml"
PF = FamiliaFonte.CNES_PF


def _versoes(store: Path) -> list[ArtifactVersion]:
    registros = [registro("C", "201801", "201801"), registro("I", "201801", "201712")]
    pf = [registro_pf("0012345", "225125"), registro_pf("0012345", "2231F9")]
    return [
        artefato_pa(store, dbc_pa(registros)),
        artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        artefato_cnes(store, dbc_cnes(PF, pf), PF),
        artefato_cnes(store, dbc_cnes(PF, pf), FamiliaFonte.CNES_SR),
        artefato_cnes(
            store,
            dbc_cnes(FamiliaFonte.CNES_ST, [registro_st("0012345")], truncar_bytes=10),
            FamiliaFonte.CNES_ST,
        ),
    ]


def _config(pasta: Path, *, territorio: Path = DRS_XI, piloto: bool = True) -> Path:
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        "runtime:",
        f"  raiz_dados: {pasta / 'dados'}",
        f"  raiz_manifestos: {pasta / 'manifestos'}",
        f"  raiz_saidas: {pasta / 'saidas'}",
        "  duckdb_memoria: 256MB",
        '  duckdb_threads: "1"',
    ]
    if piloto:
        linhas += [
            "piloto:",
            "  uf: SP",
            '  competencias_processamento: ["201801"]',
            f"  territorio: {territorio}",
            "  familias_fontes: [SIA_PA, CNES_PF, CNES_ST, CNES_SR, SIGTAP]",
        ]
    caminho = pasta / "ingest.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def _preparar(pasta: Path) -> Path:
    versoes = _versoes(pasta / "dados" / "raw")
    (pasta / "manifestos").mkdir(parents=True)
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)
    return _config(pasta)


def _jsonl(caminho: Path) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def executado(tmp_path: Path) -> Path:
    assert cli.main(["ingest", "--config", str(_preparar(tmp_path))]) == ExitCode.OK
    return tmp_path / "saidas" / "ingest"


def test_ingest_produz_conjuntos_canonicos_e_cobertura(executado: Path) -> None:
    datasets = [DatasetRef.model_validate(x) for x in _jsonl(executado / "datasets.jsonl")]
    assert sorted(d.schema_id for d in datasets) == [
        "cnes_estab_cbo.v1",
        "cobertura.v1",
        "sia_pa.v1",
        "sigtap_proc_ocupacao.v1",
        "sigtap_proc_registro.v1",
        "sigtap_procedimento.v1",
        "sigtap_registro.v1",
    ]
    assert {d.origem_dados for d in datasets} == {OrigemDados.SINTETICO}
    assert all(Path(d.caminho).is_file() for d in datasets)


def test_ingest_registra_reservada_e_quarentena_sem_tabela(executado: Path) -> None:
    resultados = {(x["fonte"], x["estado"]) for x in _jsonl(executado / "resultados.jsonl")}
    assert ("CNES_SR", "FAMILIA_RESERVADA") in resultados
    assert any(
        fonte == "CNES_ST" and estado.startswith("QUARENTENA_") for fonte, estado in resultados
    )
    assert ("SIA_PA", "NORMALIZADO") in resultados


def test_ingest_sem_piloto_e_config_invalida(tmp_path: Path) -> None:
    assert cli.main(["ingest", "--config", str(_config(tmp_path, piloto=False))]) == (
        ExitCode.CONFIG_INVALIDA
    )


def test_ingest_com_territorio_invalido_e_config_invalida(tmp_path: Path) -> None:
    ruim = tmp_path / "territorio.yaml"
    ruim.write_text(DRS_XI.read_text(encoding="utf-8").replace("ibge7: 3514403", "ibge7: 3514404"))
    assert cli.main(["ingest", "--config", str(_config(tmp_path, territorio=ruim))]) == (
        ExitCode.CONFIG_INVALIDA
    )
