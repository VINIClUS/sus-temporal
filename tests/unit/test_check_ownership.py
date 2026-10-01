from pathlib import Path

import pytest

from scripts.check_ownership import (
    EspecificacaoPropriedade,
    Dono,
    carregar_especificacao,
    dono_do_branch,
    encontrar_violacoes,
)

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def especificacao() -> EspecificacaoPropriedade:
    return EspecificacaoPropriedade(
        donos={
            "ORQ": Dono(branches=("claude/orq-*",), caminhos=("pyproject.toml", "docs/process/*")),
            "S1": Dono(branches=("claude/s1-*",), caminhos=("src/sustemporal/acquisition/*",)),
            "S2": Dono(branches=("claude/s2-*",), caminhos=("src/sustemporal/ingest/dbc.py",)),
        },
        somente_humanos=("experiments/decisions/*.yaml",),
        excecoes_humanos=("experiments/decisions/MODELO_*.yaml",),
    )


def test_branch_de_sessao_mapeia_para_dono(especificacao: EspecificacaoPropriedade) -> None:
    assert dono_do_branch("claude/s1-bitemporal", especificacao) == "S1"


def test_branch_desconhecido_nao_tem_dono(especificacao: EspecificacaoPropriedade) -> None:
    assert dono_do_branch("feature/qualquer", especificacao) is None


def test_arquivo_de_outro_dono_e_violacao(especificacao: EspecificacaoPropriedade) -> None:
    violacoes = encontrar_violacoes(["src/sustemporal/ingest/dbc.py"], "S1", especificacao)
    assert violacoes == ["src/sustemporal/ingest/dbc.py"]


def test_arquivo_proprio_e_permitido(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["src/sustemporal/acquisition/fetch.py"]
    assert encontrar_violacoes(alterados, "S1", especificacao) == []


def test_arquivo_sem_dono_e_compartilhado(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["tests/unit/test_fetch.py", "docs/pendencias/T02.md"]
    assert encontrar_violacoes(alterados, "S1", especificacao) == []


def test_decisao_humana_e_violacao_para_agente(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["experiments/decisions/G0.yaml"]
    assert encontrar_violacoes(alterados, "ORQ", especificacao) == alterados


def test_modelo_de_decisao_e_permitido(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["experiments/decisions/MODELO_G0.yaml"]
    assert encontrar_violacoes(alterados, "S2", especificacao) == []


def test_especificacao_do_repositorio_cobre_todas_as_sessoes() -> None:
    especificacao = carregar_especificacao(RAIZ / "docs" / "process" / "propriedade.yaml")
    assert set(especificacao.donos) == {"ORQ", *(f"S{n}" for n in range(1, 10))}
    assert dono_do_branch("claude/determined-ritchie-b9o2qg", especificacao) == "ORQ"
    assert dono_do_branch("claude/s4-motor-regras", especificacao) == "S4"
    assert encontrar_violacoes(["uv.lock"], "S3", especificacao) == ["uv.lock"]
