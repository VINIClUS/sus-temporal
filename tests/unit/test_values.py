"""P3: parcela identificada de valor de tabela não aprovado (T13b) sobre cenário SINTETICO."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal.contracts import (
    DatasetRef,
    EstadoExecucao,
    FamiliaRegra,
    Governanca,
    MetodoId,
    OrigemDados,
    calcular_dataset_id,
)
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.values import (
    CATEGORIAS,
    COLUNAS_VALORES,
    SCHEMA_VALORES,
    summarize_values,
)
from sustemporal.hashing import hash_logico_linhas
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.anotacao_valores import CenarioValores, Linha, montar_valores
from tests.fixtures.regras_cenario import reemitir

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


def test_rotulo_contraditorio_reportado_a_parte_sem_sair_do_denominador(
    tmp_path: Path,
) -> None:
    linhas = [
        Linha(
            "r1",
            REJ,
            D("10.00"),
            D("6.00"),
            ("ESTAB_CBO_CNES",),
            contradicoes="NAO_APROVADO_COM_VALOR_APROVADO",
        ),
        Linha("r2", REJ, D("4.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
        Linha("r3", REJ, D("2.00"), D("5.00"), contradicoes="VALOR_APROVADO_MAIOR_QUE_APRESENTADO"),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    contraditorio = tabela[(REJ, "ROTULO_CONTRADITORIO")]
    assert contraditorio["ocorrencias"] == 2
    assert contraditorio["aditiva"] is False
    assert contraditorio["valor_apresentado"] == D("12")
    assert tabela[(REJ, "DENOMINADOR")]["ocorrencias"] == 2
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("8")
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("8")
    assert tabela[(REJ, "DIFERENCA_NEGATIVA")]["ocorrencias"] == 1


def test_catalogo_de_regras_divergente_do_run_e_recusado(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    run = cenario.run.model_copy(update={"catalogo_regras_sha256": "f" * 64})
    with pytest.raises(
        FalhaOperacionalErro, match=f"catalogo_regras_divergente run=.* esperado={'f' * 64} lido="
    ):
        _executar(replace(cenario, run=run), tmp_path)


def test_execucao_sem_catalogo_de_regras_e_recusada(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    run = cenario.run.model_copy(update={"catalogo_regras_sha256": None})
    with pytest.raises(ValueError, match="execucao_sem_catalogo_de_regras"):
        _executar(replace(cenario, run=run), tmp_path)


def test_catalogo_alterado_depois_da_execucao_e_recusado_e_o_mesmo_passa(
    tmp_path: Path,
) -> None:
    cenario = montar_valores(
        tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",))]
    )
    regras = carregar_regras()
    ref = summarize_values(
        cenario.run,
        cenario.labels,
        tmp_path / "ok",
        regras=regras,
        governanca_por_familia=MUNICIPAL,
    )
    assert ref.linhas > 0
    alteradas = [r.model_copy(update={"descricao": r.descricao + " (alterada)"}) for r in regras]
    with pytest.raises(FalhaOperacionalErro, match="catalogo_regras_divergente"):
        summarize_values(
            cenario.run,
            cenario.labels,
            tmp_path / "alterado",
            regras=alteradas,
            governanca_por_familia=MUNICIPAL,
        )


def test_versao_de_regra_divergente_e_recusada(tmp_path: Path) -> None:
    cenario = montar_valores(
        tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))], versao_regras="0.2.0"
    )
    with pytest.raises(FalhaOperacionalErro, match=r"catalogo_regras_divergente .*versao"):
        _executar(cenario, tmp_path)


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
    assert inconclusivo["aditiva"] is False
    assert tabela[(REJ, "ABSTENCAO_ELEGIVEL")]["diferenca"] == D("7")
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
            esperado = 1 if (estrato, categoria) == (REJ, "SEM_VIOLACAO_VERIFICADA") else 0
            assert tabela[(estrato, categoria)]["ocorrencias"] == esperado


def test_reapresentacoes_nao_vinculaveis_sao_ocorrencias_distintas(tmp_path: Path) -> None:
    linhas = [Linha(f"r{i}", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",)) for i in range(2)]
    _, tabela = _resumir(tmp_path, linhas)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] == 2
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("10")


def test_sem_mapa_de_governanca_numerador_e_razao_indeterminados(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",))]
    _, tabela = _resumir(tmp_path, linhas, governanca=None)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] is None
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] is None
    assert tabela[(REJ, "INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA")]["ocorrencias"] == 1
    assert tabela[(REJ, "RAZAO")]["razao"] is None


def test_governanca_desconhecida_fica_fora_do_numerador(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",))]
    governanca = {FamiliaRegra.ESTABELECIMENTO_CBO: Governanca.DESCONHECIDA}
    _, tabela = _resumir(tmp_path, linhas, governanca=governanca)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] == 0
    assert tabela[(REJ, "INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA")]["ocorrencias"] == 1
    assert tabela[(REJ, "RAZAO")]["razao"] == D("0")


def test_familia_de_atendimento_nao_recebe_governanca_municipal(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"))]
    governanca = {FamiliaRegra.IDADE: Governanca.MUNICIPAL_DOCUMENTADA}
    with pytest.raises(ValueError, match="familia_de_atendimento_sem_governanca_municipal"):
        _resumir(tmp_path, linhas, governanca=governanca)


def test_agregado_incoerente_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), resultado="ALERTA")]
    with pytest.raises(FalhaOperacionalErro, match="valores_agregado_incoerente"):
        _resumir(tmp_path, linhas)


def test_rotulos_de_outro_dataset_sao_recusados(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    hash_logico = f"lh1:{'e' * 64}"
    outro = (f"art_{'9' * 64}",)
    registros = DatasetRef(
        dataset_id=calcular_dataset_id("sia_pa.v1", hash_logico, outro),
        schema_id="sia_pa.v1",
        caminho=str(tmp_path / "x.parquet"),
        hash_logico=hash_logico,
        linhas=1,
        artifact_ids=outro,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture",
    )
    run = cenario.run.model_copy(update={"entradas": (registros,)})
    with pytest.raises(ValueError, match="rotulos_de_outro_dataset"):
        _executar(replace(cenario, run=run), tmp_path)


def test_metodo_divergente_do_run_e_recusado(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    run = cenario.run.model_copy(update={"metodo": MetodoId.B_ATEND})
    with pytest.raises(ValueError, match="selecao_de_versoes_multipla"):
        _executar(replace(cenario, run=run), tmp_path)


def test_somas_grandes_sem_arredondamento(tmp_path: Path) -> None:
    grande = D("1000000000000000000000000000.01")
    linhas = [Linha(f"r{i}", REJ, grande, D("0.00"), ("ESTAB_CBO_CNES",)) for i in range(2)]
    _, tabela = _resumir(tmp_path, linhas)
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] == D("2000000000000000000000000000.02")


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


@pytest.mark.parametrize("coluna", ["rule_id", "versao"])
def test_avaliacoes_sem_coluna_de_regra_e_falha_operacional(tmp_path: Path, coluna: str) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    avaliacoes = next(d for d in cenario.run.saidas if d.schema_id == "avaliacoes.v1")
    tabela = pq.read_table(avaliacoes.caminho)
    pq.write_table(tabela.drop_columns([coluna]), avaliacoes.caminho)
    nova = reemitir(avaliacoes)
    saidas = tuple(nova if d.schema_id == "avaliacoes.v1" else d for d in cenario.run.saidas)
    run = cenario.run.model_copy(update={"saidas": saidas})
    with pytest.raises(FalhaOperacionalErro, match=f"valores_leiaute_incompativel .*{coluna}"):
        _executar(replace(cenario, run=run), tmp_path)


def test_resultado_fora_do_enum_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), resultado="APROVADO")]
    with pytest.raises(FalhaOperacionalErro, match="valores_resultado_desconhecido"):
        _resumir(tmp_path, linhas)


def test_rotulo_fora_do_dominio_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha("r1", "NAO_APROVAD0", D("5.00"), D("0.00"))]
    with pytest.raises(
        FalhaOperacionalErro, match="valores_rotulo_desconhecido valor=NAO_APROVAD0"
    ):
        _resumir(tmp_path, linhas)


def test_tipo_fisico_incompativel_e_falha_operacional(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    tabela = pq.read_table(cenario.labels.caminho)
    indice = tabela.column_names.index("valor_apresentado")
    flutuante = tabela.column(indice).cast(pa.float64())
    pq.write_table(
        tabela.set_column(indice, "valor_apresentado", flutuante), cenario.labels.caminho
    )
    with pytest.raises(
        FalhaOperacionalErro,
        match=r"valores_leiaute_incompativel .*coluna=valor_apresentado tipo=DOUBLE "
        r"esperado=DECIMAL",
    ):
        _executar(cenario, tmp_path)


def test_metodo_fora_do_dominio_e_falha_operacional(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    avaliacoes = next(d for d in cenario.run.saidas if d.schema_id == "avaliacoes.v1")
    tabela = pq.read_table(avaliacoes.caminho)
    indice = tabela.column_names.index("metodo")
    estranho = pa.array(["M_TEMPO"] * tabela.num_rows)
    pq.write_table(tabela.set_column(indice, "metodo", estranho), avaliacoes.caminho)
    nova = reemitir(avaliacoes)
    saidas = tuple(nova if d.schema_id == "avaliacoes.v1" else d for d in cenario.run.saidas)
    run = cenario.run.model_copy(update={"saidas": saidas, "metodo": None})
    with pytest.raises(FalhaOperacionalErro, match="valores_metodo_desconhecido valor=M_TEMPO"):
        _executar(replace(cenario, run=run), tmp_path)


def test_agregado_incoerente_com_avaliacoes_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",), estado_avaliacao="CONFORME")
    ]
    with pytest.raises(FalhaOperacionalErro, match="valores_agregado_incoerente_com_avaliacoes"):
        _resumir(tmp_path, linhas)


def test_inconclusivo_e_recorte_sobreposto_mesmo_sem_valor_ou_negativo(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("3.00"), None, resultado="ABSTENCAO"),
        Linha("r2", REJ, D("2.00"), D("5.00"), resultado="ABSTENCAO"),
        Linha("r3", REJ, D("4.00"), D("0.00"), resultado="ABSTENCAO"),
    ]
    _, tabela = _resumir(tmp_path, linhas)
    inconclusivo = tabela[(REJ, "INCONCLUSIVO")]
    assert inconclusivo["ocorrencias"] == 3
    assert inconclusivo["aditiva"] is False
    assert inconclusivo["valor_apresentado"] == D("9")
    assert tabela[(REJ, "CAMPOS_INSUFICIENTES")]["ocorrencias"] == 1
    assert tabela[(REJ, "DIFERENCA_NEGATIVA")]["ocorrencias"] == 1
    assert tabela[(REJ, "ABSTENCAO_ELEGIVEL")]["ocorrencias"] == 1
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("4")


def test_avaliacao_incoerente_com_o_contrato_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",), insumos_completos=False)]
    with pytest.raises(FalhaOperacionalErro, match="valores_avaliacao_incoerente"):
        _resumir(tmp_path, linhas)


def test_nulo_em_coluna_nao_anulavel_e_falha_operacional(tmp_path: Path) -> None:
    cenario = montar_valores(tmp_path / "dados", [Linha("r1", REJ, D("5.00"), D("0.00"))])
    tabela = pq.read_table(cenario.labels.caminho)
    indice = tabela.column_names.index("contradicoes")
    nulos = pa.array([None] * tabela.num_rows, pa.string())
    pq.write_table(tabela.set_column(indice, "contradicoes", nulos), cenario.labels.caminho)
    cenario = replace(cenario, labels=reemitir(cenario.labels))
    with pytest.raises(
        FalhaOperacionalErro, match=r"valores_nulo_em_coluna_nao_anulavel .*coluna=contradicoes"
    ):
        _executar(cenario, tmp_path)


def test_sem_selecao_de_versoes_e_falha_operacional(tmp_path: Path) -> None:
    linhas = [Linha("r1", REJ, D("5.00"), D("0.00"), resultado="ABSTENCAO")]
    cenario = montar_valores(tmp_path / "dados", linhas, sem_avaliacoes=True)
    with pytest.raises(FalhaOperacionalErro, match="valores_sem_selecao_de_versoes"):
        _executar(cenario, tmp_path)


def test_mapa_de_governanca_incompleto_deixa_resultado_indeterminado(tmp_path: Path) -> None:
    linhas = [
        Linha("r1", REJ, D("5.00"), D("0.00"), ("ESTAB_CBO_CNES",)),
        Linha("r2", REJ, D("3.00"), D("0.00"), ("PROC_CBO_SIGTAP",)),
    ]
    governanca = {FamiliaRegra.ESTABELECIMENTO_CBO: Governanca.MUNICIPAL_DOCUMENTADA}
    _, tabela = _resumir(tmp_path, linhas, governanca=governanca)
    assert tabela[(REJ, "NUMERADOR")]["ocorrencias"] is None
    assert tabela[(REJ, "NUMERADOR")]["diferenca"] is None
    assert tabela[(REJ, "RAZAO")]["razao"] is None
    assert tabela[(REJ, "DENOMINADOR")]["diferenca"] == D("8")
