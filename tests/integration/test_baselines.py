"""B_ATEND e B_PROC pelo mesmo motor e ablações isoladas (T08), sobre dados SINTETICOS."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from tests.fixtures.explicacao_cenario import (
    ART_CNES_ALT,
    ART_CNES_OUTRA,
    ART_CNES_PROC,
    ART_SIGTAP_ALT,
    PROCESSAMENTO,
    cenario_ablacao,
    executar_metodo,
)
from tests.fixtures.regras_cenario import materializar, reemitir, snapshot_vazio
from tests.fixtures.regras_execucao import tabela
from tests.fixtures.regras_exemplos import ART_CNES, ART_SIA, ART_SIGTAP, COMPETENCIA, registro

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.rules import EstadoAvaliacao
from sustemporal.contracts.temporal import BaseTemporal, MetodoId
from sustemporal.evaluation.ablation import (
    INTERPRETACAO_ABLACAO,
    AblacaoNaoIsolada,
    TipoAblacao,
    comparar_ablacao,
    trocar_versao_fonte,
)
from sustemporal.explanation.explain import explain
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.rules.insumos import InsumosAvaliacao

LINHA = f"{ART_SIA}#0"
_SEM_SELECAO = {"selecao_versoes.v1"}


def _entradas(run: RunResult) -> dict[str, str]:
    return {d.schema_id: d.dataset_id for d in run.entradas}


def _selecoes(run: RunResult) -> dict[tuple[str, str], dict[str, object]]:
    return {(s["rule_id"], s["fonte"]): s for s in tabela(run, "selecao_versoes.v1")}


def _estados(run: RunResult) -> dict[str, str]:
    return {a["rule_id"]: a["estado"] for a in tabela(run, "avaliacoes.v1")}


def test_b_atend_e_b_proc_pelo_mesmo_motor_so_a_politica_muda(tmp_path: Path) -> None:
    atend = executar_metodo(tmp_path / "atend", MetodoId.B_ATEND)
    proc = executar_metodo(tmp_path / "proc", MetodoId.B_PROC)
    assert (atend.metodo, proc.metodo) == (MetodoId.B_ATEND, MetodoId.B_PROC)
    assert atend.politica_id != proc.politica_id
    assert atend.catalogo_regras_sha256 == proc.catalogo_regras_sha256
    assert atend.snapshot_set_id == proc.snapshot_set_id
    assert _entradas(atend) == _entradas(proc)
    assert atend.codigo == proc.codigo
    sel_atend, sel_proc = _selecoes(atend), _selecoes(proc)
    assert sel_atend.keys() == sel_proc.keys()
    for chave, selecao in sel_atend.items():
        assert (selecao["base"], selecao["competencia_requerida"]) == ("ATENDIMENTO", COMPETENCIA)
        outra = sel_proc[chave]
        assert (outra["base"], outra["competencia_requerida"]) == ("PROCESSAMENTO", PROCESSAMENTO)
        assert selecao["artifact_ids"] != outra["artifact_ids"]
    assert set(_estados(atend).values()) == {"CONFORME"}
    assert _estados(proc)["ESTAB_CBO_CNES"] == "VIOLACAO"


def test_explicacoes_das_baselines_diferem_so_nas_selecoes_e_evidencias(tmp_path: Path) -> None:
    atend = explain(executar_metodo(tmp_path / "atend", MetodoId.B_ATEND), LINHA)
    proc = explain(executar_metodo(tmp_path / "proc", MetodoId.B_PROC), LINHA)
    assert atend.registro == proc.registro
    assert {s.base for s in atend.selecoes} == {BaseTemporal.ATENDIMENTO}
    assert {s.base for s in proc.selecoes} == {BaseTemporal.PROCESSAMENTO}
    assert ART_CNES_PROC in {a for s in proc.selecoes for a in s.artifact_ids}
    assert {a.rule_id for a in atend.avaliacoes} == {a.rule_id for a in proc.avaliacoes}
    assert {a.versao for a in atend.avaliacoes} == {a.versao for a in proc.avaliacoes}
    violadas = [a for a in proc.avaliacoes if a.estado is EstadoAvaliacao.VIOLACAO]
    assert violadas
    assert all(not b.causa_oficial_atribuida for b in (atend, proc))


def _executar(
    raiz: Path, insumos: InsumosAvaliacao, regras: list[RuleSpec] | None = None
) -> RunResult:
    dataset, _ = materializar(cenario_ablacao(), raiz / "entrada")
    return evaluate_rules(
        dataset,
        snapshot_vazio(),
        regras or carregar_regras(),
        RunConfig(versao="1"),
        raiz / "saida",
        insumos=insumos,
    )


@pytest.fixture
def insumos_base(tmp_path: Path) -> InsumosAvaliacao:
    return materializar(cenario_ablacao(), tmp_path / "entrada")[1]


@pytest.mark.parametrize(
    "caso",
    [
        (
            TipoAblacao.VERSAO_CNES,
            FamiliaFonte.CNES_PF,
            {ART_CNES: ART_CNES_ALT},
            {"ESTAB_CBO_CNES"},
        ),
        (
            TipoAblacao.VERSAO_SIGTAP,
            FamiliaFonte.SIGTAP,
            {ART_SIGTAP: ART_SIGTAP_ALT},
            {"PROC_CBO_SIGTAP"},
        ),
    ],
)
def test_ablacao_troca_isoladamente_a_versao_de_uma_fonte(
    tmp_path: Path,
    insumos_base: InsumosAvaliacao,
    caso: tuple[TipoAblacao, FamiliaFonte, dict[str, str], set[str]],
) -> None:
    tipo, fonte, troca, alteradas = caso
    base = _executar(tmp_path, insumos_base)
    assert insumos_base.selecoes is not None
    trocadas = trocar_versao_fonte(insumos_base.selecoes, fonte, troca, tmp_path / "ablacao")
    variante = _executar(tmp_path / "v", replace(insumos_base, selecoes=trocadas))
    relatorio = comparar_ablacao(base, variante, tipo)
    assert relatorio.tipo is tipo
    assert {m.rule_id for m in relatorio.mudancas} == alteradas
    assert all(m.estado_variante is EstadoAvaliacao.VIOLACAO for m in relatorio.mudancas)
    assert relatorio.comparadas == len(tabela(base, "avaliacoes.v1"))
    assert relatorio.interpretacao == INTERPRETACAO_ABLACAO
    assert "sensibilidade" in relatorio.interpretacao
    assert "não identifica causalmente" in relatorio.interpretacao


def test_ablacao_que_congela_a_versao_da_regra(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    regras = carregar_regras()
    base = _executar(tmp_path, insumos_base, regras)
    congelada = [
        r.model_copy(update={"versao": "0.0.9", "instrumentos": ("I",)})
        if r.rule_id == "ESTAB_CBO_CNES"
        else r
        for r in regras
    ]
    variante = _executar(tmp_path / "v", insumos_base, congelada)
    relatorio = comparar_ablacao(base, variante, TipoAblacao.VERSAO_REGRA)
    assert {m.rule_id for m in relatorio.mudancas} == {"ESTAB_CBO_CNES"}
    assert relatorio.regras_alteradas == ("ESTAB_CBO_CNES",)


def test_ablacao_que_muda_mais_de_um_fator_e_recusada(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    atend = executar_metodo(tmp_path / "atend", MetodoId.B_ATEND)
    proc = executar_metodo(tmp_path / "proc", MetodoId.B_PROC)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_politica_diferente"):
        comparar_ablacao(atend, proc, TipoAblacao.VERSAO_CNES)
    base = _executar(tmp_path, insumos_base)
    assert insumos_base.selecoes is not None
    trocadas = trocar_versao_fonte(
        insumos_base.selecoes, FamiliaFonte.SIGTAP, {ART_SIGTAP: ART_SIGTAP_ALT}, tmp_path / "x"
    )
    variante = _executar(tmp_path / "v", replace(insumos_base, selecoes=trocadas))
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_fonte_nao_isolada"):
        comparar_ablacao(base, variante, TipoAblacao.VERSAO_CNES)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_entradas_diferentes"):
        comparar_ablacao(base, variante, TipoAblacao.VERSAO_REGRA)
    congelada = [r.model_copy(update={"versao": "0.0.9"}) for r in carregar_regras()]
    variante_regra = _executar(tmp_path / "r", insumos_base, congelada)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_catalogo_diferente"):
        comparar_ablacao(base, variante_regra, TipoAblacao.VERSAO_SIGTAP)


def test_troca_de_versao_nao_mexe_nas_outras_fontes(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    assert insumos_base.selecoes is not None
    trocadas = trocar_versao_fonte(
        insumos_base.selecoes, FamiliaFonte.CNES_PF, {ART_CNES: ART_CNES_ALT}, tmp_path / "x"
    )
    assert trocadas.dataset_id != insumos_base.selecoes.dataset_id
    assert trocadas.linhas == insumos_base.selecoes.linhas
    assert ART_CNES_ALT in trocadas.artifact_ids
    linhas = pq.read_table(trocadas.caminho).to_pylist()
    for linha in linhas:
        trocada = linha["fonte"] == "CNES_PF"
        assert (linha["artifact_ids"] == ART_CNES_ALT) is trocada
        assert ("ablacao_troca_de_versao" in linha["motivo"]) is trocada
    with pytest.raises(ValueError, match="troca_sem_efeito"):
        trocar_versao_fonte(
            insumos_base.selecoes, FamiliaFonte.CNES_PF, {ART_SIGTAP: ART_CNES_ALT}, tmp_path / "y"
        )


def test_baselines_com_atendimento_igual_ao_processamento_coincidem(tmp_path: Path) -> None:
    atend = executar_metodo(tmp_path / "a", MetodoId.B_ATEND, processamento=COMPETENCIA)
    proc = executar_metodo(tmp_path / "p", MetodoId.B_PROC, processamento=COMPETENCIA)

    def sem(run: RunResult, schema_id: str, campos: set[str]) -> list[dict[str, object]]:
        return [
            {c: v for c, v in linha.items() if c not in campos} for linha in tabela(run, schema_id)
        ]

    metadados = {"run_id", "metodo", "politica_id"}
    assert sem(atend, "avaliacoes.v1", metadados) == sem(proc, "avaliacoes.v1", metadados)
    assert tabela(atend, "evidencias.v1") == tabela(proc, "evidencias.v1")
    selecao = {"run_id", "base", "motivo"}
    assert sem(atend, "selecao_versoes.v1", selecao) == sem(proc, "selecao_versoes.v1", selecao)


def _par_cnes(
    tmp_path: Path, insumos: InsumosAvaliacao, troca: dict[str, str] | None = None
) -> tuple[RunResult, RunResult]:
    base = _executar(tmp_path, insumos)
    assert insumos.selecoes is not None
    trocadas = trocar_versao_fonte(
        insumos.selecoes, FamiliaFonte.CNES_PF, troca or {ART_CNES: ART_CNES_ALT}, tmp_path / "t"
    )
    return base, _executar(tmp_path / "v", replace(insumos, selecoes=trocadas))


def test_ablacao_recusa_execucao_incompleta(tmp_path: Path, insumos_base: InsumosAvaliacao) -> None:
    base, variante = _par_cnes(tmp_path, insumos_base)
    for estado in (EstadoExecucao.PARCIAL, EstadoExecucao.FALHOU):
        incompleta = variante.model_copy(update={"estado": estado, "falhas": 1})
        with pytest.raises(AblacaoNaoIsolada, match="ablacao_execucao_incompleta"):
            comparar_ablacao(base, incompleta, TipoAblacao.VERSAO_CNES)


@pytest.mark.parametrize("tipo", [TipoAblacao.VERSAO_CNES, TipoAblacao.VERSAO_REGRA])
def test_ablacao_sem_troca_real_e_recusada(
    tmp_path: Path, insumos_base: InsumosAvaliacao, tipo: TipoAblacao
) -> None:
    base = _executar(tmp_path, insumos_base)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_sem_troca"):
        comparar_ablacao(base, base, tipo)


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("snapshot_set_id", "snap_outro", "ablacao_snapshot_diferente"),
        ("config_hash", "f" * 64, "ablacao_config_diferente"),
        ("politica_id", "outra_politica", "ablacao_politica_diferente"),
        ("catalogo_regras_sha256", "e" * 64, "ablacao_catalogo_diferente"),
    ],
)
def test_ablacao_de_fonte_exige_cada_fator_fixo(
    tmp_path: Path, insumos_base: InsumosAvaliacao, campo: str, valor: str, mensagem: str
) -> None:
    base, variante = _par_cnes(tmp_path, insumos_base)
    comparar_ablacao(base, variante, TipoAblacao.VERSAO_CNES)
    with pytest.raises(AblacaoNaoIsolada, match=mensagem):
        comparar_ablacao(base, variante.model_copy(update={campo: valor}), TipoAblacao.VERSAO_CNES)


def test_ablacao_exige_mesmo_codigo(tmp_path: Path, insumos_base: InsumosAvaliacao) -> None:
    base, variante = _par_cnes(tmp_path, insumos_base)
    codigo = variante.codigo.model_copy(update={"commit": "outro_commit"})
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_codigo_diferente"):
        comparar_ablacao(
            base, variante.model_copy(update={"codigo": codigo}), TipoAblacao.VERSAO_CNES
        )


def test_ablacao_de_fonte_recusa_mudanca_em_regra_de_outra_fonte(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    base = _executar(tmp_path, insumos_base)
    assert insumos_base.selecoes is not None
    trocadas = trocar_versao_fonte(
        insumos_base.selecoes, FamiliaFonte.CNES_PF, {ART_CNES: ART_CNES_ALT}, tmp_path / "t"
    )
    integridade = dict(insumos_base.integridade) | {ART_SIGTAP: EstadoIntegridade.NAO_VERIFICADO}
    variante = _executar(
        tmp_path / "v", replace(insumos_base, selecoes=trocadas, integridade=integridade)
    )
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_fonte_nao_isolada"):
        comparar_ablacao(base, variante, TipoAblacao.VERSAO_CNES)


def test_ablacao_de_regra_recusa_regra_nao_alterada_que_muda(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    regras = carregar_regras()
    base = _executar(tmp_path, insumos_base, regras)
    alteradas = [
        r.model_copy(update={"versao": "0.0.9"})
        if r.rule_id == "ESTAB_CBO_CNES"
        else r.model_copy(update={"instrumentos": ("I",)})
        if r.rule_id == "PROC_CBO_SIGTAP"
        else r
        for r in regras
    ]
    variante = _executar(tmp_path / "v", insumos_base, alteradas)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_regra_nao_isolada"):
        comparar_ablacao(base, variante, TipoAblacao.VERSAO_REGRA)


def test_ablacao_recusa_substituta_de_outra_competencia(
    tmp_path: Path, insumos_base: InsumosAvaliacao
) -> None:
    base, variante = _par_cnes(tmp_path, insumos_base, {ART_CNES: ART_CNES_OUTRA})
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_substituta_de_outra_competencia"):
        comparar_ablacao(base, variante, TipoAblacao.VERSAO_CNES)


def _restaurar_linha(trocadas: DatasetRef, original: DatasetRef, row_id: str) -> DatasetRef:
    """Seleção em que só as outras linhas mantêm a versão de CNES trocada."""
    antigas = {
        (linha["row_id"], linha["rule_id"], linha["fonte"]): linha
        for linha in pq.read_table(original.caminho).to_pylist()
    }
    linhas = [
        antigas[(linha["row_id"], linha["rule_id"], linha["fonte"])]
        if linha["row_id"] == row_id
        else linha
        for linha in pq.read_table(trocadas.caminho).to_pylist()
    ]
    pq.write_table(pa.Table.from_pylist(linhas, pq.read_schema(trocadas.caminho)), trocadas.caminho)
    return reemitir(trocadas)


def test_ablacao_de_fonte_rastreia_a_troca_por_linha(tmp_path: Path) -> None:
    outra_linha = f"{ART_SIA}#1"
    cenario = cenario_ablacao(registro(0), registro(1))
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    assert insumos.selecoes is not None

    def executar(raiz: Path, selecoes: DatasetRef) -> RunResult:
        return evaluate_rules(
            dataset,
            snapshot_vazio(),
            carregar_regras(),
            RunConfig(versao="1"),
            raiz,
            insumos=replace(insumos, selecoes=selecoes),
        )

    base = executar(tmp_path / "base", insumos.selecoes)
    trocadas = trocar_versao_fonte(
        insumos.selecoes, FamiliaFonte.CNES_PF, {ART_CNES: ART_CNES_ALT}, tmp_path / "t"
    )
    variante = executar(tmp_path / "v", _restaurar_linha(trocadas, insumos.selecoes, outra_linha))
    relatorio = comparar_ablacao(base, variante, TipoAblacao.VERSAO_CNES)
    assert {(m.row_id, m.rule_id) for m in relatorio.mudancas} == {(LINHA, "ESTAB_CBO_CNES")}
    ref = next(r for r in variante.saidas if r.schema_id == "avaliacoes.v1")
    linhas = pq.read_table(ref.caminho).to_pylist()
    forjadas = [
        linha | {"estado": "VIOLACAO"}
        if (linha["row_id"], linha["rule_id"]) == (outra_linha, "ESTAB_CBO_CNES")
        else linha
        for linha in linhas
    ]
    pq.write_table(pa.Table.from_pylist(forjadas, pq.read_schema(ref.caminho)), ref.caminho)
    saidas = tuple(reemitir(r) if r.schema_id == "avaliacoes.v1" else r for r in variante.saidas)
    with pytest.raises(AblacaoNaoIsolada, match="ablacao_fonte_nao_isolada"):
        comparar_ablacao(
            base, variante.model_copy(update={"saidas": saidas}), TipoAblacao.VERSAO_CNES
        )
