"""Saídas da execução refeita contra as da registrada, pela união dos `schema_id` (T14).

Os Parquet são sintéticos (`agregados_registro.v1`); a saída que só uma das pontas traz usa uma
referência sem arquivo, porque a divergência de emissão não lê o conteúdo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.reporting.reproduce_comparacao import Situacao, comparar_saidas
from tests.fixtures.reproducao_parquet import SCHEMA, gravar, linha

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef

LINHAS = [linha("run_a", f"art_{i}#0") for i in range(4)]
EVIDENCIAS = "evidencias.v1"
FALHAS = "falhas.v1"


def _com_run(run_id: str) -> list[dict[str, str]]:
    return [{**item, "run_id": run_id} for item in LINHAS]


def _saida(tmp_path: Path, pasta: str, run_id: str) -> DatasetRef:
    return gravar(_com_run(run_id), tmp_path / pasta / "s.parquet")


def _sem_arquivo(tmp_path: Path, schema_id: str) -> DatasetRef:
    return _saida(tmp_path, "sem_arquivo", "run_x").model_copy(update={"schema_id": schema_id})


def test_saidas_iguais_de_execucoes_com_outro_run_id_sao_iguais(tmp_path: Path) -> None:
    originais = {SCHEMA: _saida(tmp_path, "original", "run_a")}
    refeitas = {SCHEMA: _saida(tmp_path, "refeito", "run_b")}
    (item,) = comparar_saidas("M_TEMP", originais, refeitas)
    assert item.item == f"saida:M_TEMP:{SCHEMA}"
    assert item.situacao is Situacao.IGUAL


def test_saida_original_que_a_reconstrucao_nao_emitiu_e_divergente(tmp_path: Path) -> None:
    originais = {
        SCHEMA: _saida(tmp_path, "original", "run_a"),
        EVIDENCIAS: _sem_arquivo(tmp_path, EVIDENCIAS),
    }
    refeitas = {SCHEMA: _saida(tmp_path, "refeito", "run_b")}
    itens = {i.item: i for i in comparar_saidas("B_ATEND", originais, refeitas)}
    assert set(itens) == {f"saida:B_ATEND:{SCHEMA}", f"saida:B_ATEND:{EVIDENCIAS}"}
    assert itens[f"saida:B_ATEND:{SCHEMA}"].situacao is Situacao.IGUAL
    ausente = itens[f"saida:B_ATEND:{EVIDENCIAS}"]
    assert ausente.situacao is Situacao.DIVERGENTE
    assert ausente.detalhe == "saida_ausente_no_refeito"
    assert (ausente.esperado, ausente.obtido) == (None, None)


def test_saida_nova_sem_original_na_execucao_registrada_e_divergente(tmp_path: Path) -> None:
    originais = {SCHEMA: _saida(tmp_path, "original", "run_a")}
    refeitas = {
        SCHEMA: _saida(tmp_path, "refeito", "run_b"),
        FALHAS: _sem_arquivo(tmp_path, FALHAS),
    }
    itens = {i.item: i for i in comparar_saidas("B_PROC", originais, refeitas)}
    nova = itens[f"saida:B_PROC:{FALHAS}"]
    assert nova.situacao is Situacao.DIVERGENTE
    assert nova.detalhe == "saida_sem_original"
    assert itens[f"saida:B_PROC:{SCHEMA}"].situacao is Situacao.IGUAL


def test_execucao_registrada_sem_nenhuma_saida_deixa_toda_saida_refeita_divergente(
    tmp_path: Path,
) -> None:
    refeitas = {SCHEMA: _saida(tmp_path, "refeito", "run_b")}
    (item,) = comparar_saidas("M_TEMP", {}, refeitas)
    assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, "saida_sem_original")


def test_sem_a_execucao_registrada_a_saida_refeita_e_inconclusiva_e_nao_divergente(
    tmp_path: Path,
) -> None:
    refeitas = {SCHEMA: _saida(tmp_path, "refeito", "run_b")}
    (item,) = comparar_saidas("M_TEMP", None, refeitas)
    assert (item.situacao, item.detalhe) == (Situacao.INCONCLUSIVO, "original_ausente")


def test_sem_a_execucao_refeita_toda_saida_registrada_e_divergente(tmp_path: Path) -> None:
    originais = {
        SCHEMA: _saida(tmp_path, "original", "run_a"),
        EVIDENCIAS: _sem_arquivo(tmp_path, EVIDENCIAS),
    }
    itens = comparar_saidas("M_TEMP", originais, None)
    assert {i.item for i in itens} == {f"saida:M_TEMP:{SCHEMA}", f"saida:M_TEMP:{EVIDENCIAS}"}
    assert {(i.situacao, i.detalhe) for i in itens} == {
        (Situacao.DIVERGENTE, "saida_ausente_no_refeito")
    }


def test_itens_seguem_a_ordem_das_saidas_refeitas_e_depois_as_so_registradas(
    tmp_path: Path,
) -> None:
    originais = {
        EVIDENCIAS: _sem_arquivo(tmp_path, EVIDENCIAS),
        SCHEMA: _saida(tmp_path, "original", "run_a"),
    }
    refeitas = {
        FALHAS: _sem_arquivo(tmp_path, FALHAS),
        SCHEMA: _saida(tmp_path, "refeito", "run_b"),
    }
    nomes = [i.item for i in comparar_saidas("M_TEMP", originais, refeitas)]
    assert nomes == [f"saida:M_TEMP:{s}" for s in (FALHAS, SCHEMA, EVIDENCIAS)]


def test_sem_nenhuma_das_duas_execucoes_nao_ha_item() -> None:
    assert comparar_saidas("M_TEMP", None, None) == []
