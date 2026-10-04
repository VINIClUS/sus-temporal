"""B_ATEND e B_PROC pelo mesmo motor e ablações isoladas (T08), sobre dados SINTETICOS."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.explicacao_cenario import (
    ART_CNES_ALT,
    ART_CNES_PROC,
    ART_SIGTAP_ALT,
    PROCESSAMENTO,
    cenario_ablacao,
    executar_metodo,
)
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_execucao import tabela
from tests.fixtures.regras_exemplos import ART_CNES, ART_SIA, ART_SIGTAP, COMPETENCIA

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
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
    with pytest.raises(ValueError, match="troca_sem_efeito"):
        trocar_versao_fonte(
            insumos_base.selecoes, FamiliaFonte.CNES_PF, {ART_SIGTAP: ART_CNES_ALT}, tmp_path / "y"
        )
