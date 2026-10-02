"""Configuração de execução validada antes de qualquer processamento de dados."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from sustemporal.contracts.base import (
    Booleano,
    ContratoBase,
    FamiliaFonte,
    InstanteUTC,
    Inteiro,
    OrigemDados,
    SiglaUF,
    hash_identidade,
)
from sustemporal.contracts.experiment import (
    BootstrapSpec,
    CohortSpec,
    FreezeId,
    ModoExecucao,
    Particao,
    SplitSpec,
    contem_a_definir,
)
from sustemporal.contracts.temporal import CompetenciaProcessamento, MetodoId

__all__ = [
    "OrcamentoContrafactual",
    "PilotSpec",
    "RunConfig",
    "RuntimeConfig",
    "VerificacaoFidelidade",
    "VigilanciaSpec",
]

VerificacaoFidelidade = Literal["COMPLETA", "AMOSTRAL", "DESLIGADA"]


class RuntimeConfig(ContratoBase):
    duckdb_memoria: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*(MB|GB)$")] = "8GB"
    duckdb_threads: Inteiro = 4
    raiz_dados: str = "data"
    raiz_manifestos: str = "manifests"
    raiz_saidas: str = "outputs"
    dir_congelamentos: str = "experiments/frozen"
    rede_permitida: Booleano = False
    verificacao_fidelidade: VerificacaoFidelidade = "COMPLETA"

    @model_validator(mode="after")
    def _threads(self) -> RuntimeConfig:
        if self.duckdb_threads < 1:
            raise ValueError("duckdb_threads_deve_ser_positivo")
        return self


class PilotSpec(ContratoBase):
    uf: SiglaUF = "SP"
    competencias_processamento: tuple[CompetenciaProcessamento, ...]
    territorio: str
    familias_fontes: tuple[FamiliaFonte, ...]

    @model_validator(mode="after")
    def _competencias(self) -> PilotSpec:
        if not self.competencias_processamento:
            raise ValueError("piloto_sem_competencias")
        if len(set(self.competencias_processamento)) != len(self.competencias_processamento):
            raise ValueError("piloto_competencia_repetida")
        return self


class VigilanciaSpec(ContratoBase):
    janela_competencias: Inteiro = 6
    familias_fontes: tuple[FamiliaFonte, ...] = ()
    uf: SiglaUF = "SP"
    cadencia_dias: Inteiro | None = None
    duracao_meses: Inteiro | None = None

    @model_validator(mode="after")
    def _janela(self) -> VigilanciaSpec:
        if self.janela_competencias < 1:
            raise ValueError("vigilancia_janela_deve_ser_positiva")
        return self

    @model_validator(mode="after")
    def _cadencia_e_duracao(self) -> VigilanciaSpec:
        if self.cadencia_dias is not None and self.cadencia_dias < 1:
            raise ValueError(
                f"vigilancia_cadencia_deve_ser_positiva cadencia_dias={self.cadencia_dias}"
            )
        if self.duracao_meses is not None and self.duracao_meses < 1:
            raise ValueError(
                f"vigilancia_duracao_deve_ser_positiva duracao_meses={self.duracao_meses}"
            )
        return self


class OrcamentoContrafactual(ContratoBase):
    max_operacoes: Inteiro = 3
    max_candidatos: Inteiro = 1000

    @model_validator(mode="after")
    def _positivo(self) -> OrcamentoContrafactual:
        if self.max_operacoes < 1 or self.max_candidatos < 1:
            raise ValueError(
                f"orcamento_invalido max_operacoes={self.max_operacoes} "
                f"max_candidatos={self.max_candidatos}"
            )
        return self


class RunConfig(ContratoBase):
    versao: Literal["1"]
    modo: ModoExecucao = ModoExecucao.EXPLORATORIO
    origem_dados: OrigemDados | None = None
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    piloto: PilotSpec | None = None
    vigilancia: VigilanciaSpec | None = None
    coorte: CohortSpec | None = None
    particoes: SplitSpec | None = None
    bootstrap: BootstrapSpec = Field(default_factory=BootstrapSpec)
    metodos: tuple[MetodoId, ...] = ()
    politica_id: str | None = None
    semente: Inteiro = 2027
    contrafactual: OrcamentoContrafactual = Field(default_factory=OrcamentoContrafactual)
    corte_observacao: InstanteUTC | None = None
    freeze_id: FreezeId | None = None
    catalogos: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _confirmatorio(self) -> RunConfig:
        if self.modo is not ModoExecucao.CONFIRMATORIO:
            return self
        if self.freeze_id is None:
            raise ValueError("confirmatorio_exige_freeze_id")
        if self.origem_dados is not OrigemDados.REAL:
            raise ValueError("confirmatorio_exige_dados_reais")
        if self.runtime.rede_permitida:
            raise ValueError("confirmatorio_exige_rede_desligada")
        if contem_a_definir(self.model_dump(mode="json")):
            raise ValueError("confirmatorio_com_valor_a_definir")
        return self

    @model_validator(mode="after")
    def _recortes_dentro_das_particoes(self) -> RunConfig:
        if self.particoes is None:
            return self
        intervalos = self.particoes.intervalos
        desenvolvimento = next(i for i in intervalos if i.particao is Particao.DESENVOLVIMENTO)
        competencias = self.piloto.competencias_processamento if self.piloto else ()
        if any(not desenvolvimento.inicio <= c <= desenvolvimento.fim for c in competencias):
            raise ValueError("piloto_fora_do_desenvolvimento")
        coorte = self.coorte
        if coorte and (intervalos[0].inicio < coorte.inicio or coorte.fim < intervalos[-1].fim):
            raise ValueError(f"particoes_fora_da_coorte coorte={coorte.cohort_id}")
        return self

    @property
    def config_hash(self) -> str:
        return hash_identidade(self)
