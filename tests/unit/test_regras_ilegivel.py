"""Fonte auxiliar ou cobertura ausente, truncada ou ilegível (cenários SINTETICOS)."""

from pathlib import Path

import pytest

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave
from tests.fixtures.regras_exemplos import cenario_base, registro

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"
VIGENCIA = "VIGENCIA_PROCEDIMENTO_SIGTAP"


def _estragar(caminho: Path, modo: str) -> None:
    if modo == "ausente":
        caminho.unlink()
    elif modo == "truncado":
        dados = caminho.read_bytes()
        caminho.write_bytes(dados[: len(dados) // 2])
    else:
        caminho.write_bytes(b"isto nao e parquet")


def _executar(tmp_path: Path, cbo: str, schema_id: str, modo: str) -> RunResult:
    dataset, insumos = materializar(cenario_base(registro(cbo=cbo)), tmp_path / "entrada")
    entradas = [*insumos.auxiliares, insumos.cobertura]
    alvo = next(d for d in entradas if d is not None and d.schema_id == schema_id)
    _estragar(Path(alvo.caminho), modo)
    return evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )


@pytest.mark.parametrize(
    ("modo", "motivo"),
    [
        ("ausente", "ARQUIVO_AUSENTE"),
        ("truncado", "ARQUIVO_EM_QUARENTENA"),
        ("nao_parquet", "ARQUIVO_EM_QUARENTENA"),
    ],
)
def test_auxiliar_ilegivel_deixa_so_a_regra_dependente_inconclusiva(
    tmp_path: Path, modo: str, motivo: str
) -> None:
    resultado = _executar(tmp_path, "225125", "sigtap_procedimento.v1", modo)
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    avaliacoes = avaliacoes_por_chave(resultado)
    assert (avaliacoes[(LINHA, VIGENCIA)]["estado"], avaliacoes[(LINHA, VIGENCIA)]["motivos"]) == (
        "INCONCLUSIVO",
        motivo,
    )
    assert avaliacoes[(LINHA, PROC)]["estado"] == "CONFORME"


@pytest.mark.parametrize("modo", ["ausente", "truncado", "nao_parquet"])
def test_cobertura_ilegivel_nao_e_utilizavel(tmp_path: Path, modo: str) -> None:
    resultado = _executar(tmp_path, "999999", "cobertura.v1", modo)
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    avaliacoes = avaliacoes_por_chave(resultado)
    assert (avaliacoes[(LINHA, PROC)]["estado"], avaliacoes[(LINHA, PROC)]["motivos"]) == (
        "INCONCLUSIVO",
        "COBERTURA_INSUFICIENTE",
    )
    assert avaliacoes[(LINHA, VIGENCIA)]["estado"] == "CONFORME"
