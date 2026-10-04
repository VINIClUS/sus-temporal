"""ExplanationBundle SINTETICO válido pelo contrato, até `explain` (T08) estar em `main`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte, ValorNormalizado
from sustemporal.contracts.explanation import (
    EstadoCobertura,
    Evidence,
    ExplanationBundle,
    Limitacao,
    TipoEvidencia,
)
from sustemporal.contracts.records import ProductionRecord, RowLocator
from sustemporal.contracts.rules import Aplicabilidade, EstadoAvaliacao, RuleEvaluation
from sustemporal.contracts.temporal import BaseTemporal, EstadoSelecao, MetodoId, SelecaoVersao
from tests.fixtures.regras_exemplos import ART_CNES, ART_SIA

if TYPE_CHECKING:
    from sustemporal.contracts.records import DatasetRef

__all__ = ["bundle_sintetico", "registro_contrato"]

_RUN = "run_sintetico"


def registro_contrato(indice: int, campos: dict[str, str | None]) -> ProductionRecord:
    instrumento = campos["instrumento"]
    return ProductionRecord(
        row_id=f"{ART_SIA}#{indice}",
        origem=RowLocator(artifact_id=ART_SIA, indice=indice),
        cnes=campos["cnes"],
        competencia_atendimento=campos["competencia_atendimento"],
        competencia_processamento=campos["competencia_processamento"],
        instrumento=ValorNormalizado(bruto=instrumento, valor=instrumento),
        procedimento=campos["procedimento"],
        cbo=campos["cbo"],
    )


def _evidencia(registro: ProductionRecord, pf: DatasetRef) -> Evidence:
    return Evidence(
        evidence_id="ev_ausencia_sintetica",
        tipo=TipoEvidencia.AUSENCIA_NA_FONTE,
        query_id="q_estab_cbo",
        sql_sha256="0" * 64,
        parametros={"cnes": str(registro.cnes), "cbo": str(registro.cbo)},
        dataset_id=pf.dataset_id,
        hash_logico=pf.hash_logico,
        artifact_ids=(ART_CNES,),
        cobertura=EstadoCobertura.DISPONIVEL,
        integridade=EstadoIntegridade.OK,
        n_resultados=0,
    )


def _selecao(competencia: str) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=FamiliaFonte.CNES_PF,
        base=BaseTemporal.ATENDIMENTO,
        competencia_requerida=competencia,
        estado=EstadoSelecao.SELECIONADA,
        artifact_ids=(ART_CNES,),
        motivo="selecao_sintetica",
    )


def _violacao(row_id: str, rule_id: str, selecao: SelecaoVersao, evidencia: str) -> RuleEvaluation:
    return RuleEvaluation(
        run_id=_RUN,
        row_id=row_id,
        rule_id=rule_id,
        versao="0.1.0",
        politica_id="b_atend_sintetica",
        metodo=MetodoId.B_ATEND,
        estado=EstadoAvaliacao.VIOLACAO,
        aplicabilidade=Aplicabilidade.APLICAVEL,
        insumos_completos=True,
        incompatibilidade_demonstrada=True,
        selecoes=(selecao,),
        evidence_ids=(evidencia,),
    )


def bundle_sintetico(
    registro: ProductionRecord, pf: DatasetRef, alvos: tuple[tuple[str, str], ...]
) -> ExplanationBundle:
    """Bundle com uma violação por (rule_id, competência da seleção do CNES PF) em `alvos`."""
    evidencia = _evidencia(registro, pf)
    selecoes = {competencia: _selecao(competencia) for _, competencia in alvos}
    avaliacoes = tuple(
        _violacao(registro.row_id, rule_id, selecoes[competencia], evidencia.evidence_id)
        for rule_id, competencia in alvos
    )
    return ExplanationBundle(
        bundle_id="bundle_sintetico",
        run_id=_RUN,
        row_id=registro.row_id,
        registro=registro,
        avaliacoes=avaliacoes,
        selecoes=tuple(selecoes.values()),
        evidencias=(evidencia,),
        prov_n="SINTETICO",
        prov_json_sha256="0" * 64,
        limitacoes=(
            Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA,
            Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL,
            Limitacao.DADOS_SINTETICOS,
        ),
    )
