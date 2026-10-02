"""Tipos de tempo não intercambiáveis, políticas temporais e seleção de versões."""

from __future__ import annotations

import re
from enum import StrEnum
from functools import total_ordering
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic import ValidationInfo, model_validator
from pydantic_core import core_schema

from sustemporal.contracts.base import (
    Booleano,
    CanalPublicacao,
    ContratoBase,
    DocRef,
    EstadoDocumento,
    FamiliaFonte,
    Identificador,
    InstanteUTC,
    Inteiro,
    hash_canonico,
)

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
    from pydantic.json_schema import JsonSchemaValue

__all__ = [
    "BaseTemporal",
    "CompetenciaArquivo",
    "CompetenciaAtendimento",
    "CompetenciaProcessamento",
    "CriterioTemporal",
    "EstadoSelecao",
    "InstanteObservacao",
    "MetodoId",
    "PoliticaTemporal",
    "SelecaoVersao",
    "SnapshotSet",
    "TipoPolitica",
    "TipoTempo",
    "VigenciaDocumentada",
]

_PADRAO_COMPETENCIA = re.compile(r"^([0-9]{4})(0[1-9]|1[0-2])$")
_PADRAO_ARTEFATO = r"^art_[0-9a-f]{64}$"
_PADRAO_OBSERVACAO = r"^obs_[0-9a-f]{32,64}$"
_PADRAO_HASH_LOGICO = r"^lh1:[0-9a-f]{64}$"
_PROVISORIO = "snap_provisorio"

InstanteObservacao = InstanteUTC


class TipoTempo(StrEnum):
    ATENDIMENTO = "ATENDIMENTO"
    PROCESSAMENTO = "PROCESSAMENTO"
    ARQUIVO = "ARQUIVO"
    VIGENCIA_DOCUMENTADA = "VIGENCIA_DOCUMENTADA"
    OBSERVACAO = "OBSERVACAO"


@total_ordering
class _Competencia:
    """Competência AAAAMM de um tipo de tempo; tipos diferentes não se comparam."""

    tipo: ClassVar[TipoTempo]
    __slots__ = ("_valor",)

    def __init__(self, valor: str) -> None:
        if not isinstance(valor, str) or not _PADRAO_COMPETENCIA.fullmatch(valor):
            raise ValueError(f"competencia_invalida tipo={self.tipo} valor={valor!r}")
        self._valor = valor

    @property
    def valor(self) -> str:
        return self._valor

    @property
    def ano(self) -> int:
        return int(self._valor[:4])

    @property
    def mes(self) -> int:
        return int(self._valor[4:])

    def deslocar(self, meses: int) -> Self:
        indice = self.ano * 12 + (self.mes - 1) + meses
        return type(self)(f"{indice // 12:04d}{indice % 12 + 1:02d}")

    def __eq__(self, outro: object) -> bool:
        if not isinstance(outro, _Competencia):
            return NotImplemented
        return type(outro) is type(self) and self._valor == outro._valor

    def __lt__(self, outro: object) -> bool:
        if not isinstance(outro, _Competencia) or type(outro) is not type(self):
            nome = type(outro).__name__
            raise TypeError(f"comparacao_entre_tempos_distintos {self.tipo} x {nome}")
        return self._valor < outro._valor

    def __hash__(self) -> int:
        return hash((self.tipo, self._valor))

    def __repr__(self) -> str:
        return f"{type(self).__name__}('{self._valor}')"

    def __str__(self) -> str:
        return self._valor

    @classmethod
    def _validar(cls, valor: object) -> Self:
        if isinstance(valor, cls):
            return valor
        if isinstance(valor, _Competencia):
            raise ValueError(f"tempo_incompativel esperado={cls.tipo} recebido={valor.tipo}")
        if not isinstance(valor, str):
            raise ValueError(f"competencia_exige_texto valor={valor!r}")
        return cls(valor)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, origem: Any, manipulador: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validar,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, esquema: core_schema.CoreSchema, manipulador: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "pattern": _PADRAO_COMPETENCIA.pattern, "title": cls.__name__}


class CompetenciaAtendimento(_Competencia):
    tipo = TipoTempo.ATENDIMENTO


class CompetenciaProcessamento(_Competencia):
    tipo = TipoTempo.PROCESSAMENTO


class CompetenciaArquivo(_Competencia):
    tipo = TipoTempo.ARQUIVO


class TipoPolitica(StrEnum):
    DOCUMENTADA = "DOCUMENTADA"
    ALTERNATIVA_EXPLORATORIA = "ALTERNATIVA_EXPLORATORIA"
    NAO_RESOLVIDA = "NAO_RESOLVIDA"


class MetodoId(StrEnum):
    B_ATEND = "B_ATEND"
    B_PROC = "B_PROC"
    B_ML = "B_ML"
    M_TEMP = "M_TEMP"
    CONTROLE_TRIVIAL = "CONTROLE_TRIVIAL"


class BaseTemporal(StrEnum):
    ATENDIMENTO = "ATENDIMENTO"
    PROCESSAMENTO = "PROCESSAMENTO"


class CriterioTemporal(ContratoBase):
    fonte: FamiliaFonte
    base: BaseTemporal
    deslocamento_meses: Inteiro = 0
    canal: CanalPublicacao | None = None


class PoliticaTemporal(ContratoBase):
    politica_id: Identificador
    tipo: TipoPolitica
    metodo: MetodoId
    criterios: tuple[CriterioTemporal, ...]
    documento: DocRef | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> PoliticaTemporal:
        fontes = [criterio.fonte for criterio in self.criterios]
        if len(fontes) != len(set(fontes)):
            raise ValueError(f"politica_com_fonte_repetida politica={self.politica_id}")
        if self.tipo is TipoPolitica.NAO_RESOLVIDA and self.criterios:
            raise ValueError(f"politica_nao_resolvida_sem_criterios politica={self.politica_id}")
        if self.tipo is not TipoPolitica.NAO_RESOLVIDA and not self.criterios:
            raise ValueError(f"politica_sem_criterios politica={self.politica_id}")
        if self.tipo is TipoPolitica.DOCUMENTADA and self.documento is None:
            raise ValueError(f"politica_documentada_exige_documento politica={self.politica_id}")
        return self

    @property
    def documento_pendente(self) -> bool:
        return self.documento is not None and self.documento.estado is EstadoDocumento.PENDENTE


class VigenciaDocumentada(ContratoBase):
    inicio: str | None = None
    fim: str | None = None
    referente_a: TipoTempo
    documento: DocRef

    @model_validator(mode="after")
    def _limites(self) -> VigenciaDocumentada:
        for limite in (self.inicio, self.fim):
            if limite is not None and not _PADRAO_COMPETENCIA.fullmatch(limite):
                raise ValueError(f"vigencia_limite_invalido valor={limite!r}")
        if self.inicio and self.fim and self.inicio > self.fim:
            raise ValueError("vigencia_inicio_apos_fim")
        return self

    def contem(self, competencia: _Competencia) -> bool:
        if competencia.tipo is not self.referente_a:
            raise TypeError(f"vigencia_refere_{self.referente_a}_recebeu_{competencia.tipo}")
        depois_do_inicio = self.inicio is None or competencia.valor >= self.inicio
        antes_do_fim = self.fim is None or competencia.valor <= self.fim
        return depois_do_inicio and antes_do_fim


class EstadoSelecao(StrEnum):
    SELECIONADA = "SELECIONADA"
    AUSENTE = "AUSENTE"
    AMBIGUA = "AMBIGUA"
    INCOMPLETA = "INCOMPLETA"
    EM_QUARENTENA = "EM_QUARENTENA"
    FORA_DO_CORTE = "FORA_DO_CORTE"
    NAO_RESOLVIDA = "NAO_RESOLVIDA"


class SelecaoVersao(ContratoBase):
    fonte: FamiliaFonte
    base: BaseTemporal | None
    competencia_requerida: CompetenciaArquivo | None
    estado: EstadoSelecao
    artifact_ids: tuple[str, ...] = ()
    observation_ids: tuple[str, ...] = ()
    motivo: str

    @model_validator(mode="after")
    def _coerencia(self) -> SelecaoVersao:
        if any(not re.fullmatch(_PADRAO_ARTEFATO, a) for a in self.artifact_ids):
            raise ValueError("selecao_artifact_id_invalido")
        quantidade = len(self.artifact_ids)
        if self.estado is EstadoSelecao.SELECIONADA and quantidade == 0:
            raise ValueError(f"selecao_sem_artefato fonte={self.fonte}")
        if self.estado is EstadoSelecao.AMBIGUA and quantidade < 2:
            raise ValueError(f"selecao_ambigua_exige_candidatos fonte={self.fonte}")
        vazios = {EstadoSelecao.AUSENTE, EstadoSelecao.NAO_RESOLVIDA}
        if self.estado in vazios and quantidade:
            raise ValueError(f"selecao_vazia_com_artefatos fonte={self.fonte}")
        return self


class SnapshotSet(ContratoBase):
    snapshot_id: str
    artifact_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    dataset_hashes: tuple[str, ...]
    selecoes: tuple[SelecaoVersao, ...]
    corte_observacao: InstanteObservacao | None = None
    congelado: Booleano = False

    @classmethod
    def calcular_id(cls, conteudo: dict[str, Any]) -> str:
        return f"snap_{hash_canonico(conteudo)}"

    @classmethod
    def criar(cls, **campos: Any) -> SnapshotSet:
        provisorio = cls.model_validate(
            {**campos, "snapshot_id": _PROVISORIO}, context={_PROVISORIO: True}
        )
        conteudo = provisorio.model_dump(mode="json", exclude={"snapshot_id"})
        return cls.model_validate({**conteudo, "snapshot_id": cls.calcular_id(conteudo)})

    @model_validator(mode="after")
    def _identidade(self, info: ValidationInfo) -> SnapshotSet:
        if self.artifact_ids != tuple(sorted(set(self.artifact_ids))):
            raise ValueError("snapshot_artefatos_devem_ser_ordenados_e_unicos")
        self._formatos()
        self._selecoes_contidas()
        if self.snapshot_id == _PROVISORIO and (info.context or {}).get(_PROVISORIO):
            return self
        conteudo = self.model_dump(mode="json", exclude={"snapshot_id"})
        if self.snapshot_id != self.calcular_id(conteudo):
            raise ValueError("snapshot_id_nao_corresponde_ao_conteudo")
        return self

    def _formatos(self) -> None:
        padroes = (
            (self.artifact_ids, _PADRAO_ARTEFATO),
            (self.observation_ids, _PADRAO_OBSERVACAO),
            (self.dataset_hashes, _PADRAO_HASH_LOGICO),
        )
        for valores, padrao in padroes:
            if any(not re.fullmatch(padrao, valor) for valor in valores):
                raise ValueError(f"snapshot_identificador_invalido padrao={padrao}")

    def _selecoes_contidas(self) -> None:
        selecionados = {a for s in self.selecoes for a in s.artifact_ids}
        if not selecionados <= set(self.artifact_ids):
            raise ValueError("snapshot_selecao_fora_do_conjunto")
        citadas = {o for s in self.selecoes for o in s.observation_ids}
        malformadas = any(not re.fullmatch(_PADRAO_OBSERVACAO, o) for o in citadas)
        if malformadas or not citadas <= set(self.observation_ids):
            raise ValueError("snapshot_selecao_com_observacao_externa")
