"""Métricas com denominadores explícitos e relatórios de avaliação."""

from __future__ import annotations

from decimal import Decimal

from pydantic import model_validator

from sustemporal.contracts.base import (
    ContratoBase,
    DecimalExato,
    Identificador,
    InstanteUTC,
    InteiroNaoNegativo,
    OrigemDados,
)
from sustemporal.contracts.experiment import FreezeId, ModoExecucao
from sustemporal.contracts.records import DatasetRef

__all__ = ["EvaluationReport", "IntervaloConfianca", "ValorMetrica"]


class IntervaloConfianca(ContratoBase):
    inferior: DecimalExato
    superior: DecimalExato
    nivel: DecimalExato = Decimal("0.95")

    @model_validator(mode="after")
    def _ordem(self) -> IntervaloConfianca:
        if self.inferior > self.superior:
            raise ValueError("intervalo_invertido")
        return self


class ValorMetrica(ContratoBase):
    nome: Identificador
    estrato: str = "TOTAL"
    numerador: InteiroNaoNegativo
    denominador: InteiroNaoNegativo
    valor: DecimalExato | None = None
    ic: IntervaloConfianca | None = None

    @model_validator(mode="after")
    def _denominador(self) -> ValorMetrica:
        if self.denominador == 0 and self.valor is not None:
            raise ValueError(f"metrica_com_denominador_zero nome={self.nome}")
        if self.denominador > 0 and self.valor is None:
            raise ValueError(f"metrica_sem_valor nome={self.nome}")
        return self


class EvaluationReport(ContratoBase):
    report_id: Identificador
    modo: ModoExecucao
    origem_dados: OrigemDados
    freeze_id: FreezeId | None = None
    decisao_g2: str | None = None
    runs: tuple[str, ...] = ()
    metricas: tuple[ValorMetrica, ...] = ()
    tabelas: tuple[DatasetRef, ...] = ()
    notas: tuple[str, ...] = ()
    criado_em: InstanteUTC

    @model_validator(mode="after")
    def _confirmatorio(self) -> EvaluationReport:
        if self.origem_dados is OrigemDados.SINTETICO and self.modo is ModoExecucao.CONFIRMATORIO:
            raise ValueError(f"relatorio_sintetico_confirmatorio report={self.report_id}")
        if self.modo is ModoExecucao.CONFIRMATORIO and not (self.freeze_id and self.decisao_g2):
            raise ValueError(f"relatorio_confirmatorio_sem_freeze_ou_g2 report={self.report_id}")
        return self
