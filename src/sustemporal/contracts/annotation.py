"""Amostra estratificada para anotação humana cega."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints, model_validator

from sustemporal.contracts.base import (
    ContratoBase,
    DecimalExato,
    Identificador,
    Inteiro,
    InteiroNaoNegativo,
    razao_confere,
)
from sustemporal.contracts.experiment import FreezeId
from sustemporal.contracts.rules import FamiliaRegra

__all__ = [
    "AnnotationSample",
    "AvaliacaoCaso",
    "CasoId",
    "ConclusaoCaso",
    "EstadoReferencia",
    "Estrato",
    "ReferenciaHumana",
]

CasoId = Annotated[str, StringConstraints(pattern=r"^(caso|treino)_[0-9]{4,}$")]


class Estrato(ContratoBase):
    nome: str
    populacao: InteiroNaoNegativo
    amostra: InteiroNaoNegativo
    prob_inclusao: DecimalExato

    @model_validator(mode="after")
    def _coerencia(self) -> Estrato:
        if self.populacao == 0:
            raise ValueError(f"estrato_populacao_vazia estrato={self.nome}")
        if self.amostra > self.populacao:
            raise ValueError(f"estrato_amostra_maior_que_populacao estrato={self.nome}")
        if not Decimal(0) < self.prob_inclusao <= Decimal(1):
            raise ValueError(f"estrato_probabilidade_invalida estrato={self.nome}")
        if not razao_confere(self.amostra, self.populacao, self.prob_inclusao):
            raise ValueError(f"estrato_probabilidade_diverge_da_fracao estrato={self.nome}")
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
    dimensoes_estrato: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _treino_separado(self) -> AnnotationSample:
        if set(self.casos) & set(self.casos_treino):
            raise ValueError(f"caso_de_treino_na_amostra_final amostra={self.sample_id}")
        if len(set(self.casos)) != len(self.casos):
            raise ValueError(f"caso_repetido amostra={self.sample_id}")
        nomes = [estrato.nome for estrato in self.estratos]
        if len(set(nomes)) != len(nomes):
            raise ValueError(f"estrato_repetido amostra={self.sample_id}")
        total = sum(estrato.amostra for estrato in self.estratos)
        if total != len(self.casos):
            raise ValueError(
                f"amostra_estratos_divergem_dos_casos amostra={self.sample_id} "
                f"estratos={total} casos={len(self.casos)}"
            )
        return self


class ConclusaoCaso(StrEnum):
    INCOMPATIBILIDADE_IDENTIFICADA = "INCOMPATIBILIDADE_IDENTIFICADA"
    CAUSA_FORA_DE_ESCOPO_DOCUMENTADA = "CAUSA_FORA_DE_ESCOPO_DOCUMENTADA"
    CAUSA_INDETERMINADA = "CAUSA_INDETERMINADA"
    EVIDENCIA_INSUFICIENTE = "EVIDENCIA_INSUFICIENTE"


class AvaliacaoCaso(ContratoBase):
    """Uma resposta do formulário: várias famílias só com incompatibilidade identificada."""

    caso_id: CasoId
    avaliador: Identificador
    conclusao: ConclusaoCaso
    familias: tuple[FamiliaRegra, ...] = ()
    evidencias: str = ""
    minutos: DecimalExato | None = None

    @model_validator(mode="after")
    def _familias_coerentes(self) -> AvaliacaoCaso:
        identificada = self.conclusao is ConclusaoCaso.INCOMPATIBILIDADE_IDENTIFICADA
        if identificada != bool(self.familias):
            raise ValueError(
                f"avaliacao_familias_incoerentes caso={self.caso_id} conclusao={self.conclusao}"
            )
        if len(set(self.familias)) != len(self.familias):
            raise ValueError(f"avaliacao_familia_repetida caso={self.caso_id}")
        if self.minutos is not None and self.minutos < 0:
            raise ValueError(f"avaliacao_minutos_negativos caso={self.caso_id}")
        return self


class EstadoReferencia(StrEnum):
    ABERTA = "ABERTA"
    FECHADA = "FECHADA"


class ReferenciaHumana(ContratoBase):
    """Referência adjudicada por row_id; só FECHADA pode ser comparada ao motor."""

    sample_id: Identificador
    estado: EstadoReferencia
    casos: dict[str, AvaliacaoCaso]
    casos_amostra: tuple[str, ...]
    pendentes: tuple[CasoId, ...] = ()

    @model_validator(mode="after")
    def _fechamento(self) -> ReferenciaHumana:
        if not set(self.casos) <= set(self.casos_amostra):
            raise ValueError(f"referencia_com_caso_fora_da_amostra amostra={self.sample_id}")
        if self.estado is not EstadoReferencia.FECHADA:
            return self
        if self.pendentes:
            raise ValueError(f"referencia_fechada_com_pendencias amostra={self.sample_id}")
        if set(self.casos) != set(self.casos_amostra):
            raise ValueError(f"referencia_fechada_incompleta amostra={self.sample_id}")
        return self
