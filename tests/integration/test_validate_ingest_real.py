"""`sustemporal ingest` real seguido de `validate --ingest` sobre a pasta gerada (SINTETICO)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.contracts import FamiliaFonte, RunResult
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.errors import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

_FORA_DO_DRS_XI = "355030"


def _preparar(pasta: Path) -> Path:
    store = pasta / "dados" / "raw"
    registros = [
        registro("C", "201801", "201801"),
        registro("C", "201801", "201801", PA_UFMUN=_FORA_DO_DRS_XI),
    ]
    pf = [registro_pf("0012345", "225125")]
    versoes = [
        artefato_pa(store, dbc_pa(registros)),
        artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        artefato_cnes(store, dbc_cnes(FamiliaFonte.CNES_PF, pf), FamiliaFonte.CNES_PF),
    ]
    (pasta / "manifestos").mkdir(parents=True)
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)
    return config_ingest(pasta, fontes_ingest(pasta, None))


def test_validate_sobre_a_pasta_do_ingest_real(tmp_path: Path) -> None:
    config = _preparar(tmp_path)
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    (execucao,) = sorted((tmp_path / "saidas" / "ingest").iterdir())
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    assert cli.main([*argumentos, "--ingest", str(execucao)]) == ExitCode.OK
    (gravado,) = sorted((tmp_path / "saidas" / "runs").glob("*/run_result.json"))
    resultado = RunResult.model_validate_json(gravado.read_text(encoding="utf-8"))
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    recorte = json.loads((gravado.parent / "recorte_territorial.json").read_text("utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1}
    avaliacoes_ref = next(s for s in resultado.saidas if s.schema_id == "avaliacoes.v1")
    avaliacoes = pq.read_table(avaliacoes_ref.caminho).to_pylist()
    assert avaliacoes
    assert len({a["row_id"] for a in avaliacoes}) == 1
