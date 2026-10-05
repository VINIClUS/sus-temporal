"""Comparação do refeito com o congelado por hash lógico, contagens e métricas (T14).

Os Parquet são sintéticos (`agregados_registro.v1`); o hash lógico declarado vem da referência em
Python puro, independente do caminho de produção que o comparador usa.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.evaluation import IntervaloConfianca, ValorMetrica
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.freeze_entrada import identidades_da_entrada
from sustemporal.reporting.reproduce_comparacao import (
    Comparacao,
    Situacao,
    comparar_insumos,
    comparar_metricas,
    comparar_referencia,
    comparar_saida,
    exigir_conferido,
    identidade_do_arquivo,
    resultado_geral,
)
from tests.fixtures.protocolo_insumos import entrada_da_politica
from tests.fixtures.reproducao_parquet import SCHEMA, gravar, linha

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef

LINHAS = [
    linha("run_a", f"art_{i}#0", "ALERTA" if i % 2 else "SEM_VIOLACAO_VERIFICADA") for i in range(6)
]


def _com_run(run_id: str) -> list[dict[str, str]]:
    return [{**item, "run_id": run_id} for item in LINHAS]


def test_identidade_confere_com_a_referencia_em_python_puro(tmp_path: Path) -> None:
    ref = gravar(LINHAS, tmp_path / "a.parquet")
    identidade = identidade_do_arquivo(tmp_path / "a.parquet", SCHEMA)
    assert (identidade.linhas, identidade.hash_logico) == (ref.linhas, ref.hash_logico)


def test_identidade_ignora_a_ordem_das_linhas_e_a_compressao_mas_nao_os_bytes(
    tmp_path: Path,
) -> None:
    gravar(LINHAS, tmp_path / "a.parquet", compressao="snappy")
    gravar(list(reversed(LINHAS)), tmp_path / "b.parquet", compressao="zstd")
    a = identidade_do_arquivo(tmp_path / "a.parquet", SCHEMA)
    b = identidade_do_arquivo(tmp_path / "b.parquet", SCHEMA)
    assert (a.linhas, a.hash_logico) == (b.linhas, b.hash_logico)
    assert a.sha256 != b.sha256


def test_identidade_sem_a_coluna_de_identidade_ignora_so_ela(tmp_path: Path) -> None:
    gravar(_com_run("run_a"), tmp_path / "a.parquet")
    gravar(_com_run("run_b"), tmp_path / "b.parquet")
    completa_a = identidade_do_arquivo(tmp_path / "a.parquet", SCHEMA)
    completa_b = identidade_do_arquivo(tmp_path / "b.parquet", SCHEMA)
    sem_a = identidade_do_arquivo(tmp_path / "a.parquet", SCHEMA, sem_colunas=("run_id",))
    sem_b = identidade_do_arquivo(tmp_path / "b.parquet", SCHEMA, sem_colunas=("run_id",))
    assert completa_a.hash_logico != completa_b.hash_logico
    assert sem_a.hash_logico == sem_b.hash_logico


def test_identidade_de_arquivo_ausente_ou_ilegivel_e_falha_operacional(tmp_path: Path) -> None:
    with pytest.raises(FalhaOperacionalErro, match="arquivo_ilegivel"):
        identidade_do_arquivo(tmp_path / "nao_existe.parquet", SCHEMA)
    (tmp_path / "lixo.parquet").write_bytes(b"isto nao e parquet")
    with pytest.raises(FalhaOperacionalErro, match="arquivo_ilegivel"):
        identidade_do_arquivo(tmp_path / "lixo.parquet", SCHEMA)


def test_refeito_com_o_mesmo_conteudo_e_os_mesmos_bytes_e_igual(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.IGUAL
    assert resultado.detalhe == ""
    assert resultado.esperado == resultado.obtido == f"6:{esperada.hash_logico}"


def test_bytes_diferentes_com_hash_logico_igual_sao_relatados_como_tais(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet", compressao="snappy")
    obtida = gravar(list(reversed(LINHAS)), tmp_path / "refeito" / "a.parquet", compressao="zstd")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.BYTES_DIFERENTES
    assert resultado.detalhe == "bytes_diferem"


def test_conteudo_refeito_diferente_do_declarado_e_divergente(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    alterado = [*LINHAS[:-1], linha("run_a", "art_5#0", "ABSTENCAO")]
    obtida = gravar(alterado, tmp_path / "refeito" / "a.parquet")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.detalhe == "refeito_diverge"
    assert resultado.esperado != resultado.obtido


def test_linha_a_menos_no_refeito_e_divergente_pela_contagem(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS[:-1], tmp_path / "refeito" / "a.parquet")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert (resultado.esperado or "").startswith("6:")
    assert (resultado.obtido or "").startswith("5:")


def test_contagem_declarada_diferente_da_refeita_e_divergente_mesmo_com_o_mesmo_hash(
    tmp_path: Path,
) -> None:
    refeita = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    declarada = gravar(LINHAS, tmp_path / "original" / "a.parquet").model_copy(update={"linhas": 7})
    resultado = comparar_referencia("conjunto:x", declarada, refeita)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.detalhe == "refeito_diverge"
    assert (resultado.esperado or "").startswith("7:")
    assert (resultado.obtido or "").startswith("6:")


def test_hash_do_refeito_e_recalculado_do_arquivo_e_nao_lido_da_referencia(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    adulterado = gravar(
        [*LINHAS[:-1], linha("run_a", "art_5#0", "ABSTENCAO")], tmp_path / "r.parquet"
    )
    mentirosa = adulterado.model_copy(
        update={"hash_logico": esperada.hash_logico, "dataset_id": esperada.dataset_id}
    )
    resultado = comparar_referencia("conjunto:x", esperada, mentirosa)
    assert resultado.situacao is Situacao.DIVERGENTE


def test_original_adulterado_e_divergente_e_nao_bytes_diferentes(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    gravar(
        [*LINHAS[:-1], linha("run_a", "art_5#0", "ABSTENCAO")], tmp_path / "original" / "a.parquet"
    )
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.detalhe == "original_diverge"


def test_original_ausente_compara_so_com_o_declarado_e_diz_que_os_bytes_nao_foram_vistos(
    tmp_path: Path,
) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    shutil.rmtree(tmp_path / "original")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.IGUAL
    assert resultado.detalhe == "original_ausente"


def test_original_ilegivel_compara_so_com_o_declarado_como_o_ausente(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    (tmp_path / "original" / "a.parquet").write_bytes(b"PAR1 truncado")
    resultado = comparar_referencia("conjunto:x", esperada, obtida)
    assert resultado.situacao is Situacao.IGUAL
    assert resultado.detalhe == "original_ilegivel"
    assert resultado.esperado == resultado.obtido == f"6:{esperada.hash_logico}"


def test_refeito_ilegivel_segue_sendo_falha_operacional(tmp_path: Path) -> None:
    esperada = gravar(LINHAS, tmp_path / "original" / "a.parquet")
    obtida = gravar(LINHAS, tmp_path / "refeito" / "a.parquet")
    (tmp_path / "refeito" / "a.parquet").write_bytes(b"PAR1 truncado")
    with pytest.raises(FalhaOperacionalErro, match=r"^arquivo_ilegivel caminho="):
        comparar_referencia("conjunto:x", esperada, obtida)


def test_saida_original_ilegivel_e_inconclusiva(tmp_path: Path) -> None:
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    obtida = gravar(_com_run("run_b"), tmp_path / "refeito" / "s.parquet")
    (tmp_path / "original" / "s.parquet").write_bytes(b"PAR1 truncado")
    resultado = comparar_saida("saida:x", original, obtida)
    assert resultado.situacao is Situacao.INCONCLUSIVO
    assert resultado.detalhe == "original_ilegivel"
    assert resultado.esperado is None


def test_saida_refeita_ilegivel_segue_sendo_falha_operacional(tmp_path: Path) -> None:
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    obtida = gravar(_com_run("run_b"), tmp_path / "refeito" / "s.parquet")
    (tmp_path / "refeito" / "s.parquet").write_bytes(b"PAR1 truncado")
    with pytest.raises(FalhaOperacionalErro, match=r"^arquivo_ilegivel caminho="):
        comparar_saida("saida:x", original, obtida)


def test_saida_com_outro_run_id_e_o_mesmo_conteudo_e_igual(tmp_path: Path) -> None:
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    obtida = gravar(_com_run("run_b"), tmp_path / "refeito" / "s.parquet")
    resultado = comparar_saida("saida:M_TEMP:agregados_registro.v1", original, obtida)
    assert resultado.situacao is Situacao.IGUAL
    assert resultado.detalhe == "sem_colunas=run_id"


def test_saida_com_resultado_diferente_e_divergente_mesmo_com_run_id_diferente(
    tmp_path: Path,
) -> None:
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    mudado = [*_com_run("run_b")[:-1], linha("run_b", "art_5#0", "ABSTENCAO")]
    obtida = gravar(mudado, tmp_path / "refeito" / "s.parquet")
    resultado = comparar_saida("saida:M_TEMP:agregados_registro.v1", original, obtida)
    assert resultado.situacao is Situacao.DIVERGENTE


def test_saida_pede_as_colunas_de_identidade_que_ignora(tmp_path: Path) -> None:
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    obtida = gravar(_com_run("run_b"), tmp_path / "refeito" / "s.parquet")
    resultado = comparar_saida("saida:x", original, obtida, sem_colunas=())
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.detalhe == "sem_colunas="


def test_saida_sem_original_ou_com_o_arquivo_ausente_e_inconclusiva(tmp_path: Path) -> None:
    obtida = gravar(_com_run("run_b"), tmp_path / "refeito" / "s.parquet")
    sem_ref = comparar_saida("saida:x", None, obtida)
    assert (sem_ref.situacao, sem_ref.detalhe) == (Situacao.INCONCLUSIVO, "original_ausente")
    original = gravar(_com_run("run_a"), tmp_path / "original" / "s.parquet")
    shutil.rmtree(tmp_path / "original")
    sem_arquivo = comparar_saida("saida:x", original, obtida)
    assert sem_arquivo.situacao is Situacao.INCONCLUSIVO


def _metrica(nome: str, numerador: int, denominador: int, **extras: object) -> ValorMetrica:
    valor = (Decimal(numerador) / Decimal(denominador)).quantize(Decimal("0.000001"))
    return ValorMetrica(
        nome=nome, numerador=numerador, denominador=denominador, valor=valor, **extras
    )


def test_metricas_iguais_em_outra_ordem_sao_iguais() -> None:
    a = [_metrica("m1", 1, 2), _metrica("m2", 3, 4)]
    b = [_metrica("m2", 3, 4), _metrica("m1", 1, 2)]
    resultado = comparar_metricas("metricas", a, b)
    assert resultado.situacao is Situacao.IGUAL
    assert resultado.esperado == resultado.obtido == "2"


def test_metrica_com_valor_diferente_e_divergente_e_nomeia_a_primeira() -> None:
    a = [_metrica("m1", 1, 2), _metrica("m2", 3, 4)]
    b = [_metrica("m1", 1, 2), _metrica("m2", 2, 4)]
    resultado = comparar_metricas("metricas", a, b)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert "diferentes=1" in resultado.detalhe
    assert "m2[TOTAL]" in resultado.detalhe


def test_intervalo_de_confianca_diferente_e_divergente() -> None:
    ic = IntervaloConfianca(inferior=Decimal("0.1"), superior=Decimal("0.9"))
    outro = IntervaloConfianca(inferior=Decimal("0.2"), superior=Decimal("0.9"))
    resultado = comparar_metricas(
        "m", [_metrica("m1", 1, 2, ic=ic)], [_metrica("m1", 1, 2, ic=outro)]
    )
    assert resultado.situacao is Situacao.DIVERGENTE


def test_metrica_que_falta_ou_sobra_e_divergente_com_as_contagens() -> None:
    a = [_metrica("m1", 1, 2), _metrica("m2", 3, 4)]
    resultado = comparar_metricas("metricas", a, [_metrica("m1", 1, 2), _metrica("m3", 1, 4)])
    assert resultado.situacao is Situacao.DIVERGENTE
    assert "faltando=1 sobrando=1" in resultado.detalhe
    assert (resultado.esperado, resultado.obtido) == ("2", "2")


def test_metrica_do_mesmo_nome_em_outro_estrato_nao_se_confunde() -> None:
    a = [_metrica("m1", 1, 2, estrato="competencia=202301")]
    b = [_metrica("m1", 1, 2, estrato="competencia=202302")]
    assert comparar_metricas("metricas", a, b).situacao is Situacao.DIVERGENTE


def test_metricas_sem_o_relatorio_original_sao_inconclusivas() -> None:
    resultado = comparar_metricas("metricas", None, [_metrica("m1", 1, 2)])
    assert (resultado.situacao, resultado.detalhe) == (Situacao.INCONCLUSIVO, "original_ausente")


def _teste(tmp_path: Path) -> DatasetRef:
    return gravar(LINHAS, tmp_path / "teste.parquet")


def test_insumos_com_a_identidade_congelada_sao_iguais(tmp_path: Path) -> None:
    entrada = entrada_da_politica(_teste(tmp_path), "B_ATEND")
    resultado = comparar_insumos("insumos:b_atend", identidades_da_entrada(entrada), entrada)
    assert resultado.situacao is Situacao.IGUAL


def test_insumos_com_um_campo_diferente_nomeiam_o_campo(tmp_path: Path) -> None:
    entrada = entrada_da_politica(_teste(tmp_path), "B_ATEND")
    congeladas = identidades_da_entrada(entrada)
    outra = entrada_da_politica(_teste(tmp_path), "B_ATEND", sigtap="2024-02")
    resultado = comparar_insumos("insumos:b_atend", congeladas, outra)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.detalhe == "campos=auxiliares"


def test_insumos_sem_identidade_congelada_para_a_politica_sao_inconclusivos(tmp_path: Path) -> None:
    entrada = entrada_da_politica(_teste(tmp_path), "B_ATEND")
    resultado = comparar_insumos("insumos:b_atend", None, entrada)
    assert resultado.situacao is Situacao.INCONCLUSIVO
    assert resultado.detalhe == "politica_sem_insumo_congelado"


def _itens(**situacoes: Situacao) -> list[Comparacao]:
    return [Comparacao(nome, situacao) for nome, situacao in situacoes.items()]


@pytest.mark.parametrize(
    ("situacoes", "esperado"),
    [
        ([], Situacao.IGUAL),
        ([Situacao.IGUAL, Situacao.IGUAL], Situacao.IGUAL),
        ([Situacao.IGUAL, Situacao.BYTES_DIFERENTES], Situacao.BYTES_DIFERENTES),
        (
            [Situacao.BYTES_DIFERENTES, Situacao.INCONCLUSIVO, Situacao.IGUAL],
            Situacao.INCONCLUSIVO,
        ),
        (
            [Situacao.INCONCLUSIVO, Situacao.DIVERGENTE, Situacao.BYTES_DIFERENTES],
            Situacao.DIVERGENTE,
        ),
    ],
)
def test_resultado_geral_e_a_pior_situacao_dos_itens(
    situacoes: list[Situacao], esperado: Situacao
) -> None:
    itens = [Comparacao(f"i{n}", situacao) for n, situacao in enumerate(situacoes)]
    assert resultado_geral(itens) is esperado


def test_exigir_conferido_aceita_iguais_e_bytes_diferentes_com_hash_logico_igual() -> None:
    exigir_conferido(_itens(a=Situacao.IGUAL, b=Situacao.BYTES_DIFERENTES))


def test_exigir_conferido_nomeia_os_itens_divergentes_antes_dos_inconclusivos() -> None:
    itens = _itens(
        a=Situacao.IGUAL, b=Situacao.DIVERGENTE, c=Situacao.INCONCLUSIVO, d=Situacao.DIVERGENTE
    )
    with pytest.raises(FalhaOperacionalErro, match=r"reproducao_divergente itens=2 primeiros=b,d$"):
        exigir_conferido(itens)


def test_exigir_conferido_trata_o_inconclusivo_como_falha_e_nao_como_reproduzido() -> None:
    itens = _itens(a=Situacao.IGUAL, b=Situacao.INCONCLUSIVO, c=Situacao.INCONCLUSIVO)
    with pytest.raises(
        FalhaOperacionalErro, match=r"reproducao_inconclusiva itens=2 primeiros=b,c$"
    ):
        exigir_conferido(itens)


def test_exigir_conferido_cita_so_os_primeiros_itens() -> None:
    itens = [Comparacao(f"i{n}", Situacao.DIVERGENTE) for n in range(7)]
    with pytest.raises(FalhaOperacionalErro, match=r"itens=7 primeiros=i0,i1,i2,i3,i4$"):
        exigir_conferido(itens)


def test_comparacao_vira_dicionario_com_a_situacao_em_texto() -> None:
    comparacao = Comparacao("x", Situacao.BYTES_DIFERENTES, "6:lh1:a", "6:lh1:a", "bytes_diferem")
    assert comparacao.como_dict() == {
        "item": "x",
        "situacao": "BYTES_DIFERENTES_HASH_LOGICO_IGUAL",
        "esperado": "6:lh1:a",
        "obtido": "6:lh1:a",
        "detalhe": "bytes_diferem",
    }
