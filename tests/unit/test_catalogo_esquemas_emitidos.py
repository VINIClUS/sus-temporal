"""Esquemas canônicos do que o código publica: nenhum `schema_id` emitido fica sem YAML."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts import PapelColuna
from sustemporal.evaluation.baselines import SCHEMA_PREDICOES
from sustemporal.evaluation.values import COLUNAS_VALORES, SCHEMA_VALORES
from sustemporal.reporting.report_publicacao import TABELAS_RELATORIO
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from sustemporal.contracts import EsquemaCanonico

RAIZ = Path(__file__).resolve().parents[2]
ESQUEMAS = RAIZ / "catalog" / "schemas"
FORMA_DE_SCHEMA_ID = re.compile(r"[a-z0-9_]+\.v[0-9]+")
NAO_E_CONJUNTO = {"anotacao_formulario.v1": "versão do formulário de anotação, não um conjunto"}
PUBLICADAS: dict[str, tuple[str, ...]] = {
    **dict(TABELAS_RELATORIO.values()),
    SCHEMA_VALORES: COLUNAS_VALORES,
    SCHEMA_PREDICOES.schema_id: tuple(coluna.nome for coluna in SCHEMA_PREDICOES.colunas),
}
CHAVES = {
    "piloto_contagens.v1": ("dimensao", "valor"),
    "piloto_exclusoes.v1": ("motivo",),
    "piloto_campos.v1": ("campo",),
    "piloto_defasagem.v1": ("defasagem_meses",),
    "piloto_rotulos.v1": ("etapa", "valor"),
    "piloto_inconclusivos.v1": ("rule_id", "fonte", "base", "estado", "classe"),
    "piloto_disponibilidade.v1": ("familia_regra", "instrumento", "competencia", "base_temporal"),
    "valores_p3.v1": ("run_id", "estrato", "categoria"),
    "predicoes_baseline.v1": ("run_id", "row_id", "metodo"),
}
CHAVES_COM_NULO = {
    "piloto_contagens.v1": ("valor",),
    "piloto_defasagem.v1": ("defasagem_meses",),
    "piloto_rotulos.v1": ("valor",),
}
ANULAVEIS = {
    "piloto_contagens.v1": {"valor"},
    "piloto_defasagem.v1": {"defasagem_meses"},
    "piloto_rotulos.v1": {"valor"},
    "piloto_disponibilidade.v1": {"motivo"},
    "valores_p3.v1": {"ocorrencias", "valor_apresentado", "valor_aprovado", "diferenca", "razao"},
}


def _arquivo_do_esquema(schema_id: str) -> Path:
    return ESQUEMAS / f"{schema_id.rsplit('.', 1)[0]}.yaml"


def _ids_literais_em_src() -> set[str]:
    ids: set[str] = set()
    for arquivo in sorted((RAIZ / "src").rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        ids |= {
            no.value
            for no in ast.walk(arvore)
            if isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and FORMA_DE_SCHEMA_ID.fullmatch(no.value)
        }
    return ids


def _papel_esperado(schema_id: str, nome: str) -> PapelColuna:
    if nome in CHAVES[schema_id]:
        return PapelColuna.CHAVE
    if (schema_id, nome) == ("predicoes_baseline.v1", "particao"):
        return PapelColuna.LINHAGEM
    return PapelColuna.DIAGNOSTICO


def _estrutura(esquema: EsquemaCanonico) -> tuple[object, ...]:
    colunas = tuple((c.nome, c.tipo, c.papel, c.anulavel) for c in esquema.colunas)
    return (esquema.schema_id, esquema.chave, esquema.chave_com_nulo, colunas)


def test_todo_schema_id_literal_em_src_tem_esquema_no_catalogo() -> None:
    emitidos = _ids_literais_em_src() - NAO_E_CONJUNTO.keys()
    assert sorted(i for i in emitidos if not _arquivo_do_esquema(i).is_file()) == []


def test_o_que_nao_e_conjunto_continua_emitido_e_sem_esquema() -> None:
    assert NAO_E_CONJUNTO.keys() <= _ids_literais_em_src()
    assert [i for i in NAO_E_CONJUNTO if _arquivo_do_esquema(i).is_file()] == []


def test_o_levantamento_enxerga_os_esquemas_publicados() -> None:
    assert PUBLICADAS.keys() <= _ids_literais_em_src()


def test_a_especificacao_cobre_todo_esquema_publicado() -> None:
    assert CHAVES.keys() == PUBLICADAS.keys()
    assert CHAVES_COM_NULO.keys() <= PUBLICADAS.keys()
    assert ANULAVEIS.keys() <= PUBLICADAS.keys()


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_esquema_carrega_com_as_colunas_e_a_ordem_da_publicacao(schema_id: str) -> None:
    esquema = carregar_esquema(schema_id)
    assert esquema.schema_id == schema_id
    assert tuple(coluna.nome for coluna in esquema.colunas) == PUBLICADAS[schema_id]


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_chave_do_esquema_e_a_do_agrupamento_publicado(schema_id: str) -> None:
    esquema = carregar_esquema(schema_id)
    assert esquema.chave == CHAVES[schema_id]
    assert esquema.chave_com_nulo == CHAVES_COM_NULO.get(schema_id, ())


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_papeis_sao_chave_na_chave_e_diagnostico_no_resto(schema_id: str) -> None:
    esquema = carregar_esquema(schema_id)
    esperados = {c.nome: _papel_esperado(schema_id, c.nome) for c in esquema.colunas}
    assert {c.nome: c.papel for c in esquema.colunas} == esperados


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_nenhuma_coluna_publicada_e_atributo_de_predicao(schema_id: str) -> None:
    esquema = carregar_esquema(schema_id)
    assert esquema.colunas_com_papel(PapelColuna.ATRIBUTO) == ()
    assert esquema.colunas_com_papel(PapelColuna.ROTULO) == ()


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_anulaveis_sao_as_colunas_que_a_publicacao_pode_deixar_nulas(schema_id: str) -> None:
    esquema = carregar_esquema(schema_id)
    assert {c.nome for c in esquema.colunas if c.anulavel} == ANULAVEIS.get(schema_id, set())


@pytest.mark.parametrize("schema_id", PUBLICADAS)
def test_descricao_declara_origem_exploratoria_e_confirmacao_pendente(schema_id: str) -> None:
    descricao = " ".join(carregar_esquema(schema_id).descricao.split())
    assert "pré-G0" in descricao
    assert "A_CONFIRMAR" in descricao


def test_predicoes_do_catalogo_tem_a_estrutura_declarada_em_codigo() -> None:
    assert _estrutura(carregar_esquema("predicoes_baseline.v1")) == _estrutura(SCHEMA_PREDICOES)
