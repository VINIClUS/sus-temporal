"""Tabelas publicadas pelo código (SINTETICO) conferem com o esquema do catálogo.

Cada tabela sai do publicador real (relatório do piloto, P3 e baseline) e é relida do Parquet:
o hash lógico recalculado com as colunas do catálogo reproduz o `DatasetRef`, e ordem, tipo,
nulos e chave do esquema descrevem as linhas gravadas. Nenhum valor descreve o SUS.
"""

from __future__ import annotations

from contextlib import closing
from decimal import Decimal
from typing import TYPE_CHECKING

import duckdb
import pytest

from sustemporal.contracts import FamiliaRegra, Governanca, ResultadoTentativa, TipoCanonico
from sustemporal.evaluation.baselines import SCHEMA_PREDICOES, fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.values import SCHEMA_VALORES, summarize_values
from sustemporal.hashing import hash_logico_relacao
from sustemporal.reporting.report import build_pilot_report
from sustemporal.reporting.report_publicacao import TABELAS_RELATORIO
from sustemporal.rules.catalog import carregar_esquema
from tests.fixtures.anotacao_valores import Linha, montar_valores
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_relatorio import coorte_piloto
from tests.fixtures.piloto_selecao import selecao_sintetica
from tests.fixtures.protocolo_dados import cenario_baseline

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef

D = Decimal
PUBLICADAS = (
    "piloto_contagens.v1",
    "piloto_exclusoes.v1",
    "piloto_campos.v1",
    "piloto_defasagem.v1",
    "piloto_rotulos.v1",
    "piloto_inconclusivos.v1",
    "piloto_disponibilidade.v1",
    "valores_p3.v1",
    "predicoes_baseline.v1",
)
CATEGORIA_NULA = {
    "piloto_contagens.v1": "valor",
    "piloto_defasagem.v1": "defasagem_meses",
    "piloto_rotulos.v1": "valor",
}
CANONICO_DO_FISICO = {
    "VARCHAR": TipoCanonico.TEXTO,
    "BIGINT": TipoCanonico.INTEIRO,
    "BOOLEAN": TipoCanonico.BOOLEANO,
    "DATE": TipoCanonico.DATA,
}
MUNICIPAL = {
    FamiliaRegra.ESTABELECIMENTO_CBO: Governanca.MUNICIPAL_DOCUMENTADA,
    FamiliaRegra.PROCEDIMENTO_CBO: Governanca.MUNICIPAL_DOCUMENTADA,
}
FORA_DO_DRS_XI = "355030"


def _relatorio(pasta: Path) -> dict[str, DatasetRef]:
    principal = conjunto_sia_pa(
        pasta,
        [
            registro("C", "201801", "201801", PA_INDICA="5"),
            registro("C", "201801", "201712", PA_INDICA="6"),
            registro("I", "201801", "201711", PA_INDICA="0", PA_CBOCOD=""),
            registro("", "201801", "", PA_INDICA="5"),
            registro("C", "201801", "201801", PA_UFMUN=FORA_DO_DRS_XI),
            registro("C", "201801", "201801"),
            registro("C", "201901", "201901"),
        ],
        deletados=[5],
    )
    sem_indica = conjunto_sia_pa(
        pasta / "sem_indica",
        [registro("C", "201802", "201802"), registro("I", "201802", "201801")],
        competencia="201802",
        parte="b",
        sem_campos=["PA_INDICA"],
    )
    saida = pasta / "relatorio"
    saida.mkdir()
    entradas = [
        principal,
        sem_indica,
        cobertura_sintetica(pasta, [principal, sem_indica]),
        selecao_sintetica(pasta, principal, observation_ids="obs_x"),
    ]
    observacoes = {"obs_x": ResultadoTentativa.NAO_ENCONTRADO}
    relatorio = build_pilot_report(entradas, coorte_piloto(), saida, observacoes=observacoes)
    return {tabela.schema_id: tabela for tabela in relatorio.tabelas}


def _valores(pasta: Path) -> dict[str, DatasetRef]:
    linhas = [
        Linha("r1", "NAO_APROVADO", D("10.00"), D("0.00"), ("ESTAB_CBO_CNES", "PROC_CBO_SIGTAP")),
        Linha("r2", "NAO_APROVADO", D("5.00"), D("0.00")),
        Linha("r3", "APROVADO_PARCIAL", D("5.00"), D("8.00")),
        Linha("r4", "NAO_APROVADO", None, D("0.00"), resultado="ABSTENCAO"),
    ]
    cenario = montar_valores(pasta / "dados", linhas)
    ref = summarize_values(
        cenario.run, cenario.labels, pasta / "saida", governanca_por_familia=MUNICIPAL
    )
    return {ref.schema_id: ref}


def _baseline(pasta: Path) -> dict[str, DatasetRef]:
    cenario = cenario_baseline(pasta)
    run = fit_baseline(cenario.split, FEATURES_PADRAO, cenario.config, pasta / "run")
    (saida,) = run.saidas
    return {saida.schema_id: saida}


@pytest.fixture(scope="module")
def publicadas(tmp_path_factory: pytest.TempPathFactory) -> dict[str, DatasetRef]:
    raiz = tmp_path_factory.mktemp("esquemas_publicados")
    refs = {**_relatorio(raiz / "piloto"), **_valores(raiz / "p3"), **_baseline(raiz / "ml")}
    return {schema_id: refs[schema_id] for schema_id in PUBLICADAS}


def _tipos_e_linhas(ref: DatasetRef) -> tuple[list[tuple[str, str]], list[tuple[object, ...]]]:
    with closing(duckdb.connect()) as con:
        descricao = con.execute(
            "DESCRIBE SELECT * FROM read_parquet($c)", {"c": ref.caminho}
        ).fetchall()
        linhas = con.execute("SELECT * FROM read_parquet($c)", {"c": ref.caminho}).fetchall()
    return [(str(coluna[0]), str(coluna[1])) for coluna in descricao], linhas


def _hash_recalculado(ref: DatasetRef, colunas: list[str]) -> str:
    with closing(duckdb.connect()) as con:
        con.execute("CREATE TABLE publicada AS SELECT * FROM read_parquet($c)", {"c": ref.caminho})
        return hash_logico_relacao(con, "publicada", colunas)


def _canonico(fisico: str) -> TipoCanonico:
    if fisico.startswith("DECIMAL("):
        return TipoCanonico.DECIMAL
    return CANONICO_DO_FISICO[fisico]


def test_o_cenario_publica_todo_esquema_do_relatorio_da_p3_e_do_baseline() -> None:
    emitidos = {schema_id for schema_id, _ in TABELAS_RELATORIO.values()}
    assert set(PUBLICADAS) == emitidos | {SCHEMA_VALORES, SCHEMA_PREDICOES.schema_id}


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_hash_logico_com_as_colunas_do_catalogo_reproduz_o_dataset_ref(
    schema_id: str, publicadas: dict[str, DatasetRef]
) -> None:
    ref = publicadas[schema_id]
    nomes = [coluna.nome for coluna in carregar_esquema(schema_id).colunas]
    assert _hash_recalculado(ref, nomes) == ref.hash_logico


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_colunas_gravadas_seguem_a_ordem_e_o_tipo_do_esquema(
    schema_id: str, publicadas: dict[str, DatasetRef]
) -> None:
    esquema = carregar_esquema(schema_id)
    fisicas, _ = _tipos_e_linhas(publicadas[schema_id])
    assert [(nome, _canonico(tipo)) for nome, tipo in fisicas] == [
        (coluna.nome, coluna.tipo) for coluna in esquema.colunas
    ]


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_coluna_nao_anulavel_nao_tem_nulo_nas_linhas_gravadas(
    schema_id: str, publicadas: dict[str, DatasetRef]
) -> None:
    esquema = carregar_esquema(schema_id)
    _, linhas = _tipos_e_linhas(publicadas[schema_id])
    assert linhas
    for posicao, coluna in enumerate(esquema.colunas):
        if not coluna.anulavel:
            assert all(linha[posicao] is not None for linha in linhas), coluna.nome


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_chave_do_esquema_identifica_cada_linha_gravada(
    schema_id: str, publicadas: dict[str, DatasetRef]
) -> None:
    esquema = carregar_esquema(schema_id)
    nomes = [coluna.nome for coluna in esquema.colunas]
    posicoes = [nomes.index(nome) for nome in esquema.chave]
    _, linhas = _tipos_e_linhas(publicadas[schema_id])
    chaves = [tuple(linha[posicao] for posicao in posicoes) for linha in linhas]
    assert chaves
    assert len(set(chaves)) == len(chaves)


@pytest.mark.parametrize("schema_id", CATEGORIA_NULA)
def test_tabela_de_frequencia_grava_a_categoria_nula_que_a_chave_admite(
    schema_id: str, publicadas: dict[str, DatasetRef]
) -> None:
    esquema = carregar_esquema(schema_id)
    coluna = CATEGORIA_NULA[schema_id]
    posicao = [c.nome for c in esquema.colunas].index(coluna)
    _, linhas = _tipos_e_linhas(publicadas[schema_id])
    assert coluna in esquema.chave_com_nulo
    assert any(linha[posicao] is None for linha in linhas)
