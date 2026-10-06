"""Insumos auxiliares congelados: entradas originais e disponibilidade dos artefatos (T14).

O manifesto guarda só a identidade (hash) de cada campo da entrada de validação; os artefatos dos
auxiliares vêm da `entrada_validacao.json` original da política (`<raiz_saidas>/split/insumos`),
que só vale se tem a identidade congelada. A entrada ausente, ilegível ou alterada é problema da
política (inconclusão), nunca entrada que se ignora. Os conjuntos não têm arquivo: a conferência
só lê ids.
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
    comparar_entradas_originais,
)
from sustemporal.reporting.reproduce_etapas import conferir_entradas
from sustemporal.temporal.politicas import carregar_politica
from tests.fixtures.protocolo_dados import artefato
from tests.fixtures.protocolo_insumos import conjunto_sintetico, entrada_da_politica

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.rules.entrada import EntradaValidacao

A1, A2, A3 = (artefato(nome) for nome in ("a1", "a2", "a3"))
NORMALIZADO = "NORMALIZADO"
POLITICA = "B_ATEND"
AUSENTE = "entrada_original_ausente"
ILEGIVEL = "entrada_original_ilegivel"
ALTERADA = "entrada_original_alterada"


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
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert resultado.conferidas == {POLITICA: entrada}
    assert resultado.problemas == {}


def test_entrada_original_ausente_e_problema_da_politica_e_nao_some(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    resultado = conferir_entradas(tmp_path / "insumos", {POLITICA: identidades_da_entrada(entrada)})
    assert resultado.conferidas == {}
    assert resultado.problemas == {POLITICA: AUSENTE}


def test_pasta_com_outra_politica_deixa_ausente_a_que_falta(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = {**_congelada(tmp_path, entrada), "b_proc": identidades_da_entrada(entrada)}
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert set(resultado.conferidas) == {POLITICA}
    assert resultado.problemas == {"b_proc": AUSENTE}


@pytest.mark.parametrize("conteudo", [b'{"dataset": ', b"[]", b"\xff\xfe nao e utf-8"])
def test_entrada_original_ilegivel_e_problema_da_politica(tmp_path: Path, conteudo: bytes) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = _congelada(tmp_path, entrada)
    (tmp_path / "insumos" / f"{POLITICA}.json").write_bytes(conteudo)
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert resultado.conferidas == {}
    assert resultado.problemas == {POLITICA: ILEGIVEL}


def test_entrada_original_que_nao_pode_ser_aberta_e_ilegivel_e_nao_ausente(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = _congelada(tmp_path, entrada)
    arquivo = tmp_path / "insumos" / f"{POLITICA}.json"
    arquivo.unlink()
    arquivo.mkdir()
    assert conferir_entradas(tmp_path / "insumos", congeladas).problemas == {POLITICA: ILEGIVEL}


def test_entrada_original_alterada_depois_do_congelamento_e_problema_da_politica(
    tmp_path: Path,
) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = _congelada(tmp_path, entrada)
    outra = _entrada(_conjunto("cnes_estab_cbo.v1", A1, A2))
    (tmp_path / "insumos" / f"{POLITICA}.json").write_text(
        outra.model_dump_json(), encoding="utf-8"
    )
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert resultado.conferidas == {}
    assert resultado.problemas == {POLITICA: ALTERADA}


def test_entrada_sem_a_politica_resolvida_confere_pela_politica_do_catalogo(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    assert entrada.politica is None
    congeladas = _congelada(tmp_path, entrada)
    congeladas[POLITICA]["politica"] = "hash-da-politica-do-catalogo"
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert resultado.conferidas == {POLITICA: entrada}
    assert resultado.problemas == {}


def test_entrada_com_a_politica_resolvida_diferente_da_congelada_e_alterada(
    tmp_path: Path,
) -> None:
    politica = carregar_politica("M_TEMP_PADRAO")
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1)).model_copy(update={"politica": politica})
    congeladas = _congelada(tmp_path, entrada)
    congeladas[POLITICA]["politica"] = "hash-de-outra-politica"
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert resultado.conferidas == {}
    assert resultado.problemas == {POLITICA: ALTERADA}


def test_cada_politica_tem_a_sua_conferencia_e_o_resto_segue(tmp_path: Path) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    outra = _entrada(_conjunto("cnes_estab_cbo.v1", A2))
    congeladas = {
        **_congelada(tmp_path, entrada),
        "b_proc": identidades_da_entrada(outra),
        "m_temp": identidades_da_entrada(outra),
    }
    (tmp_path / "insumos" / "b_proc.json").write_text(entrada.model_dump_json(), encoding="utf-8")
    resultado = conferir_entradas(tmp_path / "insumos", congeladas)
    assert set(resultado.conferidas) == {POLITICA}
    assert resultado.problemas == {"b_proc": ALTERADA, "m_temp": AUSENTE}


def test_cada_entrada_que_nao_confere_deixa_uma_linha_de_log_com_o_motivo(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entrada = _entrada(_conjunto("cnes_estab_cbo.v1", A1))
    congeladas = {**_congelada(tmp_path, entrada), "b_proc": identidades_da_entrada(entrada)}
    with caplog.at_level("WARNING", logger="sustemporal.reporting.reproduce_etapas"):
        conferir_entradas(tmp_path / "insumos", congeladas)
    assert [r.getMessage() for r in caplog.records] == [
        f"entrada_original_nao_conferida politica=b_proc motivo={AUSENTE}"
    ]


def test_politica_com_entrada_nao_conferida_vira_item_inconclusivo_com_o_motivo() -> None:
    itens = comparar_entradas_originais(
        {"b_proc": ALTERADA, "b_atend": AUSENTE, "m_temp": ILEGIVEL}
    )
    assert itens == [
        Comparacao("insumos:b_atend", Situacao.INCONCLUSIVO, None, None, AUSENTE),
        Comparacao("insumos:b_proc", Situacao.INCONCLUSIVO, None, None, ALTERADA),
        Comparacao("insumos:m_temp", Situacao.INCONCLUSIVO, None, None, ILEGIVEL),
    ]


def test_sem_problema_nas_entradas_originais_nao_ha_item() -> None:
    assert comparar_entradas_originais({}) == []
