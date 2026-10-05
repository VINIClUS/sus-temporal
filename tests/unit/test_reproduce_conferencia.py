"""Conferências puras da reprodução: split, originais, notas, ambiente e rodada registrada (T14).

Cada função recebe o já lido (manifestos, estados do ingest, registro) e devolve o veredito, sem
refazer o fluxo; o e2e (`test_reproduce_offline.py`) cobre a costura com os arquivos reais.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.experiment import CodeVersion, Particao, SplitManifest
from sustemporal.reporting.reproduce_comparacao import (
    Situacao,
    comparar_notas,
    comparar_originais,
    comparar_split,
    observacoes_do_ambiente,
    rodada_registrada,
)
from tests.fixtures.protocolo_dados import cenario_baseline
from tests.fixtures.reproducao_parquet import gravar, linha

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef

LINHAS = [linha("run_a", f"art_{i}#0") for i in range(4)]
HASH_OUTRO = "lh1:" + "0" * 64


@pytest.fixture(scope="module")
def split(tmp_path_factory: pytest.TempPathFactory) -> SplitManifest:
    return cenario_baseline(tmp_path_factory.mktemp("split")).split


def _situacoes(split: SplitManifest, outro: SplitManifest) -> dict[str, Situacao]:
    return {c.item: c.situacao for c in comparar_split(split, outro)}


def test_split_igual_compara_o_id_e_cada_particao_e_cada_rotulo(split: SplitManifest) -> None:
    situacoes = _situacoes(split, split)
    assert set(situacoes) == {
        "split:split_id",
        *(f"split:particao:{p.value}" for p in Particao),
        *(f"split:rotulos:{p.value}" for p in Particao),
    }
    assert set(situacoes.values()) == {Situacao.IGUAL}


def test_split_com_outro_id_e_divergente_so_no_id(split: SplitManifest) -> None:
    outro = split.model_copy(update={"split_id": "spl_" + "f" * 64})
    situacoes = _situacoes(split, outro)
    assert situacoes.pop("split:split_id") is Situacao.DIVERGENTE
    assert set(situacoes.values()) == {Situacao.IGUAL}


def test_split_traz_o_id_esperado_e_o_obtido(split: SplitManifest) -> None:
    outro = split.model_copy(update={"split_id": "spl_" + "f" * 64})
    (item,) = (c for c in comparar_split(split, outro) if c.item == "split:split_id")
    assert (item.esperado, item.obtido) == (split.split_id, outro.split_id)


def _com_hash_declarado_diferente(
    split: SplitManifest, particao: Particao, *, rotulos: bool
) -> SplitManifest:
    refs: dict[Particao, DatasetRef] = dict(
        (split.rotulos_por_particao if rotulos else split.particoes) or {}
    )
    refs[particao] = refs[particao].model_copy(update={"hash_logico": HASH_OUTRO})
    return split.model_copy(update={"rotulos_por_particao" if rotulos else "particoes": refs})


@pytest.mark.parametrize(("nome", "rotulos"), [("particao", False), ("rotulos", True)])
def test_split_com_hash_declarado_diferente_do_refeito_e_divergente_na_particao(
    split: SplitManifest, nome: str, rotulos: bool
) -> None:
    esperado = _com_hash_declarado_diferente(split, Particao.TESTE, rotulos=rotulos)
    situacoes = _situacoes(esperado, split)
    assert situacoes.pop(f"split:{nome}:TESTE") is Situacao.DIVERGENTE
    assert set(situacoes.values()) == {Situacao.IGUAL}


@pytest.mark.parametrize(
    ("nome", "campo"), [("particao", "particoes"), ("rotulos", "rotulos_por_particao")]
)
def test_split_refeito_sem_a_particao_e_divergente_e_nao_inconclusivo(
    split: SplitManifest, nome: str, campo: str
) -> None:
    sem = split.model_copy(update={campo: None})
    itens = {c.item: c for c in comparar_split(split, sem)}
    for particao in Particao:
        item = itens[f"split:{nome}:{particao.value}"]
        assert item.situacao is Situacao.DIVERGENTE
        assert item.obtido is None
        assert item.detalhe == "particao_ausente"


def test_split_congelado_sem_particoes_nao_gera_itens_dessa_parte(split: SplitManifest) -> None:
    sem = split.model_copy(update={"particoes": None, "rotulos_por_particao": None})
    assert [c.item for c in comparar_split(sem, split)] == ["split:split_id"]


def _dataset(tmp_path: Path, nome: str, artefatos: tuple[str, ...]) -> DatasetRef:
    ref = gravar(LINHAS, tmp_path / nome / "a.parquet")
    return ref.model_copy(update={"artifact_ids": artefatos})


A1, A2, A3 = ("art_" + c * 64 for c in "123")


def test_originais_normalizados_no_ingest_refeito_nao_geram_item(tmp_path: Path) -> None:
    conjunto = _dataset(tmp_path, "u", (A1, A2))
    assert comparar_originais([conjunto], {A1: "NORMALIZADO", A2: "NORMALIZADO"}) == []


def test_original_ausente_do_ingest_torna_o_conjunto_inconclusivo(tmp_path: Path) -> None:
    conjunto = _dataset(tmp_path, "u", (A1, A2))
    (item,) = comparar_originais([conjunto], {A1: "NORMALIZADO", A2: "ARQUIVOAUSENTE"})
    assert item.item == f"conjunto:{conjunto.schema_id}"
    assert item.situacao is Situacao.INCONCLUSIVO
    assert item.esperado == f"{conjunto.linhas}:{conjunto.hash_logico}"
    assert item.obtido is None
    assert item.detalhe == "originais_indisponiveis artefatos=1 estados=ARQUIVOAUSENTE"


def test_artefato_que_o_ingest_nem_listou_conta_como_indisponivel(tmp_path: Path) -> None:
    conjunto = _dataset(tmp_path, "u", (A1,))
    (item,) = comparar_originais([conjunto], {})
    assert item.detalhe == "originais_indisponiveis artefatos=1 estados=AUSENTE_DO_INGEST"


def test_estados_diferentes_aparecem_ordenados_e_sem_repeticao(tmp_path: Path) -> None:
    conjunto = _dataset(tmp_path, "u", (A1, A2, A3))
    estados = {A1: "QUARENTENA_LEIAUTE", A2: "ARQUIVOAUSENTE", A3: "QUARENTENA_LEIAUTE"}
    (item,) = comparar_originais([conjunto], estados)
    assert item.detalhe == (
        "originais_indisponiveis artefatos=3 estados=ARQUIVOAUSENTE,QUARENTENA_LEIAUTE"
    )


def test_so_o_conjunto_com_artefato_indisponivel_fica_inconclusivo(tmp_path: Path) -> None:
    sao = _dataset(tmp_path, "a", (A1,))
    falta = _dataset(tmp_path, "b", (A2,)).model_copy(update={"schema_id": "sia_pa_rotulos.v1"})
    itens = comparar_originais([sao, falta], {A1: "NORMALIZADO", A2: "FALHA_NORMALIZACAO"})
    assert [i.item for i in itens] == ["conjunto:sia_pa_rotulos.v1"]


def test_notas_iguais_em_outra_ordem_sao_iguais() -> None:
    assert comparar_notas("notas", ["a", "b"], ["b", "a"]).situacao is Situacao.IGUAL


def test_notas_sem_o_relatorio_original_sao_inconclusivas() -> None:
    resultado = comparar_notas("notas", None, ["a"])
    assert resultado.situacao is Situacao.INCONCLUSIVO
    assert resultado.detalhe == "original_ausente"


def test_nota_que_muda_ou_falta_ou_sobra_e_divergente_com_as_contagens() -> None:
    resultado = comparar_notas("notas", ["reamostragens=50", "x"], ["reamostragens=2000", "x", "y"])
    assert resultado.situacao is Situacao.DIVERGENTE
    assert resultado.esperado == "2"
    assert resultado.obtido == "3"
    assert resultado.detalhe == "faltando=1 sobrando=2 primeira=reamostragens=50"


def test_notas_repetidas_contam_como_notas_repetidas() -> None:
    assert comparar_notas("notas", ["a", "a"], ["a"]).situacao is Situacao.DIVERGENTE


CODIGO = CodeVersion(commit="a" * 40, sujo=False, versao_pacote="0.0.0")
PACOTES = {"duckdb": "1.0", "pyarrow": "2.0"}


def _observacoes(
    *, config_igual: bool = True, codigo: CodeVersion = CODIGO, pacotes: Mapping[str, str] = PACOTES
) -> list[str]:
    return observacoes_do_ambiente(
        config_igual=config_igual,
        codigo=codigo,
        congelado=CODIGO,
        pacotes=pacotes,
        congelados=PACOTES,
    )


def test_ambiente_igual_nao_tem_observacao() -> None:
    assert _observacoes() == []


def test_config_diferente_vira_observacao_e_nao_divergencia() -> None:
    assert _observacoes(config_igual=False) == ["config_diferente_da_congelada"]


def test_commit_diferente_traz_os_dois_commits() -> None:
    outro = CODIGO.model_copy(update={"commit": "b" * 40})
    assert _observacoes(codigo=outro) == [
        f"codigo_diferente_do_congelado congelado={'a' * 40} atual={'b' * 40}"
    ]


def test_arvore_suja_com_o_mesmo_commit_tambem_e_observacao() -> None:
    suja = CODIGO.model_copy(update={"sujo": True})
    assert _observacoes(codigo=suja) == [
        f"codigo_diferente_do_congelado congelado={'a' * 40} atual={'a' * 40}"
    ]


def test_pacote_diferente_ou_ausente_e_listado_em_ordem() -> None:
    atuais = {"duckdb": "1.1"}
    assert _observacoes(pacotes=atuais) == [
        "pacotes_diferentes_do_congelado pacotes=duckdb,pyarrow"
    ]


def test_pacote_a_mais_no_ambiente_atual_nao_e_diferenca() -> None:
    assert _observacoes(pacotes={**PACOTES, "novo": "9"}) == []


def test_observacoes_saem_na_ordem_config_codigo_pacotes() -> None:
    outro = CODIGO.model_copy(update={"commit": "b" * 40})
    observacoes = _observacoes(config_igual=False, codigo=outro, pacotes={})
    assert [o.split(" ")[0] for o in observacoes] == [
        "config_diferente_da_congelada",
        "codigo_diferente_do_congelado",
        "pacotes_diferentes_do_congelado",
    ]


REGISTRO = [
    {"freeze_id": "frz_a", "modo": "EXPLORATORIO", "report_id": "rep_1"},
    {"freeze_id": "frz_b", "modo": "EXPLORATORIO", "report_id": "rep_2"},
    {"freeze_id": "frz_a", "modo": "CONFIRMATORIO", "report_id": "rep_3"},
    {"freeze_id": "frz_a", "modo": "EXPLORATORIO", "report_id": "rep_4"},
    {"freeze_id": "frz_b", "modo": "CONFIRMATORIO", "report_id": "rep_5"},
]


def test_rodada_registrada_e_a_ultima_do_mesmo_congelamento_e_modo() -> None:
    rodada = rodada_registrada(REGISTRO, "frz_a", "EXPLORATORIO")
    assert rodada is not None
    assert rodada["report_id"] == "rep_4"


def test_rodada_registrada_nao_mistura_congelamento_nem_modo() -> None:
    assert (rodada_registrada(REGISTRO, "frz_b", "EXPLORATORIO") or {})["report_id"] == "rep_2"
    assert (rodada_registrada(REGISTRO, "frz_a", "CONFIRMATORIO") or {})["report_id"] == "rep_3"


def test_sem_rodada_do_congelamento_e_modo_nao_ha_original() -> None:
    assert rodada_registrada(REGISTRO, "frz_c", "EXPLORATORIO") is None
    assert rodada_registrada([], "frz_a", "EXPLORATORIO") is None
