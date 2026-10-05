"""T04: recorte da ingestão por família configurada, UF e corte de observação (SINTETICO)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import (
    cobertura_ingest,
    config_ingest,
    fontes_ingest,
    motivos_ingest,
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
    from sustemporal.contracts import ArtifactVersion

PF = FamiliaFonte.CNES_PF
LEIAUTE_PA = Path(__file__).resolve().parents[2] / "catalog" / "layouts" / "sia_pa.yaml"
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


def _rodar(pasta: Path, **opcoes: Any) -> None:
    config = config_ingest(pasta, fontes_ingest(pasta, ["a"]), **opcoes)
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK


def test_familia_fora_da_configuracao_nao_entra(tmp_path: Path) -> None:
    registrar_versoes(_manifesto(tmp_path), _versoes(tmp_path / "dados" / "raw").values())
    _rodar(tmp_path, familias="SIA_PA, CNES_PF")
    sigtap = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "SIGTAP"]
    assert {(r["estado"], r.get("motivo")) for r in sigtap} == {
        ("FORA_DO_RECORTE", "familia_nao_configurada")
    }
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


def test_parte_incompleta_rebaixa_tambem_a_competencia_de_processamento_dos_registros(
    tmp_path: Path,
) -> None:
    store = tmp_path / "dados" / "raw"
    registros = [registro("C", "201801", "201801"), registro("C", "201802", "201802")]
    versoes = [
        artefato_pa(store, dbc_pa(registros)),
        artefato_pa(store, dbc_pa(registros, truncar_bytes=30), parte="b"),
        artefato_sigtap(store, zip_sigtap(pacote_padrao("201801")), competencia="201801"),
        artefato_sigtap(store, zip_sigtap(pacote_padrao("201802")), competencia="201802"),
    ]
    registrar_versoes(_manifesto(tmp_path), versoes)
    _rodar(tmp_path, competencias='"201801", "201802"')
    estados = cobertura_ingest(tmp_path, competencia="201802")
    assert estados[("VIGENCIA_PROCEDIMENTO", "PROCESSAMENTO")] != "DISPONIVEL"
    motivos = motivos_ingest(tmp_path, "201802")
    assert any("incompleto_via_arquivo competencia_arquivo=201801" in m for m in motivos)
    (pa,) = [
        r
        for r in resultados_ingest(tmp_path)
        if r["fonte"] == "SIA_PA" and r["estado"] == "NORMALIZADO"
    ]
    assert pa.get("diagnostico") == "competencia_processamento_divergente_do_arquivo n=1"


def test_sem_divergencia_de_competencia_nao_ha_diagnostico(tmp_path: Path) -> None:
    registrar_versoes(_manifesto(tmp_path), _versoes(tmp_path / "dados" / "raw").values())
    _rodar(tmp_path)
    (pa,) = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "SIA_PA"]
    assert "diagnostico" not in pa


def test_familia_nacional_com_uf_fica_fora_com_motivo(tmp_path: Path) -> None:
    versoes = _versoes(tmp_path / "dados" / "raw")
    sigtap = versoes["sigtap"]
    chave = sigtap.chave.model_copy(update={"uf": "SP"})
    versoes["sigtap"] = sigtap.model_copy(
        update={"chave": chave, "artifact_id": calcular_artifact_id(chave, sigtap.sha256)}
    )
    registrar_versoes(_manifesto(tmp_path), versoes.values())
    _rodar(tmp_path)
    estados = {
        (r["estado"], r.get("motivo"))
        for r in resultados_ingest(tmp_path)
        if r["fonte"] == "SIGTAP"
    }
    assert estados == {("FORA_DO_RECORTE", "uf_em_familia_nacional")}


def test_leiaute_do_sia_pa_vem_da_configuracao(tmp_path: Path) -> None:
    registrar_versoes(_manifesto(tmp_path), _versoes(tmp_path / "dados" / "raw").values())
    leiaute = tmp_path / "sia_pa_leiaute.yaml"
    texto = LEIAUTE_PA.read_text(encoding="utf-8")
    assert "proveniencia: INFERIDA\n" in texto
    leiaute.write_text(
        texto.replace(
            "proveniencia: INFERIDA\n", 'proveniencia: INFERIDA\nvalido_de: "201901"\n', 1
        ),
        encoding="utf-8",
    )
    _rodar(tmp_path, leiaute_pa=leiaute)
    (pa,) = [r for r in resultados_ingest(tmp_path) if r["fonte"] == "SIA_PA"]
    assert pa["estado"] == "QUARENTENA_LEIAUTE"
    assert "leiaute_fora_da_vigencia" in pa["motivo"]
