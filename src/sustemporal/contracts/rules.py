"""Especificação de regras, estados de avaliação e agregação por registro."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, StringConstraints, model_validator

from sustemporal.contracts.base import (
    Booleano,
    ContratoBase,
    DocRef,
    FamiliaFonte,
    Identificador,
    InstanteUTC,
    ReferenciaDecisao,
)
from sustemporal.contracts.records import RowId, SchemaId
from sustemporal.contracts.temporal import (
    EstadoSelecao,
    MetodoId,
    SelecaoVersao,
    VigenciaDocumentada,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "AgregadoRegistro",
    "Aplicabilidade",
    "CatalogoFamilias",
    "EstadoAvaliacao",
    "EstadoRegra",
    "FalhaOperacional",
    "FamiliaCandidata",
    "FamiliaRegra",
    "MotivoInconclusao",
    "RequisitoFonte",
    "ResultadoRegistro",
    "RuleEvaluation",
    "RuleSpec",
    "UnidadeAvaliacao",
    "decidir_estado",
]

RuleId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
VersaoSemantica = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]


class EstadoAvaliacao(StrEnum):
    CONFORME = "CONFORME"
    VIOLACAO = "VIOLACAO"
    INCONCLUSIVO = "INCONCLUSIVO"
    NAO_APLICAVEL = "NAO_APLICAVEL"


class Aplicabilidade(StrEnum):
    APLICAVEL = "APLICAVEL"
    NAO_APLICAVEL_DEMONSTRADA = "NAO_APLICAVEL_DEMONSTRADA"
    DESCONHECIDA = "DESCONHECIDA"


class MotivoInconclusao(StrEnum):
    ARQUIVO_AUSENTE = "ARQUIVO_AUSENTE"
    ARQUIVO_EM_QUARENTENA = "ARQUIVO_EM_QUARENTENA"
    CAMPO_INSUFICIENTE = "CAMPO_INSUFICIENTE"
    VIGENCIA_NAO_RESOLVIDA = "VIGENCIA_NAO_RESOLVIDA"
    VERSAO_AMBIGUA = "VERSAO_AMBIGUA"
    COBERTURA_INSUFICIENTE = "COBERTURA_INSUFICIENTE"
    LEIAUTE_INCOMPATIVEL = "LEIAUTE_INCOMPATIVEL"
    FORA_DO_CORTE = "FORA_DO_CORTE"
    APLICABILIDADE_DESCONHECIDA = "APLICABILIDADE_DESCONHECIDA"
    POLITICA_NAO_RESOLVIDA = "POLITICA_NAO_RESOLVIDA"


def decidir_estado(
    aplicabilidade: Aplicabilidade,
    insumos_completos: bool,
    incompatibilidade: Booleano | None,
    motivos: Iterable[MotivoInconclusao],
) -> EstadoAvaliacao:
    """Tabela-verdade formal de V(r, g, S, p).

    Returns:
        NAO_APLICAVEL só com não aplicabilidade demonstrada; VIOLACAO só com aplicabilidade
        conhecida, insumos completos, nenhum motivo de inconclusão e incompatibilidade
        demonstrada; INCONCLUSIVO em qualquer lacuna.
    """
    if aplicabilidade is Aplicabilidade.NAO_APLICAVEL_DEMONSTRADA:
        return EstadoAvaliacao.NAO_APLICAVEL
    if aplicabilidade is Aplicabilidade.DESCONHECIDA:
        return EstadoAvaliacao.INCONCLUSIVO
    if not insumos_completos or tuple(motivos) or incompatibilidade is None:
        return EstadoAvaliacao.INCONCLUSIVO
    return EstadoAvaliacao.VIOLACAO if incompatibilidade else EstadoAvaliacao.CONFORME


class FamiliaRegra(StrEnum):
    PROCEDIMENTO_CBO = "PROCEDIMENTO_CBO"
    ESTABELECIMENTO_CBO = "ESTABELECIMENTO_CBO"
    INSTRUMENTO_REGISTRO = "INSTRUMENTO_REGISTRO"
    VIGENCIA_PROCEDIMENTO = "VIGENCIA_PROCEDIMENTO"
    SERVICO_CLASSIFICACAO = "SERVICO_CLASSIFICACAO"
    HABILITACAO = "HABILITACAO"
    CID = "CID"
    IDADE = "IDADE"
    SEXO = "SEXO"
    QUANTIDADE_MAXIMA = "QUANTIDADE_MAXIMA"


class EstadoRegra(StrEnum):
    CANDIDATA_PRE_G0 = "CANDIDATA_PRE_G0"
    APROVADA_G0 = "APROVADA_G0"
    CONGELADA = "CONGELADA"
    RETIRADA = "RETIRADA"


class UnidadeAvaliacao(StrEnum):
    OCORRENCIA = "OCORRENCIA"
    ESTABELECIMENTO_CBO = "ESTABELECIMENTO_CBO"


class RequisitoFonte(ContratoBase):
    fonte: FamiliaFonte
    schema_id: SchemaId
    campos: tuple[str, ...]


def _exigir_unidade_cadastral(
    familia: FamiliaRegra, unidade: UnidadeAvaliacao, identificador: str
) -> None:
    cadastral = familia is FamiliaRegra.ESTABELECIMENTO_CBO
    if cadastral and unidade is not UnidadeAvaliacao.ESTABELECIMENTO_CBO:
        raise ValueError(f"regra_cadastral_exige_estabelecimento_cbo regra={identificador}")


def _decidida_sem_g0(estado: EstadoRegra, decisao_g0: str | None) -> bool:
    return estado in {EstadoRegra.APROVADA_G0, EstadoRegra.CONGELADA} and decisao_g0 is None


class FamiliaCandidata(ContratoBase):
    familia: FamiliaRegra
    estado: EstadoRegra
    descricao: str
    instrumentos: tuple[str, ...]
    unidade_avaliacao: UnidadeAvaliacao
    requisitos_fonte: tuple[RequisitoFonte, ...] = Field(min_length=1)
    referencia: DocRef
    decisao_g0: ReferenciaDecisao | None = None

    @model_validator(mode="after")
    def _unidade(self) -> FamiliaCandidata:
        if _decidida_sem_g0(self.estado, self.decisao_g0):
            raise ValueError(f"familia_sem_decisao_g0 familia={self.familia} estado={self.estado}")
        _exigir_unidade_cadastral(self.familia, self.unidade_avaliacao, self.familia)
        return self


class CatalogoFamilias(ContratoBase):
    versao: str
    familias: tuple[FamiliaCandidata, ...]
    reservadas: tuple[FamiliaRegra, ...] = ()

    @model_validator(mode="after")
    def _sem_repeticao(self) -> CatalogoFamilias:
        nomes = [entrada.familia for entrada in self.familias]
        if len(set(nomes)) != len(nomes) or set(nomes) & set(self.reservadas):
            raise ValueError("catalogo_familias_repetidas_ou_reservadas")
        return self


class RuleSpec(ContratoBase):
    rule_id: RuleId
    familia: FamiliaRegra
    versao: VersaoSemantica
    estado: EstadoRegra
    descricao: str
    instrumentos: tuple[str, ...]
    condicao_aplicabilidade: Identificador
    unidade_avaliacao: UnidadeAvaliacao
    campos_necessarios: tuple[str, ...]
    requisitos_fonte: tuple[RequisitoFonte, ...]
    politica_id: Identificador
    vigencia: VigenciaDocumentada | None = None
    referencia: DocRef
    pressupostos: tuple[str, ...] = ()
    decisao_g0: ReferenciaDecisao | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> RuleSpec:
        if _decidida_sem_g0(self.estado, self.decisao_g0):
            raise ValueError(f"regra_sem_decisao_g0 regra={self.rule_id} estado={self.estado}")
        _exigir_unidade_cadastral(self.familia, self.unidade_avaliacao, self.rule_id)
        if not self.requisitos_fonte:
            raise ValueError(f"regra_sem_requisito_de_fonte regra={self.rule_id}")
        return self


class RuleEvaluation(ContratoBase):
    run_id: Identificador
    row_id: RowId
    rule_id: RuleId
    versao: VersaoSemantica
    politica_id: Identificador
    metodo: MetodoId
    estado: EstadoAvaliacao
    aplicabilidade: Aplicabilidade
    insumos_completos: Booleano
    incompatibilidade_demonstrada: Booleano | None
    motivos: tuple[MotivoInconclusao, ...] = ()
    selecoes: tuple[SelecaoVersao, ...] = ()
    evidence_ids: tuple[Identificador, ...] = ()

    @model_validator(mode="after")
    def _coerencia(self) -> RuleEvaluation:
        esperado = decidir_estado(
            self.aplicabilidade,
            self.insumos_completos,
            self.incompatibilidade_demonstrada,
            self.motivos,
        )
        if self.estado is not esperado:
            raise ValueError(f"estado_incoerente row={self.row_id} regra={self.rule_id}")
        selecionadas = bool(self.selecoes) and all(
            selecao.estado is EstadoSelecao.SELECIONADA for selecao in self.selecoes
        )
        if self.estado is EstadoAvaliacao.VIOLACAO and not (selecionadas and self.evidence_ids):
            raise ValueError(f"violacao_sem_insumos_ou_evidencia row={self.row_id}")
        if self.estado is EstadoAvaliacao.CONFORME and not selecionadas:
            raise ValueError(f"conforme_sem_insumos row={self.row_id} regra={self.rule_id}")
        if self.estado is EstadoAvaliacao.INCONCLUSIVO and not self.motivos:
            raise ValueError(f"inconclusivo_sem_motivo row={self.row_id} regra={self.rule_id}")
        return self


class ResultadoRegistro(StrEnum):
    ALERTA = "ALERTA"
    SEM_VIOLACAO_VERIFICADA = "SEM_VIOLACAO_VERIFICADA"
    ABSTENCAO = "ABSTENCAO"


class AgregadoRegistro(ContratoBase):
    run_id: Identificador
    row_id: RowId
    violacoes: tuple[str, ...] = ()
    conformes: tuple[str, ...] = ()
    inconclusivas: tuple[str, ...] = ()
    nao_aplicaveis: tuple[str, ...] = ()
    resultado: ResultadoRegistro

    @classmethod
    def agregar(
        cls, run_id: str, row_id: str, avaliacoes: Iterable[RuleEvaluation]
    ) -> AgregadoRegistro:
        grupos: dict[EstadoAvaliacao, list[str]] = {estado: [] for estado in EstadoAvaliacao}
        for avaliacao in _lote_de_um_registro(run_id, row_id, avaliacoes):
            grupos[avaliacao.estado].append(avaliacao.rule_id)
        violacoes = grupos[EstadoAvaliacao.VIOLACAO]
        inconclusivas = grupos[EstadoAvaliacao.INCONCLUSIVO]
        return cls(
            run_id=run_id,
            row_id=row_id,
            violacoes=tuple(sorted(violacoes)),
            conformes=tuple(sorted(grupos[EstadoAvaliacao.CONFORME])),
            inconclusivas=tuple(sorted(inconclusivas)),
            nao_aplicaveis=tuple(sorted(grupos[EstadoAvaliacao.NAO_APLICAVEL])),
            resultado=_resultado(
                bool(violacoes), bool(inconclusivas), bool(grupos[EstadoAvaliacao.CONFORME])
            ),
        )

    @model_validator(mode="after")
    def _coerencia(self) -> AgregadoRegistro:
        regras = [*self.violacoes, *self.conformes, *self.inconclusivas, *self.nao_aplicaveis]
        if len(set(regras)) != len(regras):
            raise ValueError(f"agregado_regra_repetida row={self.row_id}")
        esperado = _resultado(bool(self.violacoes), bool(self.inconclusivas), bool(self.conformes))
        if self.resultado is not esperado:
            raise ValueError(f"agregado_incoerente row={self.row_id}")
        return self


def _lote_de_um_registro(
    run_id: str, row_id: str, avaliacoes: Iterable[RuleEvaluation]
) -> list[RuleEvaluation]:
    lote = list(avaliacoes)
    for avaliacao in lote:
        if avaliacao.row_id != row_id:
            raise ValueError(f"avaliacao_de_outro_registro row={avaliacao.row_id}")
        if avaliacao.run_id != run_id:
            raise ValueError(
                f"avaliacao_de_outra_execucao run={avaliacao.run_id} esperado={run_id}"
            )
    if len({(avaliacao.metodo, avaliacao.politica_id) for avaliacao in lote}) > 1:
        raise ValueError(f"avaliacoes_de_metodos_distintos row={row_id}")
    regras = [avaliacao.rule_id for avaliacao in lote]
    if len(set(regras)) != len(regras):
        raise ValueError(f"avaliacao_repetida row={row_id}")
    return lote


def _resultado(tem_violacao: bool, tem_inconclusiva: bool, tem_conforme: bool) -> ResultadoRegistro:
    if tem_violacao:
        return ResultadoRegistro.ALERTA
    if tem_inconclusiva or not tem_conforme:
        return ResultadoRegistro.ABSTENCAO
    return ResultadoRegistro.SEM_VIOLACAO_VERIFICADA


class FalhaOperacional(ContratoBase):
    run_id: Identificador
    etapa: str
    row_id: RowId | None = None
    rule_id: RuleId | None = None
    erro: str
    ocorrida_em: InstanteUTC
