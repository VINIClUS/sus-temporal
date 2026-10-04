"""T04: recorte da ingestão por família configurada, UF e corte de observação (SINTETICO)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import (
    cobertura_ingest,
    config_ingest,
    fontes_ingest,
    resultados_ingest,
)
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.contracts import FamiliaFonte
from sustemporal.contracts.artifacts import calcular_artifact_id
from sustemporal.errors import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion

PF = FamiliaFonte.CNES_PF
CEDO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TARDE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _versoes(store: Path) -> dict[str, ArtifactVersion]:
    return {
        "pa": artefato_pa(store, dbc_pa([registro("C", "201801", "201801")])),
        "sigtap": artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        "pf": artefato_cnes(store, dbc_cnes(PF, [registro_pf("0012345", "225125")]), PF),
    }


def _sem_uf(versao: ArtifactVersion) -> ArtifactVersion:
    chave = versao.chave.model_copy(update={"uf": None})
    return versao.model_copy(
        update={"chave": chave, "artifact_id": calcular_artifact_id(chave, versao.sha256)}
    )


def _manifesto(pasta: Path) -> Path:
    (pasta / "manifestos").mkdir(parents=True, exist_ok=True)
    return pasta / "manifestos" / "aquisicao.jsonl"


def _rodar(pasta: Path, **opcoes: str) -> None:
    config = config_ingest(pasta, fontes_ingest(pasta, ["a"]), **opcoes)
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK


def test_familia_fora_da_configuracao_nao_entra(tmp_path: Path) -> None:
    registrar_versoes(_manifesto(tmp_path), _versoes(tmp_path / "dados" / "raw").values())
    _rodar(tmp_path, familias="SIA_PA, CNES_PF")
    sigtap = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "SIGTAP"]
    assert {(r["estado"], r.get("familia")) for r in sigtap} == {("FORA_DO_RECORTE", "SIGTAP")}
    assert cobertura_ingest(tmp_path)[("VIGENCIA_PROCEDIMENTO", "PROCESSAMENTO")] == "AUSENTE"


def test_familia_regional_sem_uf_fica_fora_com_motivo(tmp_path: Path) -> None:
    versoes = _versoes(tmp_path / "dados" / "raw")
    versoes["pf"] = _sem_uf(versoes["pf"])
    registrar_versoes(_manifesto(tmp_path), versoes.values())
    _rodar(tmp_path)
    (pf,) = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "CNES_PF"]
    assert (pf["estado"], pf.get("motivo")) == (
        "FORA_DO_RECORTE",
        "uf_ausente_em_familia_regional",
    )
    assert cobertura_ingest(tmp_path)[("ESTABELECIMENTO_CBO", "PROCESSAMENTO")] == "AUSENTE"


def test_versao_observada_so_depois_do_corte_nao_entra(tmp_path: Path) -> None:
    versoes = _versoes(tmp_path / "dados" / "raw")
    manifesto = _manifesto(tmp_path)
    registrar_versoes(manifesto, [versoes["sigtap"], versoes["pf"]], observado_em=CEDO)
    registrar_versoes(manifesto, [versoes["pa"]], observado_em=TARDE)
    _rodar(tmp_path, corte="2026-09-15T00:00:00Z")
    (pa,) = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "SIA_PA"]
    assert pa["estado"] == "FORA_DO_CORTE"
    assert pa.get("primeira_observacao", "").startswith("2026-10-01")
    assert "DISPONIVEL" not in set(cobertura_ingest(tmp_path).values())


def test_sem_corte_as_mesmas_versoes_entram(tmp_path: Path) -> None:
    versoes = _versoes(tmp_path / "dados" / "raw")
    manifesto = _manifesto(tmp_path)
    registrar_versoes(manifesto, [versoes["sigtap"], versoes["pf"]], observado_em=CEDO)
    registrar_versoes(manifesto, [versoes["pa"]], observado_em=TARDE)
    _rodar(tmp_path)
    assert {r["estado"] for r in resultados_ingest(tmp_path)} == {"NORMALIZADO"}
    assert cobertura_ingest(tmp_path)[("VIGENCIA_PROCEDIMENTO", "PROCESSAMENTO")] == "DISPONIVEL"
