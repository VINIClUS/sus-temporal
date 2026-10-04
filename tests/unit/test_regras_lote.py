"""Motor integrado à seleção temporal em lote do T06 (SINTETICO, ponta a ponta)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.errors import ConfigInvalida
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_da_execucao
from sustemporal.rules.lote import avaliar_com_registro, selecionar_em_lote
from sustemporal.temporal.politicas import carregar_politica
from sustemporal.temporal.selector import select_snapshots, unir_snapshots
from tests.fixtures.regras_execucao import avaliacoes_por_chave, tabela
from tests.fixtures.regras_exemplos import ART_SIA
from tests.fixtures.regras_lote import config_lote, mundo_lote, registros_de_producao
from tests.fixtures.temporal_registro import docref

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleSpec

_METODOS = {
    "B_ATEND": MetodoId.B_ATEND,
    "B_PROC": MetodoId.B_PROC,
    "M_TEMP_PADRAO": MetodoId.M_TEMP,
}
_LINHA_JAN_FEV = f"{ART_SIA}#0"


def _executar(
    tmp_path: Path, politica_id: str, *, regras: list[RuleSpec] | None = None, **mundo: bool
) -> RunResult:
    cenario = mundo_lote(tmp_path / "entrada", **mundo)
    return avaliar_com_registro(
        cenario.dataset,
        regras or carregar_regras(),
        config_lote(politica_id),
        cenario.registro,
        tmp_path / "saida",
        insumos=cenario.insumos,
    )


def _estados(resultado: RunResult) -> dict[tuple[str, str], str]:
    return {chave: a["estado"] for chave, a in avaliacoes_por_chave(resultado).items()}


def test_politica_da_execucao_carrega_politica_id_da_config() -> None:
    regras = carregar_regras()
    politica = politica_da_execucao(InsumosAvaliacao(), config_lote("B_PROC"), regras)
    assert politica == carregar_politica("B_PROC")


def test_politica_explicita_prevalece_sobre_politica_id_da_config() -> None:
    regras = carregar_regras()
    explicita = carregar_politica("B_ATEND")
    insumos = InsumosAvaliacao(politica=explicita)
    assert politica_da_execucao(insumos, config_lote("B_PROC"), regras) is explicita


def test_sem_politica_id_usa_a_padrao_do_metodo() -> None:
    config = config_lote(None, metodos=["B_PROC"])
    politica = politica_da_execucao(InsumosAvaliacao(), config, carregar_regras())
    assert politica.politica_id == "b_proc_exploratoria"


def test_politica_id_inexistente_e_config_invalida() -> None:
    with pytest.raises(ConfigInvalida, match="politica_invalida"):
        politica_da_execucao(InsumosAvaliacao(), config_lote("NAO_EXISTE"), carregar_regras())


def test_politica_id_de_outro_metodo_que_o_da_config_e_recusada() -> None:
    config = config_lote("B_PROC", metodos=["B_ATEND"])
    with pytest.raises(MetodoInvalido, match="politica_de_outro_metodo"):
        politica_da_execucao(InsumosAvaliacao(), config, carregar_regras())


@pytest.mark.parametrize("politica_id", sorted(_METODOS))
def test_lote_equivale_a_selecao_por_registro(tmp_path: Path, politica_id: str) -> None:
    cenario = mundo_lote(tmp_path / "entrada")
    config = config_lote(politica_id)
    regras = carregar_regras()
    selecao = selecionar_em_lote(
        cenario.dataset, regras, config, cenario.registro, tmp_path / "sel"
    )
    politica = carregar_politica(politica_id)
    por_registro = {
        (record.row_id, regra.rule_id): select_snapshots(
            record, regra, config, registro=cenario.registro, politica=politica
        )
        for record in registros_de_producao()
        for regra in regras
    }
    linhas = pq.read_table(selecao.selecoes.caminho).to_pylist()
    assert len(linhas) == selecao.selecoes.linhas == len(por_registro)
    for linha in linhas:
        (esperada,) = por_registro[(linha["row_id"], linha["rule_id"])].selecoes
        assert linha["fonte"] == esperada.fonte.value
        assert linha["estado"] == esperada.estado.value
        assert linha["artifact_ids"] == ";".join(esperada.artifact_ids)
        assert linha["motivo"] == esperada.motivo
    assert selecao.snapshots == unir_snapshots(por_registro.values())


def test_tres_metodos_so_mudam_as_selecoes(tmp_path: Path) -> None:
    resultados = {p: _executar(tmp_path / p, p) for p in _METODOS}
    for politica_id, resultado in resultados.items():
        assert resultado.estado is EstadoExecucao.CONCLUIDA
        assert resultado.metodo is _METODOS[politica_id]
        assert resultado.politica_id == politica_id
    fixas = {
        p: sorted(e.dataset_id for e in r.entradas if e.schema_id != "selecao_versoes.v1")
        for p, r in resultados.items()
    }
    assert len({tuple(v) for v in fixas.values()}) == 1
    selecoes = {
        p: next(e.dataset_id for e in r.entradas if e.schema_id == "selecao_versoes.v1")
        for p, r in resultados.items()
    }
    assert len(set(selecoes.values())) == len(_METODOS)
    chave = (_LINHA_JAN_FEV, "ESTAB_CBO_CNES")
    assert _estados(resultados["B_ATEND"])[chave] == "CONFORME"
    assert _estados(resultados["B_PROC"])[chave] == "VIOLACAO"
    assert set(_estados(resultados["M_TEMP_PADRAO"]).values()) <= {"INCONCLUSIVO", "NAO_APLICAVEL"}


def test_m_temp_documentada_coincidente_com_a_regra_seleciona_por_fonte(tmp_path: Path) -> None:
    criterios = (
        CriterioTemporal(fonte=FamiliaFonte.CNES_PF, base=BaseTemporal.PROCESSAMENTO),
        CriterioTemporal(fonte=FamiliaFonte.SIGTAP, base=BaseTemporal.ATENDIMENTO),
    )
    politica = PoliticaTemporal(
        politica_id="m_temp_sintetica",
        tipo=TipoPolitica.DOCUMENTADA,
        metodo=MetodoId.M_TEMP,
        criterios=criterios,
        documento=docref(pendente=False),
    )
    regras = [
        r.model_copy(
            update={
                "criterios_temporais": tuple(
                    c for c in criterios if c.fonte in {q.fonte for q in r.requisitos_fonte}
                )
            }
        )
        for r in carregar_regras()
    ]
    cenario = mundo_lote(tmp_path / "entrada")
    resultado = avaliar_com_registro(
        cenario.dataset,
        regras,
        config_lote(None),
        cenario.registro,
        tmp_path / "saida",
        insumos=replace(cenario.insumos, politica=politica),
    )
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    assert resultado.politica_id == "m_temp_sintetica"
    assert _estados(resultado)[(_LINHA_JAN_FEV, "ESTAB_CBO_CNES")] == "VIOLACAO"
    assert _estados(resultado)[(_LINHA_JAN_FEV, "PROC_CBO_SIGTAP")] == "CONFORME"


def test_reexecucao_reproduz_run_id_e_saidas(tmp_path: Path) -> None:
    cenario = mundo_lote(tmp_path / "entrada")

    def executar() -> RunResult:
        return avaliar_com_registro(
            cenario.dataset,
            carregar_regras(),
            config_lote("B_PROC"),
            cenario.registro,
            tmp_path / "saida",
            insumos=cenario.insumos,
        )

    primeira, segunda = executar(), executar()
    assert primeira.run_id == segunda.run_id
    assert [s.hash_logico for s in primeira.saidas] == [s.hash_logico for s in segunda.saidas]
    assert primeira.snapshot_set_id == segunda.snapshot_set_id


@pytest.mark.parametrize(
    "mundo", [{"cnes_fev_quarentena": True}, {"sigtap_fev_ausente": True}], ids=str
)
def test_arquivo_ausente_ou_em_quarentena_e_inconclusivo(
    tmp_path: Path, mundo: dict[str, bool]
) -> None:
    resultado = _executar(tmp_path, "B_PROC", **mundo)
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    fonte = "CNES_PF" if "cnes_fev_quarentena" in mundo else "SIGTAP"
    selecoes = tabela(resultado, "selecao_versoes.v1")
    afetadas = {
        (s["row_id"], s["rule_id"])
        for s in selecoes
        if s["fonte"] == fonte and s["competencia_requerida"] == "202302"
    }
    assert afetadas
    estados = _estados(resultado)
    for chave in afetadas:
        assert estados[chave] == "INCONCLUSIVO"
    esperado = "EM_QUARENTENA" if fonte == "CNES_PF" else "AUSENTE"
    assert {s["estado"] for s in selecoes if (s["row_id"], s["rule_id"]) in afetadas} == {esperado}


def test_m_temp_com_criterio_diferente_do_da_regra_nunca_avalia_com_ele(tmp_path: Path) -> None:
    politica = PoliticaTemporal(
        politica_id="m_temp_sintetica",
        tipo=TipoPolitica.DOCUMENTADA,
        metodo=MetodoId.M_TEMP,
        criterios=(CriterioTemporal(fonte=FamiliaFonte.CNES_PF, base=BaseTemporal.ATENDIMENTO),),
        documento=docref(pendente=False),
    )
    cenario = mundo_lote(tmp_path / "entrada")
    resultado = avaliar_com_registro(
        cenario.dataset,
        carregar_regras(),
        config_lote(None),
        cenario.registro,
        tmp_path / "saida",
        insumos=replace(cenario.insumos, politica=politica),
    )
    if resultado.estado is EstadoExecucao.FALHOU:
        (falha,) = tabela(resultado, "falhas.v1")
        assert falha["etapa"] == "conferir_selecao"
    else:
        assert set(_estados(resultado).values()) <= {"INCONCLUSIVO", "NAO_APLICAVEL"}


def test_corte_da_config_deixa_fevereiro_fora_do_corte(tmp_path: Path) -> None:
    cenario = mundo_lote(tmp_path / "entrada")
    config = config_lote("B_PROC", corte_observacao="2026-01-02T12:00:00+00:00")
    selecao = selecionar_em_lote(
        cenario.dataset, carregar_regras(), config, cenario.registro, tmp_path / "sel"
    )
    estados = {
        (s["competencia_requerida"], s["estado"])
        for s in pq.read_table(selecao.selecoes.caminho).to_pylist()
    }
    assert estados == {("202301", "SELECIONADA"), ("202302", "FORA_DO_CORTE")}
    assert selecao.snapshots.corte_observacao == config.corte_observacao
