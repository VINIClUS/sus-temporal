"""`validate --ingest`: seleção INCOMPLETA do SIA-PA vira marca `sia_pa_incompleto` (SINTETICO)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from sustemporal import cli
from sustemporal.contracts.experiment import RunResult
from sustemporal.errors import ExitCode
from tests.fixtures.regras_ingest import montar_ingest

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef
    from tests.fixtures.regras_ingest import MundoIngest

_ESTAB_CBO = "ESTABELECIMENTO_CBO"
_MARCA_PARTE = "sia_pa_incompleto competencia=202302 motivo=selecao_incompleta partes_ausentes"


def _executar(mundo: MundoIngest) -> RunResult:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    argumentos += ["--ingest", str(mundo.pasta), "--saida", str(mundo.saida)]
    assert cli.main(argumentos) == ExitCode.OK
    (caminho,) = mundo.saida.glob("*/run_result.json")
    return RunResult.model_validate_json(caminho.read_text(encoding="utf-8"))


def _linhas(refs: Iterable[DatasetRef], schema_id: str) -> list[dict[str, Any]]:
    caminho = next(r.caminho for r in refs if r.schema_id == schema_id)
    linhas: list[dict[str, Any]] = pq.read_table(caminho).to_pylist()
    return linhas


def _celula(resultado: RunResult, competencia: str, base: str) -> dict[str, Any]:
    (celula,) = (
        c
        for c in _linhas(resultado.entradas, "cobertura.v1")
        if (c["familia_regra"], c["competencia"], c["base_temporal"])
        == (_ESTAB_CBO, competencia, base)
        and c["instrumento"] == "C"
    )
    return celula


def _estados(resultado: RunResult) -> dict[tuple[str, str], str]:
    avaliacoes = _linhas(resultado.saidas, "avaliacoes.v1")
    return {(a["row_id"], a["rule_id"]): a["estado"] for a in avaliacoes}


def test_parte_esperada_ausente_no_registro_deixa_a_competencia_insuficiente(
    tmp_path: Path,
) -> None:
    resultado = _executar(montar_ingest(tmp_path, sem_parte_b=True))
    celula = _celula(resultado, "202302", "PROCESSAMENTO")
    assert celula["estado"] == "INSUFICIENTE"
    assert str(celula["motivo"]).startswith(_MARCA_PARTE)


def test_linha_que_dependeria_da_parte_ausente_fica_inconclusiva_nunca_violacao(
    tmp_path: Path,
) -> None:
    resultado = _executar(montar_ingest(tmp_path, sem_parte_b=True))
    estados = _estados(resultado)
    cnes = [k for k in estados if k[1] == "ESTAB_CBO_CNES" and k[0].endswith("#0")]
    assert cnes
    assert {estados[k] for k in cnes} == {"INCONCLUSIVO"}
    assert "VIOLACAO" not in set(estados.values())


def test_competencia_de_processamento_trazida_pelo_arquivo_incompleto_tambem_e_marcada(
    tmp_path: Path,
) -> None:
    resultado = _executar(montar_ingest(tmp_path, sem_parte_b=True, linha_de_janeiro=True))
    celula = _celula(resultado, "202301", "ATENDIMENTO")
    assert celula["estado"] == "INSUFICIENTE"
    assert str(celula["motivo"]).startswith(
        "sia_pa_incompleto competencia=202301 motivo=incompleto_via_arquivo "
        "competencia_arquivo=202302"
    )


def test_partes_sem_declaracao_no_catalogo_deixam_a_competencia_insuficiente(
    tmp_path: Path,
) -> None:
    resultado = _executar(montar_ingest(tmp_path, partes_sem_declaracao=True))
    celula = _celula(resultado, "202302", "PROCESSAMENTO")
    assert celula["estado"] == "INSUFICIENTE"
    assert str(celula["motivo"]).startswith(
        "sia_pa_incompleto competencia=202302 motivo=selecao_incompleta "
        "partes_sem_declaracao completude=INDETERMINADA partes=a,b"
    )
