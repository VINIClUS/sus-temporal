"""Versões de conteúdo, observações de coleta e requisições de fontes."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, model_validator

from sustemporal.contracts.base import (
    Booleano,
    CanalPublicacao,
    ContratoBase,
    Falso,
    FamiliaFonte,
    InstanteUTC,
    InteiroNaoNegativo,
    Sha256Hex,
    SiglaUF,
    hash_canonico,
)
from sustemporal.contracts.temporal import CompetenciaArquivo

__all__ = [
    "ArtifactId",
    "ArtifactObservation",
    "ArtifactVersion",
    "ChaveArtefato",
    "EstadoIntegridade",
    "FormatoArquivo",
    "LinhaManifesto",
    "MembroArquivo",
    "MetadadosRemotos",
    "MotivoRequisicao",
    "ObservationId",
    "ResultadoTentativa",
    "SourceRequest",
    "TipoLinhaManifesto",
    "calcular_artifact_id",
]

ArtifactId = Annotated[str, StringConstraints(pattern=r"^art_[0-9a-f]{64}$")]
ObservationId = Annotated[str, StringConstraints(pattern=r"^obs_[0-9a-f]{32,64}$")]
_ESQUEMAS_PERMITIDOS = {"ftp", "https", "file"}


class ChaveArtefato(ContratoBase):
    fonte: FamiliaFonte
    uf: SiglaUF | None = None
    competencia_arquivo: CompetenciaArquivo | None = None
    parte: Annotated[str, StringConstraints(pattern=r"^([a-z]|_[0-9]+)$")] | None = None
    canal: CanalPublicacao
    nome_original: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    versao_publicacao: str | None = None


def calcular_artifact_id(chave: ChaveArtefato, sha256: str) -> str:
    return f"art_{hash_canonico({'chave': chave.model_dump(mode='json'), 'sha256': sha256})}"


class FormatoArquivo(StrEnum):
    DBC = "DBC"
    DBF = "DBF"
    ZIP = "ZIP"
    TXT = "TXT"
    CSV = "CSV"
    PDF = "PDF"
    HTML = "HTML"
    YAML = "YAML"
    OUTRO = "OUTRO"


class EstadoIntegridade(StrEnum):
    OK = "OK"
    QUARENTENA_TRUNCADO = "QUARENTENA_TRUNCADO"
    QUARENTENA_CHECKSUM = "QUARENTENA_CHECKSUM"
    QUARENTENA_CONTEUDO_INESPERADO = "QUARENTENA_CONTEUDO_INESPERADO"
    QUARENTENA_LEIAUTE = "QUARENTENA_LEIAUTE"
    QUARENTENA_CAMINHO_INSEGURO = "QUARENTENA_CAMINHO_INSEGURO"
    NAO_VERIFICADO = "NAO_VERIFICADO"


class MembroArquivo(ContratoBase):
    nome: str
    tamanho_bytes: InteiroNaoNegativo
    sha256: Sha256Hex | None = None
    seguro: Booleano


class ArtifactVersion(ContratoBase):
    artifact_id: ArtifactId
    chave: ChaveArtefato
    localizador: str
    sha256: Sha256Hex
    tamanho_bytes: InteiroNaoNegativo
    formato: FormatoArquivo
    caminho_conteudo: str
    leiaute_id: str | None = None
    integridade: EstadoIntegridade
    membros: tuple[MembroArquivo, ...] = ()

    @model_validator(mode="after")
    def _coerencia(self) -> ArtifactVersion:
        if self.artifact_id != calcular_artifact_id(self.chave, self.sha256):
            raise ValueError(f"artifact_id_nao_corresponde artifact_id={self.artifact_id}")
        zip_integro = (
            self.integridade is EstadoIntegridade.OK and self.formato is FormatoArquivo.ZIP
        )
        if zip_integro and not (self.membros and all(m.seguro for m in self.membros)):
            raise ValueError(f"zip_integro_exige_membros_seguros artifact={self.artifact_id}")
        return self


class ResultadoTentativa(StrEnum):
    OBTIDO = "OBTIDO"
    NAO_ENCONTRADO = "NAO_ENCONTRADO"
    FALHA_TRANSPORTE = "FALHA_TRANSPORTE"
    INTERROMPIDO = "INTERROMPIDO"
    CONTEUDO_INVALIDO = "CONTEUDO_INVALIDO"
    RECUSADO_OFFLINE = "RECUSADO_OFFLINE"


class MetadadosRemotos(ContratoBase):
    brutos: dict[str, str] = Field(default_factory=dict)
    interpretado_como_registro_oficial: Falso = False


class ArtifactObservation(ContratoBase):
    observation_id: ObservationId
    chave: ChaveArtefato
    request_sha256: Sha256Hex
    observado_em: InstanteUTC
    resultado: ResultadoTentativa
    artifact_id: ArtifactId | None = None
    sha256_obtido: Sha256Hex | None = None
    bytes_recebidos: InteiroNaoNegativo = 0
    metadados_remotos: MetadadosRemotos = Field(default_factory=MetadadosRemotos)
    ferramenta: str
    erro: str | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> ArtifactObservation:
        obtido = self.resultado is ResultadoTentativa.OBTIDO
        if obtido and self.artifact_id is None:
            raise ValueError(f"observacao_obtida_sem_artefato id={self.observation_id}")
        if self.artifact_id is not None and self.sha256_obtido is None:
            raise ValueError(f"observacao_artefato_sem_hash id={self.observation_id}")
        sem_conteudo = {
            ResultadoTentativa.NAO_ENCONTRADO,
            ResultadoTentativa.FALHA_TRANSPORTE,
            ResultadoTentativa.INTERROMPIDO,
            ResultadoTentativa.RECUSADO_OFFLINE,
        }
        if self.resultado in sem_conteudo and self.artifact_id is not None:
            raise ValueError(f"observacao_sem_conteudo_com_artefato id={self.observation_id}")
        sem_bytes = {ResultadoTentativa.NAO_ENCONTRADO, ResultadoTentativa.RECUSADO_OFFLINE}
        if self.resultado in sem_bytes and self.sha256_obtido is not None:
            raise ValueError(f"observacao_sem_bytes_com_hash id={self.observation_id}")
        if self.resultado in sem_bytes and self.bytes_recebidos > 0:
            raise ValueError(
                f"observacao_sem_bytes_com_bytes_recebidos id={self.observation_id} "
                f"bytes={self.bytes_recebidos}"
            )
        if self.artifact_id is not None and self.sha256_obtido is not None:
            esperado = calcular_artifact_id(self.chave, self.sha256_obtido)
            if self.artifact_id != esperado:
                raise ValueError(f"observacao_artefato_incoerente id={self.observation_id}")
        return self


class MotivoRequisicao(StrEnum):
    PRIMARIA = "PRIMARIA"
    AUXILIAR_DERIVADA = "AUXILIAR_DERIVADA"
    VIGILANCIA = "VIGILANCIA"
    DOCUMENTO = "DOCUMENTO"


class SourceRequest(ContratoBase):
    chave: ChaveArtefato
    localizador: str
    formato_esperado: FormatoArquivo
    sha256_esperado: Sha256Hex | None = None
    tamanho_maximo_bytes: InteiroNaoNegativo
    motivo: MotivoRequisicao

    @model_validator(mode="after")
    def _localizador_seguro(self) -> SourceRequest:
        partes = urlsplit(self.localizador)
        if partes.scheme not in _ESQUEMAS_PERMITIDOS:
            raise ValueError(f"esquema_nao_permitido localizador={self.localizador}")
        if "@" in partes.netloc or re.search(r"\s", self.localizador):
            raise ValueError(f"localizador_com_credencial_ou_espaco localizador={self.localizador}")
        return self

    def sha256(self) -> str:
        return hash_canonico(self.model_dump(mode="json"))


class TipoLinhaManifesto(StrEnum):
    OBSERVACAO = "OBSERVACAO"
    VERSAO = "VERSAO"


class LinhaManifesto(ContratoBase):
    sequencia: InteiroNaoNegativo
    tipo: TipoLinhaManifesto
    observacao: ArtifactObservation | None = None
    versao: ArtifactVersion | None = None
    anterior_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> LinhaManifesto:
        if (self.tipo is TipoLinhaManifesto.OBSERVACAO) != (self.observacao is not None):
            raise ValueError(f"linha_manifesto_tipo_incoerente sequencia={self.sequencia}")
        if (self.tipo is TipoLinhaManifesto.VERSAO) != (self.versao is not None):
            raise ValueError(f"linha_manifesto_tipo_incoerente sequencia={self.sequencia}")
        if self.sequencia < 1:
            raise ValueError(f"linha_manifesto_sequencia_invalida sequencia={self.sequencia}")
        if (self.sequencia == 1) != (self.anterior_sha256 is None):
            raise ValueError(f"linha_manifesto_cadeia_incoerente sequencia={self.sequencia}")
        return self

    def sha256(self) -> str:
        return hash_canonico(self.model_dump(mode="json"))
