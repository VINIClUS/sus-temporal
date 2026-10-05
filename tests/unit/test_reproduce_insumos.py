"""Insumos auxiliares congelados: entradas originais e disponibilidade dos artefatos (T14).

O manifesto guarda só a identidade (hash) de cada campo da entrada de validação; os artefatos dos
auxiliares vêm da `entrada_validacao.json` original da política (`<raiz_saidas>/split/insumos`),
que só vale se tem a identidade congelada. Os conjuntos não têm arquivo: a conferência só lê ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.evaluation.freeze_entrada import identidades_da_entrada
from sustemporal.reporting.reproduce_comparacao import (
    Comparacao,
    Situacao,
    comparar_auxiliares,
    observacoes_dos_insumos,
)
from sustemporal.reporting.reproduce_etapas import entradas_congeladas
from tests.fixtures.protocolo_dados import artefato
from tests.fixtures.protocolo_insumos import conjunto_sintetico, entrada_da_politica

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.rules.entrada import EntradaValidacao

A1, A2, A3 = (artefato(nome) for nome in ("a1", "a2", "a3"))
NORMALIZADO = "NORMALIZADO"
POLITICA = "B_ATEND"


def _conjunto(esquema: str, *artefatos: str) -> DatasetRef:
    base = conjunto_sintetico(esquema, "v1")
    ids = tuple(sorted(artefatos))
    novo = calcular_dataset_id(esquema, base.hash_logico, ids)
    return base.model_copy(update={"artifact_ids": ids, "dataset_id": novo})


def _entrada(
    *auxiliares: DatasetRef, politica: str = POLITICA, **mudancas: object
) -> EntradaValidacao:
    teste = conjunto_sintetico("sia_pa.v1", "teste")
    entrada = entrada_da_politica(teste, politica)
    return entrada.model_copy(update={"auxiliares": auxiliares, **mudancas})


def _inconclusivo(entrada: EntradaValidacao, estados: dict[str, str]) -> Comparacao:
    (comparacao,) = comparar_auxiliares({POLITICA: entrada}, estados)
    assert comparacao.situacao is Situacao.INCONCLUSIVO
    assert (comparacao.esperado, comparacao.obtido) == (None, None)
    return comparacao


def test_auxiliares_normalizados_no_ingest_refeito_nao_geram_item() -> None:
    entrada = _entrada(
        _conjunto("cnes_estab_cbo.v1", A1, A2), _conjunto("sigtap_procedimento.v1", A3)
    )
    estados = {A1: NORMALIZADO, A2: NORMALIZADO, A3: NORMALIZADO}
    assert comparar_auxiliares({POLITICA: entrada}, estados) == []


def test_auxiliar_cujo_arquivo_original_falta_torna_a_politica_inconclusiva() -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1, A2))
    item = _inconclusivo(entrada, {A1: NORMALIZADO, A2: "ARQUIVOAUSENTE"})
    assert item.item == f"insumos:{POLITICA}"
    assert item.detalhe == "originais_indisponiveis artefatos=1 estados=ARQUIVOAUSENTE"


def test_artefato_indisponivel_so_no_segundo_conjunto_auxiliar_tambem_conta() -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1), _conjunto("sigtap_procedimento.v1", A2))
    item = _inconclusivo(entrada, {A1: NORMALIZADO, A2: "QUARENTENA_TRUNCADO"})
    assert item.detalhe == "originais_indisponiveis artefatos=1 estados=QUARENTENA_TRUNCADO"


def test_artefato_que_o_ingest_nem_listou_conta_como_indisponivel() -> None:
    entrada = _entrada(_conjunto("sigtap_procedimento.v1", A1))
    item = _inconclusivo(entrada, {})
    assert item.detalhe == "originais_indisponiveis artefatos=1 estados=AUSENTE_DO_INGEST"


def test_quarentena_e_truncamento_valem_como_ausencia_e_o_artefato_repetido_conta_uma_vez() -> None:
    entrada = _entrada(
        _conjunto("sigtap_procedimento.v1", A1, A2), _conjunto("sigtap_proc_registro.v1", A1, A2)
    )
    estados = {A1: "QUARENTENA_TRUNCADO", A2: "ARQUIVOAUSENTE"}
    item = _inconclusivo(entrada, estados)
    assert item.detalhe == (
        "originais_indisponiveis artefatos=2 estados=ARQUIVOAUSENTE,QUARENTENA_TRUNCADO"
    )


def test_so_os_auxiliares_contam_a_cobertura_e_a_selecao_ficam_para_as_outras_conferencias() -> (
    None
):
    cobertura = _conjunto("cobertura.v1", A2, A3)
    selecao = _conjunto("selecao_versoes.v1", A3)
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1), cobertura=cobertura, selecoes=selecao)
    assert comparar_auxiliares({POLITICA: entrada}, {A1: NORMALIZADO}) == []


def test_um_item_por_politica_afetada_na_ordem_do_id() -> None:
    afetada = _entrada(_conjunto("cnes_estab_cbo.v1", A1), politica="B_PROC")
    outra = _entrada(_conjunto("cnes_estab_cbo.v1", A1), politica="M_TEMP_PADRAO")
    integra = _entrada(_conjunto("cnes_estab_cbo.v1", A2), politica=POLITICA)
    entradas = {"m_temp": outra, "b_proc": afetada, "b_atend": integra}
    itens = comparar_auxiliares(entradas, {A1: "ARQUIVOAUSENTE", A2: NORMALIZADO})
    assert [i.item for i in itens] == ["insumos:b_proc", "insumos:m_temp"]


def _congelada(tmp_path: Path, entrada: EntradaValidacao) -> dict[str, dict[str, str]]:
    pasta = tmp_path / "insumos"
    pasta.mkdir(exist_ok=True)
    (pasta / f"{POLITICA}.json").write_text(entrada.model_dump_json(), encoding="utf-8")
    return {POLITICA: identidades_da_entrada(entrada)}


def test_entrada_original_com_a_identidade_congelada_e_lida(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1, A2))
    congeladas = _congelada(tmp_path, entrada)
    assert entradas_congeladas(tmp_path / "insumos", congeladas) == {POLITICA: entrada}


def test_entrada_original_ausente_fica_de_fora(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    assert (
        entradas_congeladas(tmp_path / "insumos", {POLITICA: identidades_da_entrada(entrada)}) == {}
    )


@pytest.mark.parametrize("conteudo", [b'{"dataset": ', b"[]", b"\xff\xfe nao e utf-8"])
def test_entrada_original_ilegivel_fica_de_fora(tmp_path: Path, conteudo: bytes) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = _congelada(tmp_path, entrada)
    (tmp_path / "insumos" / f"{POLITICA}.json").write_bytes(conteudo)
    assert entradas_congeladas(tmp_path / "insumos", congeladas) == {}


def test_entrada_original_alterada_depois_do_congelamento_fica_de_fora(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = _congelada(tmp_path, entrada)
    outra = _entrada(_conjunto("cnes_estab_cbo.v1", A1, A2))
    (tmp_path / "insumos" / f"{POLITICA}.json").write_text(
        outra.model_dump_json(), encoding="utf-8"
    )
    assert entradas_congeladas(tmp_path / "insumos", congeladas) == {}


def test_so_a_politica_com_a_entrada_conferida_entra_e_o_resto_segue(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = {**_congelada(tmp_path, entrada), "b_proc": identidades_da_entrada(entrada)}
    assert set(entradas_congeladas(tmp_path / "insumos", congeladas)) == {POLITICA}


def test_politicas_com_entrada_original_conferida_nao_geram_observacao() -> None:
    assert observacoes_dos_insumos(["a", "b"], ["b", "a"]) == []
    assert observacoes_dos_insumos([], []) == []


def test_observacao_lista_as_politicas_sem_entrada_original_conferida_em_ordem() -> None:
    observacoes = observacoes_dos_insumos(["b_proc", "m_temp", "b_atend"], ["m_temp"])
    assert observacoes == ["insumos_originais_nao_conferidos politicas=b_atend,b_proc"]
