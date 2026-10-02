"""Verificador único de tipos físicos das tabelas de entrada (cenários SINTETICOS)."""

from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, tabela
from tests.fixtures.regras_exemplos import ART_SIGTAP, cenario_base, registro

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"


def _reescrever_inteiro(caminho: str, coluna: str) -> None:
    tabela_pa = pq.read_table(caminho)
    indice = tabela_pa.schema.get_field_index(coluna)
    numeros = pa.array([202001] * tabela_pa.num_rows, type=pa.int64())
    pq.write_table(tabela_pa.set_column(indice, coluna, numeros), caminho)


@pytest.mark.parametrize(
    ("tabela_alvo", "coluna", "esperado"),
    [
        ("sia_pa.v1", "competencia_atendimento", "FALHOU"),
        ("sigtap_proc_ocupacao.v1", "dt_competencia", "LEIAUTE_INCOMPATIVEL"),
        ("cobertura.v1", "competencia", "COBERTURA_INSUFICIENTE"),
        ("selecao_versoes.v1", "competencia_requerida", "FALHOU"),
    ],
)
def test_toda_tabela_de_entrada_confere_tipo_fisico(
    tmp_path: Path, tabela_alvo: str, coluna: str, esperado: str
) -> None:
    dataset, insumos = materializar(cenario_base(registro(cbo="999999")), tmp_path / "entrada")
    entradas = [dataset, *insumos.auxiliares, insumos.selecoes, insumos.cobertura]
    alvo = next(d for d in entradas if d is not None and d.schema_id == tabela_alvo)
    _reescrever_inteiro(alvo.caminho, coluna)
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    if esperado == "FALHOU":
        assert resultado.estado is EstadoExecucao.FALHOU
        assert "tipo_incompativel" in tabela(resultado, "falhas.v1")[0]["erro"]
        return
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", esperado)


@pytest.mark.parametrize("estado", [1, "QUEBRADO"])
def test_integridade_com_valor_fora_do_contrato_e_falha_de_carga(
    tmp_path: Path, estado: object
) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    integridade = dict(insumos.integridade) | {ART_SIGTAP: estado}
    insumos = replace(insumos, integridade=integridade)
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.FALHOU
    assert "tipo_incompativel" in tabela(resultado, "falhas.v1")[0]["erro"]
