"""Amostra estratificada para anotação humana cega."""

from __future__ import annotations

from decimal import Decimal

from pydantic import model_validator

from sustemporal.contracts.base import (
    ContratoBase,
    DecimalExato,
    Identificador,
    Inteiro,
    InteiroNaoNegativo,
)
from sustemporal.contracts.experiment import FreezeId

__all__ = ["AnnotationSample", "Estrato"]


class Estrato(ContratoBase):
    nome: str
    populacao: InteiroNaoNegativo
    amostra: InteiroNaoNegativo
    prob_inclusao: DecimalExato

    @model_validator(mode="after")
    def _coerencia(self) -> Estrato:
        if self.amostra > self.populacao:
            raise ValueError(f"estrato_amostra_maior_que_populacao estrato={self.nome}")
        if not Decimal(0) < self.prob_inclusao <= Decimal(1):
            raise ValueError(f"estrato_probabilidade_invalida estrato={self.nome}")
        return self


class AnnotationSample(ContratoBase):
    sample_id: Identificador
    freeze_id: FreezeId | None = None
    semente: Inteiro
    estratos: tuple[Estrato, ...]
    casos: tuple[str, ...]
    casos_treino: tuple[str, ...] = ()
    colunas_excluidas: tuple[str, ...] = ()
    formulario_versao: str

    @model_validator(mode="after")
    def _treino_separado(self) -> AnnotationSample:
        if set(self.casos) & set(self.casos_treino):
            raise ValueError(f"caso_de_treino_na_amostra_final amostra={self.sample_id}")
        if len(set(self.casos)) != len(self.casos):
            raise ValueError(f"caso_repetido amostra={self.sample_id}")
        return self
