"""Evidências, afirmações rastreáveis e pacotes de explicação."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from sustemporal.contracts.artifacts import ArtifactId, EstadoIntegridade
from sustemporal.contracts.base import (
    ContratoBase,
    DatasetId,
    Falso,
    Identificador,
    InteiroNaoNegativo,
    Sha256Hex,
)
from sustemporal.contracts.records import HashLogico, ProductionRecord, RowId
from sustemporal.contracts.rules import EstadoAvaliacao, RuleEvaluation
from sustemporal.contracts.temporal import SelecaoVersao

__all__ = [
    "Afirmacao",
    "EstadoCobertura",
    "Evidence",
    "ExplanationBundle",
    "Limitacao",
    "TipoEvidencia",
]


class TipoEvidencia(StrEnum):
    VINCULO_ENCONTRADO = "VINCULO_ENCONTRADO"
    AUSENCIA_NA_FONTE = "AUSENCIA_NA_FONTE"
    FONTE_INCOMPLETA = "FONTE_INCOMPLETA"
    APLICABILIDADE = "APLICABILIDADE"
    SELECAO_TEMPORAL = "SELECAO_TEMPORAL"


class EstadoCobertura(StrEnum):
    DISPONIVEL = "DISPONIVEL"
    INSUFICIENTE = "INSUFICIENTE"
    AUSENTE = "AUSENTE"


class Evidence(ContratoBase):
    evidence_id: Identificador
    tipo: TipoEvidencia
    query_id: Identificador
    sql_sha256: Sha256Hex
    parametros: dict[str, str] = Field(default_factory=dict)
    dataset_id: DatasetId
    hash_logico: HashLogico
    artifact_ids: tuple[ArtifactId, ...]
    cobertura: EstadoCobertura
    integridade: EstadoIntegridade
    n_resultados: InteiroNaoNegativo
    chaves_amostra: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def _coerencia(self) -> Evidence:
        if self.tipo is TipoEvidencia.AUSENCIA_NA_FONTE and self.n_resultados != 0:
            raise ValueError(f"ausencia_com_resultados evidencia={self.evidence_id}")
        if self.tipo is TipoEvidencia.AUSENCIA_NA_FONTE and not self.artifact_ids:
            raise ValueError(f"ausencia_sem_artefato evidencia={self.evidence_id}")
        if self.tipo is TipoEvidencia.VINCULO_ENCONTRADO and self.n_resultados == 0:
            raise ValueError(f"vinculo_sem_resultados evidencia={self.evidence_id}")
        return self

    @property
    def utilizavel(self) -> bool:
        return (
            self.cobertura is EstadoCobertura.DISPONIVEL
            and self.integridade is EstadoIntegridade.OK
        )

    @property
    def sustenta_ausencia(self) -> bool:
        return (
            self.tipo is TipoEvidencia.AUSENCIA_NA_FONTE
            and self.utilizavel
            and self.n_resultados == 0
        )


class Afirmacao(ContratoBase):
    texto: Annotated[str, StringConstraints(min_length=1)]
    template_id: Identificador
    referencias: tuple[str, ...] = Field(min_length=1)


class Limitacao(StrEnum):
    AUSENCIA_NAO_PROVA_INEXISTENCIA = "AUSENCIA_NAO_PROVA_INEXISTENCIA"
    RETRATO_MENSAL_NAO_DATA_EXATA = "RETRATO_MENSAL_NAO_DATA_EXATA"
    RESULTADO_NAO_E_CAUSA_OFICIAL = "RESULTADO_NAO_E_CAUSA_OFICIAL"
    RETROSPECTIVO = "RETROSPECTIVO"
    DADOS_SINTETICOS = "DADOS_SINTETICOS"


class ExplanationBundle(ContratoBase):
    bundle_id: Identificador
    run_id: Identificador
    row_id: RowId
    registro: ProductionRecord
    avaliacoes: tuple[RuleEvaluation, ...]
    selecoes: tuple[SelecaoVersao, ...] = ()
    evidencias: tuple[Evidence, ...] = ()
    prov_n: str
    prov_json_sha256: Sha256Hex
    afirmacoes: tuple[Afirmacao, ...] = ()
    limitacoes: tuple[Limitacao, ...]
    causa_oficial_atribuida: Falso = False

    @model_validator(mode="after")
    def _coerencia(self) -> ExplanationBundle:
        if Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL not in self.limitacoes:
            raise ValueError(f"explicacao_sem_limitacao_de_causa bundle={self.bundle_id}")
        ausencia = any(e.tipo is TipoEvidencia.AUSENCIA_NA_FONTE for e in self.evidencias)
        if ausencia and Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA not in self.limitacoes:
            raise ValueError(f"explicacao_ausencia_sem_limitacao bundle={self.bundle_id}")
        if self.registro.row_id != self.row_id:
            raise ValueError(f"explicacao_registro_incoerente bundle={self.bundle_id}")
        if any(avaliacao.row_id != self.row_id for avaliacao in self.avaliacoes):
            raise ValueError(f"explicacao_mistura_registros bundle={self.bundle_id}")
        if any(avaliacao.run_id != self.run_id for avaliacao in self.avaliacoes):
            raise ValueError(f"explicacao_mistura_execucoes bundle={self.bundle_id}")
        identificadores = [evidencia.evidence_id for evidencia in self.evidencias]
        if len(set(identificadores)) != len(identificadores):
            raise ValueError(f"evidencia_repetida bundle={self.bundle_id}")
        self._referencias_resolvem()
        self._violacoes_sustentadas()
        self._evidencias_citadas_existem()
        self._evidencias_nas_selecoes()
        return self

    def _evidencias_citadas_existem(self) -> None:
        conhecidas = {evidencia.evidence_id for evidencia in self.evidencias}
        for avaliacao in self.avaliacoes:
            if not set(avaliacao.evidence_ids) <= conhecidas:
                raise ValueError(
                    f"avaliacao_cita_evidencia_ausente bundle={self.bundle_id} "
                    f"regra={avaliacao.rule_id}"
                )

    def _referencias_resolvem(self) -> None:
        conhecidas = {e.evidence_id for e in self.evidencias}
        conhecidas |= {a.rule_id for a in self.avaliacoes}
        conhecidas |= {aid for s in self.selecoes for aid in s.artifact_ids}
        for afirmacao in self.afirmacoes:
            if not set(afirmacao.referencias) <= conhecidas:
                raise ValueError(f"afirmacao_sem_referencia_valida bundle={self.bundle_id}")

    def _violacoes_sustentadas(self) -> None:
        """VIOLACAO cita ao menos uma ausência sustentada: nas quatro famílias é a única prova."""
        por_id = {e.evidence_id: e for e in self.evidencias}
        for avaliacao in self.avaliacoes:
            if avaliacao.estado is not EstadoAvaliacao.VIOLACAO:
                continue
            citadas = [por_id.get(i) for i in avaliacao.evidence_ids]
            if any(e is None for e in citadas):
                raise ValueError(f"violacao_cita_evidencia_ausente bundle={self.bundle_id}")
            presentes = [e for e in citadas if e is not None]
            sustentada = any(e.sustenta_ausencia for e in presentes)
            if not sustentada or any(_nao_sustenta(e) for e in presentes):
                raise ValueError(f"violacao_sem_ausencia_sustentada bundle={self.bundle_id}")
            if not all(e.utilizavel for e in presentes):
                raise ValueError(
                    f"violacao_com_evidencia_inutilizavel bundle={self.bundle_id} "
                    f"regra={avaliacao.rule_id}"
                )

    def _evidencias_nas_selecoes(self) -> None:
        """Evidência cita só versões selecionadas; aplicabilidade também o próprio registro."""
        por_id = {e.evidence_id: e for e in self.evidencias}
        do_registro = {self.registro.origem.artifact_id}
        for avaliacao in self.avaliacoes:
            selecionados = {aid for s in avaliacao.selecoes for aid in s.artifact_ids}
            for evidencia_id in avaliacao.evidence_ids:
                evidencia = por_id.get(evidencia_id)
                if evidencia is None:
                    continue
                proprio = do_registro if evidencia.tipo is TipoEvidencia.APLICABILIDADE else set()
                if not set(evidencia.artifact_ids) <= selecionados | proprio:
                    raise ValueError(
                        f"evidencia_fora_das_selecoes bundle={self.bundle_id} "
                        f"regra={avaliacao.rule_id}"
                    )


def _nao_sustenta(evidencia: Evidence) -> bool:
    if evidencia.tipo is TipoEvidencia.FONTE_INCOMPLETA:
        return True
    return evidencia.tipo is TipoEvidencia.AUSENCIA_NA_FONTE and not evidencia.sustenta_ausencia
