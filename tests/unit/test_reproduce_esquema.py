"""Leiaute físico de um Parquet contra o esquema canônico (T14); SINTETICO.

O hash lógico projeta as colunas do esquema que o arquivo tem. Por isso o leiaute completo (nomes,
ordem e tipos) é conferido antes, e a diferença nunca some da comparação: coluna que falta
(inclusive a de identidade que o hash ignora), que sobra, de outro tipo ou fora de ordem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.records import (
    ColunaCanonica,
    EsquemaCanonico,
    PapelColuna,
    TipoCanonico,
)
from sustemporal.duck import conectar
from sustemporal.reporting.reproduce_esquema import (
    Leiaute,
    colunas_que_diferem,
    colunas_que_diferem_entre,
    leiaute_do_arquivo,
)
from sustemporal.rules.catalog import carregar_esquema
from tests.fixtures.reproducao_parquet import COLUNAS, SCHEMA, gravar, linha

if TYPE_CHECKING:
    from pathlib import Path

ESQUEMA = carregar_esquema(SCHEMA)
CANONICO: Leiaute = tuple((coluna.nome, "VARCHAR") for coluna in ESQUEMA.colunas)


def _coluna(nome: str, tipo: TipoCanonico) -> ColunaCanonica:
    return ColunaCanonica(nome=nome, tipo=tipo, papel=PapelColuna.ATRIBUTO)


ESQUEMA_DE_TIPOS = EsquemaCanonico(
    schema_id="teste_tipos.v1",
    descricao="Um tipo canônico de cada.",
    chave=("t",),
    colunas=(
        ColunaCanonica(nome="t", tipo=TipoCanonico.TEXTO, papel=PapelColuna.CHAVE, anulavel=False),
        _coluna("i", TipoCanonico.INTEIRO),
        _coluna("d", TipoCanonico.DECIMAL),
        _coluna("a", TipoCanonico.DATA),
        _coluna("b", TipoCanonico.BOOLEANO),
    ),
)
TIPOS_CERTOS: Leiaute = (
    ("t", "VARCHAR"),
    ("i", "BIGINT"),
    ("d", "DECIMAL(38,2)"),
    ("a", "DATE"),
    ("b", "BOOLEAN"),
)


def _trocar(leiaute: Leiaute, nome: str, tipo: str) -> Leiaute:
    return tuple((n, tipo if n == nome else t) for n, t in leiaute)


def test_leiaute_do_arquivo_traz_nome_e_tipo_fisico_na_ordem_do_arquivo(tmp_path: Path) -> None:
    gravar([linha("run_a", "art_0#0")], tmp_path / "a.parquet")
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        leiaute = leiaute_do_arquivo(con, tmp_path / "a.parquet")
    finally:
        con.close()
    assert leiaute == tuple((nome, "VARCHAR") for nome in COLUNAS)


def test_leiaute_igual_ao_do_esquema_nao_difere() -> None:
    assert colunas_que_diferem(ESQUEMA, CANONICO) == []


def test_coluna_que_falta_difere_inclusive_a_de_identidade() -> None:
    sem_run_id = tuple(coluna for coluna in CANONICO if coluna[0] != "run_id")
    assert colunas_que_diferem(ESQUEMA, sem_run_id) == ["run_id"]


def test_coluna_que_o_esquema_nao_tem_difere() -> None:
    assert colunas_que_diferem(ESQUEMA, (*CANONICO, ("coluna_a_mais", "VARCHAR"))) == [
        "coluna_a_mais"
    ]


def test_coluna_de_outro_tipo_difere() -> None:
    assert colunas_que_diferem(ESQUEMA, _trocar(CANONICO, "violacoes", "BIGINT")) == ["violacoes"]


def test_so_a_ordem_diferente_nomeia_as_colunas_fora_de_posicao() -> None:
    trocadas = (CANONICO[1], CANONICO[0], *CANONICO[2:])
    assert colunas_que_diferem(ESQUEMA, trocadas) == ["row_id", "run_id"]


def test_varias_diferencas_saem_uma_vez_cada_ausentes_depois_a_mais_depois_tipo() -> None:
    leiaute = _trocar(CANONICO[1:], "resultado", "BIGINT")
    leiaute = (*leiaute, ("coluna_a_mais", "VARCHAR"))
    assert colunas_que_diferem(ESQUEMA, leiaute) == ["run_id", "coluna_a_mais", "resultado"]


def test_coluna_de_outro_tipo_e_fora_de_posicao_sai_uma_vez() -> None:
    trocadas = (CANONICO[1], CANONICO[0], *CANONICO[2:])
    assert colunas_que_diferem(ESQUEMA, _trocar(trocadas, "row_id", "BIGINT")) == [
        "row_id",
        "run_id",
    ]


def test_a_ordem_so_conta_quando_nenhuma_coluna_falta_nem_sobra() -> None:
    sem_run_id_e_trocado = (CANONICO[2], CANONICO[1], *CANONICO[3:])
    assert colunas_que_diferem(ESQUEMA, sem_run_id_e_trocado) == ["run_id"]


def test_leiaute_vazio_difere_em_todas_as_colunas_do_esquema() -> None:
    assert colunas_que_diferem(ESQUEMA, ()) == [coluna.nome for coluna in ESQUEMA.colunas]


def test_cada_tipo_canonico_tem_o_seu_tipo_fisico() -> None:
    assert colunas_que_diferem(ESQUEMA_DE_TIPOS, TIPOS_CERTOS) == []


@pytest.mark.parametrize(
    ("coluna", "fisico"),
    [
        ("t", "BIGINT"),
        ("i", "INTEGER"),
        ("i", "VARCHAR"),
        ("d", "DOUBLE"),
        ("d", "BIGINT"),
        ("a", "TIMESTAMP"),
        ("b", "TINYINT"),
    ],
)
def test_tipo_fisico_que_nao_e_o_do_tipo_canonico_difere(coluna: str, fisico: str) -> None:
    errado = _trocar(TIPOS_CERTOS, coluna, fisico)
    assert colunas_que_diferem(ESQUEMA_DE_TIPOS, errado) == [coluna]


@pytest.mark.parametrize("decimal", ["DECIMAL(18,2)", "DECIMAL(38,4)", "DECIMAL(9,0)"])
def test_decimal_vale_com_qualquer_precisao_e_escala(decimal: str) -> None:
    assert colunas_que_diferem(ESQUEMA_DE_TIPOS, _trocar(TIPOS_CERTOS, "d", decimal)) == []


def test_leiautes_iguais_nao_diferem_entre_si() -> None:
    assert colunas_que_diferem_entre(CANONICO, CANONICO) == []
    assert colunas_que_diferem_entre((), ()) == []


def test_tipo_fisico_diferente_entre_leiautes_nomeia_a_coluna() -> None:
    entre = colunas_que_diferem_entre(TIPOS_CERTOS, _trocar(TIPOS_CERTOS, "d", "DECIMAL(18,2)"))
    assert entre == ["d"]


def test_coluna_so_de_um_dos_leiautes_difere_nos_dois_sentidos() -> None:
    com_a_mais = (*CANONICO, ("coluna_a_mais", "VARCHAR"))
    assert colunas_que_diferem_entre(CANONICO, com_a_mais) == ["coluna_a_mais"]
    assert colunas_que_diferem_entre(com_a_mais, CANONICO) == ["coluna_a_mais"]


def test_outra_ordem_entre_leiautes_nomeia_as_colunas_fora_de_posicao() -> None:
    trocadas = (CANONICO[1], CANONICO[0], *CANONICO[2:])
    assert colunas_que_diferem_entre(CANONICO, trocadas) == ["row_id", "run_id"]


def test_leiaute_vazio_de_um_lado_difere_em_todas_as_colunas_do_outro() -> None:
    assert colunas_que_diferem_entre(CANONICO, ()) == [nome for nome, _ in CANONICO]
    assert colunas_que_diferem_entre((), CANONICO) == [nome for nome, _ in CANONICO]
