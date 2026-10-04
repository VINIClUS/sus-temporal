"""P3: parcela identificada de valor de tabela não aprovado (T13b) sobre cenário SINTETICO."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq
import pytest

from sustemporal.contracts import DatasetRef, EstadoExecucao, FamiliaRegra, Governanca
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.values import (
    CATEGORIAS,
    COLUNAS_VALORES,
    SCHEMA_VALORES,
    summarize_values,
)
from sustemporal.hashing import hash_logico_linhas
from tests.fixtures.anotacao_valores import CenarioValores, Linha, montar_valores

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

D = Decimal
MUNICIPAL = {
    FamiliaRegra.ESTABELECIMENTO_CBO: Governanca.MUNICIPAL_DOCUMENTADA,
    FamiliaRegra.PROCEDIMENTO_CBO: Governanca.MUNICIPAL_DOCUMENTADA,
}
REJ = "NAO_APROVADO"
PARC = "APROVADO_PARCIAL"


Tabela = dict[tuple[str, str], dict[str, Any]]


def _resumir(
    tmp_path: Path,
    linhas: list[Linha],
    governanca: Mapping[FamiliaRegra, Governanca] | None = MUNICIPAL,
) -> tuple[DatasetRef, Tabela]:
    cenario = montar_valores(tmp_path / "dados", linhas)
    return _executar(cenario, tmp_path, governanca)


def _executar(
    cenario: CenarioValores,
    tmp_path: Path,
    governanca: Mapping[FamiliaRegra, Governanca] | None = MUNICIPAL,
) -> tuple[DatasetRef, Tabela]:
    ref = summarize_values(
        cenario.run, cenario.labels, tmp_path / "saida", governanca_por_familia=governanca
    )
    linhas = pq.read_table(ref.caminho).to_pylist()
    return ref, {(str(x["estrato"]), str(x["categoria"])): x for x in linhas}


def test_linha_com_multiplas_violacoes_conta_uma_vez(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("10.00"), D("0.00"), ("ESTAB_CBO_CNES", "PROC_CBO_SIGTAP")),
        Linha("r2", REJ, D("5.00"), D("0.00")),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    numerador = tabela[(REJ, "NUMERADOR")]
    assert numerador["ocorrencias"] == 1
    assert numerador["diferenca"] == D("10")
    estab = tabela[(REJ, "FAMILIA_ESTABELECIMENTO_CBO")]
    proc = tabela[(REJ, "FAMILIA_PROCEDIMENTO_CBO")]
    assert estab["ocorrencias"] == proc["ocorrencias"] == 1
    assert estab["aditiva"] is False
    assert proc["aditiva"] is False
    assert estab["diferenca"] + proc["diferenca"] > numerador["diferenca"]
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("15")
    assert tabela[(REJ, "RAZAO")]["razao"] == (D("10") / D("15")).quantize(D("1e-12"))


def test_denominador_zero_da_razao_nula(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("10.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
        Linha("r2", PARC, D("5.00"), D("8.00")),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    assert tabela[(PARC, "DENOMINADOR")]["ocorrencias"] == 0
    assert tabela[(PARC, "RAZAO")]["razao"] is None
    assert tabela[(REJ, "RAZAO")]["razao"] == D("1")


def test_diferenca_negativa_fica_a_parte_sem_truncar(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("5.00"), D("8.00"), ("ESTAB_CBO_CNES",)),
        Linha("r2", REJ, D("4.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    negativa = tabela[(REJ, "DIFERENCA_NEGATIVA")]
    assert negativa["ocorrencias"] == 1
    assert negativa["diferenca"] == D("-3")
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("4")
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] == 1


def test_rotulo_contraditorio_fica_a_parte(tmp_path: Path) -> None:
    linhas = [
        Linha(
            "r1",
            REJ,
            D("10.00"),
            D("10.00"),
            ("ESTAB_CBO_CNES",),
            contradicoes="NAO_APROVADO_COM_VALOR_APROVADO",
        ),
        Linha("r2", REJ, D("4.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    contraditorio = tabela[(REJ, "ROTULO_CONTRADITORIO")]
    assert contraditorio["ocorrencias"] == 1
    assert contraditorio["valor_apresentado"] == D("10")
    assert tabela[(REJ, "DENOMINADOR")]["ocorrencias"] == 1


def test_aprovacao_parcial_separada_da_rejeicao(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("10.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
        Linha("r2", PARC, D("10.00"), D("6.00"), ("ESTAB_CBO_CNES",)),
        Linha("r3", PARC, D("10.00"), D("9.00")),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("10")
    assert tabela[(PARC, "NUMERADOR")]["diferenca"] == D("4")
    assert tabela[(PARC, "DENOMINADOR")]["diferenca"] == D("5")
    assert tabela[(PARC, "RAZAO")]["razao"] == D("0.8")


def test_soma_em_decimal_sem_float(tmp_path: Path) -> None:
    linhas = [Linha(f"r{i}", REJ, D("0.10"), D("0.00"), ("ESTAB_CBO_CNES",)) for i in range(3)] + [
        Linha("r9", REJ, D("0.20"), D("0.00"))
    ]
    ref, tabela = _resumir(tmp_path, linhas)
    numerador = tabela[(REJ, "NUMERADOR")]["diferenca"]
    assert isinstance(numerador, Decimal)
    assert numerador == D("0.30")
    assert tabela[(REJ, "RAZAO")]["razao"] == (D("0.30") / D("0.50")).quantize(D("1e-12"))
    tipos = {campo.name: str(campo.type) for campo in pq.read_schema(ref.caminho)}
    assert all("double" not in t and "float" not in t for t in tipos.values())


def test_inconclusivos_e_campos_insuficientes_contados_com_valor(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("7.00"), D("0.00"), resultado="ABSTENCAO"),
        Linha("r2", REJ, D("3.00"), None, ("ESTAB_CBO_CNES",)),
        Linha("r3", REJ, D("2.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    inconclusivo = tabela[(REJ, "INCONCLUSIVO")]
    assert inconclusivo["ocorrencias"] == 1
    assert inconclusivo["diferenca"] == D("7")
    insuficiente = tabela[(REJ, "CAMPOS_INSUFICIENTES")]
    assert insuficiente["ocorrencias"] == 1
    assert insuficiente["valor_apresentado"] == D("3")
    assert insuficiente["diferenca"] is None
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("9")
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("2")


def test_todas_as_categorias_aparecem_mesmo_vazias(tmp_path: Path) -> None:
    _, tabela = _resumir(tmp_path, [Linha("r1", REJ, D("1.00"), D("0.00"))])
    for estrato in (REJ, PARC):
        for categoria in CATEGORIAS:
            assert tabela[(estrato, categoria)]["ocorrencias"] == 0 or estrato == REJ


def test_reapresentacoes_nao_vinculaveis_sao_ocorrencias_distintas(tmp_path: Path) -> None:
    linhas = [Linha(f"r{i}", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",)) for i in range(2)]
    _, tabela = _resumir(tmp_path, linhas)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] == 2
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("10")


def test_governanca_nao_documentada_fica_fora_do_numerador(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",))]
    _, tabela = _resumir(tmp_path, linhas, governanca=None)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] == 0
    assert tabela[(REJ, "INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA")]["ocorrencias"] == 1
    assert tabela[(REJ, "RAZAO")]["razao"] == D("0")


def test_selecao_de_versoes_unica(tmp_path: Path) -> None:
    linhas = [Linha(f"r{i}", REJ, D("5.00"), D("0.00")) for i in range(2)]
    cenario = montar_valores(tmp_path / "dados", linhas, politicas=("p1", "p2"))
    with pytest.raises(ValueError, match="selecao_de_versoes_multipla"):
        _executar(cenario, tmp_path)


def test_execucao_nao_concluida_e_recusada(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"))]
    cenario = montar_valores(tmp_path / "dados", linhas, estado=EstadoExecucao.PARCIAL)
    with pytest.raises(ValueError, match="execucao_nao_concluida"):
        _executar(cenario, tmp_path)


def test_parquet_divergente_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha(f"r{i}", REJ, D("5.00"), D("0.00")) for i in range(3)]
    cenario = montar_valores(tmp_path / "dados", linhas)
    tabela = pq.read_table(cenario.labels.caminho)
    pq.write_table(tabela.slice(1), cenario.labels.caminho)
    with pytest.raises(FalhaOperacionalErro, match="valores_entrada_ilegivel_ou_divergente"):
        _executar(cenario, tmp_path)


def test_dataset_ref_confere_com_conteudo(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",))]
    ref, _ = _resumir(tmp_path, linhas)
    tabela = pq.read_table(ref.caminho)
    assert tuple(tabela.column_names) == COLUNAS_VALORES
    valores = [tabela.column(c).to_pylist() for c in COLUNAS_VALORES]
    conteudo = [tuple(col[i] for col in valores) for i in range(tabela.num_rows)]
    assert ref.schema_id == SCHEMA_VALORES
    assert ref.linhas == tabela.num_rows
    assert ref.hash_logico == hash_logico_linhas(COLUNAS_VALORES, conteudo)
