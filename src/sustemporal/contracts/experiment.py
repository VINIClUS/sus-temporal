"""Coorte, partições temporais, atributos, execuções, congelamento e decisões de portão."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationInfo, model_validator

from sustemporal.contracts.artifacts import ArtifactId
from sustemporal.contracts.base import (
    Booleano,
    CodigoMunicipio6,
    CodigoMunicipio7,
    Confirmacao,
    ContratoBase,
    Data,
    DecimalExato,
    DocRef,
    Identificador,
    InstanteUTC,
    Inteiro,
    InteiroNaoNegativo,
    OrigemDados,
    Proveniencia,
    ReferenciaDecisao,
    Sha256Hex,
    SiglaUF,
    Verdadeiro,
    hash_canonico,
)
from sustemporal.contracts.records import DatasetRef, EsquemaCanonico, PapelColuna, SchemaId
from sustemporal.contracts.rules import FamiliaRegra
from sustemporal.contracts.temporal import CompetenciaProcessamento, MetodoId

__all__ = [
    "A_DEFINIR",
    "Ambiente",
    "Atributo",
    "BootstrapSpec",
    "CodeVersion",
    "CohortSpec",
    "CorrecaoMultiplicidade",
    "CriterioGeografico",
    "DecisaoPortao",
    "EstadoExecucao",
    "FeatureSpec",
    "FreezeId",
    "FreezeManifest",
    "IntervaloParticao",
    "ModoExecucao",
    "MunicipioTerritorio",
    "Particao",
    "PertencaGeografica",
    "Portao",
    "RunResult",
    "SplitManifest",
    "SplitSpec",
    "Territorio",
    "TipoExecucao",
    "contem_a_definir",
]

A_DEFINIR = "A_DEFINIR"
_PROVISORIO = "frz_provisorio"
FreezeId = Annotated[str, StringConstraints(pattern=r"^frz_[0-9a-f]{64}$")]


def contem_a_definir(conteudo: object) -> bool:
    if isinstance(conteudo, str):
        return conteudo == A_DEFINIR
    if isinstance(conteudo, dict):
        return any(contem_a_definir(k) or contem_a_definir(v) for k, v in conteudo.items())
    if isinstance(conteudo, list | tuple):
        return any(contem_a_definir(v) for v in conteudo)
    return False


class ModoExecucao(StrEnum):
    EXPLORATORIO = "EXPLORATORIO"
    CONFIRMATORIO = "CONFIRMATORIO"


class PertencaGeografica(StrEnum):
    FIXA = "FIXA"
    HISTORICA = "HISTORICA"
    A_DEFINIR = "A_DEFINIR"


class CriterioGeografico(StrEnum):
    MUNICIPIO_ESTABELECIMENTO = "MUNICIPIO_ESTABELECIMENTO"


class MunicipioTerritorio(ContratoBase):
    ibge7: CodigoMunicipio7
    ibge6: CodigoMunicipio6
    nome: str
    regiao: str

    @model_validator(mode="after")
    def _prefixo(self) -> MunicipioTerritorio:
        if not self.ibge7.startswith(self.ibge6):
            raise ValueError(f"ibge6_nao_e_prefixo_do_ibge7 municipio={self.nome}")
        return self


class Territorio(ContratoBase):
    territorio_id: Identificador
    descricao: str
    uf: SiglaUF
    municipios: tuple[MunicipioTerritorio, ...]
    proveniencia: Proveniencia
    confirmacao: Confirmacao
    fontes: tuple[DocRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unicos(self) -> Territorio:
        codigos = [m.ibge7 for m in self.municipios]
        if not codigos or len(set(codigos)) != len(codigos):
            raise ValueError(f"territorio_municipios_vazios_ou_repetidos id={self.territorio_id}")
        return self


class CohortSpec(ContratoBase):
    cohort_id: Identificador
    uf: SiglaUF
    territorio: str
    criterio_geografico: CriterioGeografico = CriterioGeografico.MUNICIPIO_ESTABELECIMENTO
    pertenca: PertencaGeografica = PertencaGeografica.A_DEFINIR
    inicio: CompetenciaProcessamento
    fim: CompetenciaProcessamento
    instrumentos: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _intervalo(self) -> CohortSpec:
        if self.fim < self.inicio:
            raise ValueError(f"coorte_intervalo_invertido coorte={self.cohort_id}")
        return self


class Particao(StrEnum):
    DESENVOLVIMENTO = "DESENVOLVIMENTO"
    CALIBRACAO = "CALIBRACAO"
    TESTE = "TESTE"


class IntervaloParticao(ContratoBase):
    particao: Particao
    inicio: CompetenciaProcessamento
    fim: CompetenciaProcessamento


class SplitSpec(ContratoBase):
    base_temporal: Literal["PROCESSAMENTO"] = "PROCESSAMENTO"
    intervalos: tuple[IntervaloParticao, ...]

    @model_validator(mode="after")
    def _ordenados_e_disjuntos(self) -> SplitSpec:
        nomes = [intervalo.particao for intervalo in self.intervalos]
        if nomes != list(Particao):
            raise ValueError("particoes_fora_da_ordem_desenvolvimento_calibracao_teste")
        anterior = None
        for intervalo in self.intervalos:
            if intervalo.fim < intervalo.inicio:
                raise ValueError(f"particao_invertida particao={intervalo.particao}")
            if anterior is not None and intervalo.inicio <= anterior:
                raise ValueError(f"particoes_sobrepostas particao={intervalo.particao}")
            anterior = intervalo.fim
        return self


class SplitManifest(ContratoBase):
    split_id: Identificador
    spec: SplitSpec
    dataset_hash: str
    linhas_por_particao: dict[Particao, InteiroNaoNegativo]
    hash_por_particao: dict[Particao, str]
    artefatos_inspecionados: tuple[ArtifactId, ...] = ()
    artefatos_teste: tuple[ArtifactId, ...] = ()

    @model_validator(mode="after")
    def _coerencia(self) -> SplitManifest:
        declaradas = {intervalo.particao for intervalo in self.spec.intervalos}
        contadas = (set(self.linhas_por_particao), set(self.hash_por_particao))
        if any(particoes != declaradas for particoes in contadas):
            raise ValueError(f"split_manifesto_particoes_divergentes split={self.split_id}")
        if set(self.artefatos_teste) & set(self.artefatos_inspecionados):
            raise ValueError(f"teste_contem_artefato_inspecionado split={self.split_id}")
        return self


class Atributo(ContratoBase):
    nome: Identificador
    schema_id: SchemaId
    coluna: str
    transformacao: str


class FeatureSpec(ContratoBase):
    feature_set_id: Identificador
    atributos: tuple[Atributo, ...]

    @model_validator(mode="after")
    def _nomes_unicos(self) -> FeatureSpec:
        nomes = [atributo.nome for atributo in self.atributos]
        if len(set(nomes)) != len(nomes):
            raise ValueError(f"atributo_repetido feature_set={self.feature_set_id}")
        return self

    def colunas_proibidas(self, esquema: EsquemaCanonico) -> tuple[str, ...]:
        return tuple(
            atributo.coluna
            for atributo in self.atributos
            if atributo.schema_id == esquema.schema_id
            and esquema.papel_de(atributo.coluna) is not PapelColuna.ATRIBUTO
        )


class CorrecaoMultiplicidade(StrEnum):
    HOLM = "HOLM"
    BONFERRONI = "BONFERRONI"
    SEM_TESTE_FORMAL = "SEM_TESTE_FORMAL"
    A_DEFINIR = "A_DEFINIR"


class BootstrapSpec(ContratoBase):
    reamostragens: Inteiro = 2000
    semente: Inteiro = 2027
    unidade: Literal["ESTABELECIMENTO"] = "ESTABELECIMENTO"
    confianca: DecimalExato = Decimal("0.95")
    sensibilidade: Literal["BLOCOS_TEMPORAIS"] = "BLOCOS_TEMPORAIS"
    correcao: CorrecaoMultiplicidade = CorrecaoMultiplicidade.A_DEFINIR

    @model_validator(mode="after")
    def _intervalo_definido(self) -> BootstrapSpec:
        if self.reamostragens < 1 or not Decimal(0) < self.confianca < Decimal(1):
            raise ValueError(
                f"bootstrap_invalido reamostragens={self.reamostragens} confianca={self.confianca}"
            )
        return self


class CodeVersion(ContratoBase):
    commit: str
    sujo: Booleano
    versao_pacote: str


class Ambiente(ContratoBase):
    python: str
    plataforma: str
    pacotes: dict[str, str] = Field(default_factory=dict)
    uv_lock_sha256: Sha256Hex | None = None


class TipoExecucao(StrEnum):
    AQUISICAO = "AQUISICAO"
    INGESTAO = "INGESTAO"
    PILOTO = "PILOTO"
    VALIDACAO = "VALIDACAO"
    BASELINE_ML = "BASELINE_ML"
    AVALIACAO = "AVALIACAO"
    REPRODUCAO = "REPRODUCAO"


class EstadoExecucao(StrEnum):
    CONCLUIDA = "CONCLUIDA"
    PARCIAL = "PARCIAL"
    FALHOU = "FALHOU"


class RunResult(ContratoBase):
    run_id: Identificador
    tipo: TipoExecucao
    metodo: MetodoId | None = None
    politica_id: str | None = None
    modo: ModoExecucao
    config_hash: Sha256Hex
    codigo: CodeVersion
    ambiente: Ambiente
    snapshot_set_id: str | None = None
    catalogo_regras_sha256: Sha256Hex | None = None
    semente: Inteiro | None = None
    entradas: tuple[DatasetRef, ...] = ()
    saidas: tuple[DatasetRef, ...] = ()
    falhas: InteiroNaoNegativo = 0
    estado: EstadoExecucao
    iniciado_em: InstanteUTC
    concluido_em: InstanteUTC | None = None
    freeze_id: FreezeId | None = None
    origem_dados: OrigemDados

    @model_validator(mode="after")
    def _confirmatorio(self) -> RunResult:
        if self.modo is not ModoExecucao.CONFIRMATORIO:
            return self
        if self.freeze_id is None or self.codigo.sujo or self.origem_dados is not OrigemDados.REAL:
            raise ValueError(f"execucao_confirmatoria_invalida run={self.run_id}")
        return self


class FreezeManifest(ContratoBase):
    freeze_id: str
    criado_em: InstanteUTC
    config_hash: Sha256Hex
    codigo: CodeVersion
    ambiente: Ambiente
    catalogos_sha256: dict[str, Sha256Hex]
    datasets: tuple[DatasetRef, ...]
    split: SplitManifest | None = None
    features: FeatureSpec | None = None
    bootstrap: BootstrapSpec
    metricas: tuple[str, ...]
    comparacoes_primarias: tuple[str, ...]
    margens: dict[str, DecimalExato] = Field(default_factory=dict)
    decisao_g0: ReferenciaDecisao

    @classmethod
    def calcular_id(cls, conteudo: dict[str, Any]) -> str:
        return f"frz_{hash_canonico(conteudo)}"

    @classmethod
    def criar(cls, **campos: Any) -> FreezeManifest:
        provisorio = cls.model_validate(
            {**campos, "freeze_id": _PROVISORIO}, context={_PROVISORIO: True}
        )
        conteudo = provisorio.model_dump(mode="json", exclude={"freeze_id"})
        return cls.model_validate({**conteudo, "freeze_id": cls.calcular_id(conteudo)})

    @model_validator(mode="after")
    def _identidade(self, info: ValidationInfo) -> FreezeManifest:
        conteudo = self.model_dump(mode="json", exclude={"freeze_id"})
        if contem_a_definir(conteudo):
            raise ValueError("congelamento_com_valor_a_definir")
        if self.freeze_id == _PROVISORIO and (info.context or {}).get(_PROVISORIO):
            return self
        if self.freeze_id != self.calcular_id(conteudo):
            raise ValueError("freeze_id_nao_corresponde_ao_conteudo")
        return self


class Portao(StrEnum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"


_DECISOES_POR_PORTAO = {
    Portao.G0: {"CONTINUAR", "AMPLIAR_SP", "RESTRINGIR_FAMILIAS", "REFORMULAR"},
    Portao.G1: {"APROVADO", "REPROVADO"},
    Portao.G2: {"ABRIR_TESTE", "ADIAR"},
}


class DecisaoPortao(ContratoBase):
    portao: Portao
    decisao: str
    data: Data
    responsaveis: tuple[Annotated[str, StringConstraints(pattern=r"\S")], ...]
    registrado_por_humano: Verdadeiro
    evidencias: tuple[str, ...] = ()
    freeze_id: FreezeId | None = None
    familias_aprovadas: tuple[FamiliaRegra, ...] = ()
    observacoes: str = ""

    @model_validator(mode="after")
    def _coerencia(self) -> DecisaoPortao:
        if self.decisao not in _DECISOES_POR_PORTAO[self.portao]:
            raise ValueError(f"decisao_invalida portao={self.portao} decisao={self.decisao}")
        if not self.responsaveis:
            raise ValueError(f"decisao_sem_responsavel portao={self.portao}")
        if self.portao is Portao.G2 and self.freeze_id is None:
            raise ValueError("decisao_g2_exige_freeze_id")
        if self.decisao == "RESTRINGIR_FAMILIAS" and not self.familias_aprovadas:
            raise ValueError("decisao_restringir_familias_sem_familias")
        return self
