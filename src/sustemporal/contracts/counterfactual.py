"""Catálogo fechado de operações e resultado da busca de contrafactuais."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from sustemporal.contracts.base import (
    Booleano,
    Confirmacao,
    ContratoBase,
    DocRef,
    EstadoDocumento,
    Falso,
    Identificador,
    Inteiro,
    InteiroNaoNegativo,
    Proveniencia,
)
from sustemporal.contracts.records import SchemaId
from sustemporal.contracts.rules import RuleId
from sustemporal.contracts.temporal import CompetenciaArquivo

__all__ = [
    "AlvoOperacao",
    "Autoridade",
    "Candidato",
    "CounterfactualSearchResult",
    "Executabilidade",
    "Governanca",
    "Minimalidade",
    "MotivoParada",
    "OperacaoAplicada",
    "OperationSpec",
    "Orcamento",
]

_COLUNAS_IMUTAVEIS = frozenset(
    {"cid", "cid_principal", "cid_secundario", "idade", "sexo", "data_atendimento"}
)
_PREFIXOS_FATOS_DO_ATENDIMENTO = ("sia_pa",)
_PREFIXO_CADASTRO = "cnes_"


class Autoridade(StrEnum):
    ESTABELECIMENTO = "ESTABELECIMENTO"
    GESTOR_MUNICIPAL = "GESTOR_MUNICIPAL"
    GESTOR_ESTADUAL = "GESTOR_ESTADUAL"
    MINISTERIO_SAUDE = "MINISTERIO_SAUDE"
    DESCONHECIDA = "DESCONHECIDA"


class Governanca(StrEnum):
    MUNICIPAL_DOCUMENTADA = "MUNICIPAL_DOCUMENTADA"
    FORA_DA_GOVERNANCA_MUNICIPAL = "FORA_DA_GOVERNANCA_MUNICIPAL"
    DESCONHECIDA = "DESCONHECIDA"


class AlvoOperacao(ContratoBase):
    schema_id: SchemaId
    colunas: tuple[str, ...] = Field(min_length=1)


class OperationSpec(ContratoBase):
    op_id: Identificador
    descricao: str
    autoridade: Autoridade
    governanca: Governanca
    verdade_factual_exigida: str
    alvo: AlvoOperacao
    competencias_permitidas: Literal["ABERTAS", "QUALQUER_HIPOTETICA"]
    alcance: str
    custo: Inteiro
    precondicoes: tuple[str, ...] = ()
    depende_de: tuple[str, ...] = ()
    referencia: DocRef
    altera_vinculo_individual: Falso = False

    @model_validator(mode="after")
    def _operacao_admissivel(self) -> OperationSpec:
        if self.custo < 1:
            raise ValueError(f"operacao_custo_invalido op={self.op_id}")
        if self.alvo.schema_id.startswith(_PREFIXOS_FATOS_DO_ATENDIMENTO):
            raise ValueError(f"operacao_altera_fato_do_atendimento op={self.op_id}")
        if _COLUNAS_IMUTAVEIS & {coluna.lower() for coluna in self.alvo.colunas}:
            raise ValueError(f"operacao_altera_coluna_imutavel op={self.op_id}")
        if not self.alvo.schema_id.startswith(_PREFIXO_CADASTRO):
            raise ValueError(
                f"operacao_fora_do_cadastro_cnes op={self.op_id} schema={self.alvo.schema_id}"
            )
        if self.governanca is Governanca.MUNICIPAL_DOCUMENTADA and not self._documentada():
            raise ValueError(f"governanca_municipal_sem_documentacao op={self.op_id}")
        return self

    def _documentada(self) -> bool:
        """Documento oficial lido e preservado (cópia + SHA-256) e confirmado."""
        return (
            self.autoridade is not Autoridade.DESCONHECIDA
            and self.referencia.proveniencia is Proveniencia.OFICIAL_DOCUMENTO
            and self.referencia.estado is EstadoDocumento.PRESERVADO
            and self.referencia.confirmacao is Confirmacao.CONFIRMADO
        )


class Minimalidade(StrEnum):
    MINIMO_NO_CATALOGO = "MINIMO_NO_CATALOGO"
    SOLUCAO_SEM_PROVA_DE_MINIMALIDADE = "SOLUCAO_SEM_PROVA_DE_MINIMALIDADE"
    BUSCA_INCONCLUSIVA = "BUSCA_INCONCLUSIVA"


class Executabilidade(StrEnum):
    HIPOTESE_PASSADA = "HIPOTESE_PASSADA"
    POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES = "POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES"
    FORA_DA_GOVERNANCA = "FORA_DA_GOVERNANCA"
    INDETERMINADO = "INDETERMINADO"


class Orcamento(ContratoBase):
    max_operacoes: Inteiro = 3
    max_candidatos: Inteiro = 1000

    @model_validator(mode="after")
    def _positivo(self) -> Orcamento:
        if self.max_operacoes < 1 or self.max_candidatos < 1:
            raise ValueError(
                f"orcamento_invalido max_operacoes={self.max_operacoes} "
                f"max_candidatos={self.max_candidatos}"
            )
        return self


class OperacaoAplicada(ContratoBase):
    op_id: Identificador
    parametros: dict[str, str] = Field(default_factory=dict)
    competencia: CompetenciaArquivo | None = None


class Candidato(ContratoBase):
    operacoes: tuple[OperacaoAplicada, ...] = Field(min_length=1)
    custo: Inteiro
    resolve_alvo: Booleano
    novas_violacoes: tuple[str, ...] = ()
    condicoes_pendentes: tuple[str, ...] = ()
    executabilidade: Executabilidade
    regras_revalidadas: tuple[RuleId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _custo(self) -> Candidato:
        if self.custo < len(self.operacoes):
            raise ValueError(
                f"candidato_custo_invalido custo={self.custo} operacoes={len(self.operacoes)}"
            )
        sob_condicoes = Executabilidade.POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES
        if self.executabilidade is sob_condicoes and not self.condicoes_pendentes:
            raise ValueError("candidato_executavel_sem_condicoes")
        return self


class MotivoParada(StrEnum):
    MINIMO_ENCONTRADO = "MINIMO_ENCONTRADO"
    ESPACO_ESGOTADO = "ESPACO_ESGOTADO"
    ORCAMENTO_ESGOTADO = "ORCAMENTO_ESGOTADO"
    SEM_OPERACAO_ADMISSIVEL = "SEM_OPERACAO_ADMISSIVEL"


class CounterfactualSearchResult(ContratoBase):
    bundle_id: Identificador
    regras_alvo: tuple[str, ...] = Field(min_length=1)
    solucoes: tuple[Candidato, ...] = ()
    minimalidade: Minimalidade
    orcamento: Orcamento
    candidatos_avaliados: InteiroNaoNegativo
    custo_max_explorado_completo: InteiroNaoNegativo
    motivo_parada: MotivoParada
    aprovacao_garantida: Falso = False

    @model_validator(mode="after")
    def _coerencia(self) -> CounterfactualSearchResult:
        if self.candidatos_avaliados > self.orcamento.max_candidatos:
            raise ValueError(f"busca_excedeu_orcamento bundle={self.bundle_id}")
        if any(not s.resolve_alvo or s.novas_violacoes for s in self.solucoes):
            raise ValueError(f"solucao_nao_revalidada bundle={self.bundle_id}")
        if any(not set(self.regras_alvo) <= set(s.regras_revalidadas) for s in self.solucoes):
            raise ValueError(f"solucao_sem_revalidar_alvo bundle={self.bundle_id}")
        if any(len(s.operacoes) > self.orcamento.max_operacoes for s in self.solucoes):
            raise ValueError(f"solucao_excede_operacoes bundle={self.bundle_id}")
        sem_prova = Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE
        if self.minimalidade is sem_prova and not self.solucoes:
            raise ValueError(f"solucao_sem_prova_exige_solucao bundle={self.bundle_id}")
        if self.minimalidade is Minimalidade.MINIMO_NO_CATALOGO:
            self._minimo_provado()
        if self.solucoes and self.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA:
            raise ValueError(f"busca_inconclusiva_com_solucao bundle={self.bundle_id}")
        return self

    def _minimo_provado(self) -> None:
        if not self.solucoes:
            raise ValueError(f"minimo_sem_solucao bundle={self.bundle_id}")
        menor = min(s.custo for s in self.solucoes)
        if self.custo_max_explorado_completo < menor - 1:
            raise ValueError(f"minimo_sem_exploracao_completa bundle={self.bundle_id}")
