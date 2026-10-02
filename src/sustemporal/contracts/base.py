"""Tipos-base compartilhados pelos contratos."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal, NoReturn, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    StringConstraints,
    model_validator,
)

__all__ = [
    "Booleano",
    "CanalPublicacao",
    "CodigoCBO",
    "CodigoCNES",
    "CodigoMunicipio6",
    "CodigoMunicipio7",
    "CodigoProcedimento",
    "CodigoUF",
    "Confirmacao",
    "ContratoBase",
    "Data",
    "DatasetId",
    "DecimalExato",
    "DocRef",
    "EstadoDocumento",
    "Falso",
    "FamiliaFonte",
    "FileRef",
    "Identificador",
    "InstanteUTC",
    "Inteiro",
    "InteiroNaoNegativo",
    "MapaCongelado",
    "MotivoAusencia",
    "OrigemDados",
    "Proveniencia",
    "Sha256Hex",
    "SiglaUF",
    "ValorMonetario",
    "ValorNormalizado",
    "Verdadeiro",
    "hash_canonico",
    "json_canonico",
]


class MapaCongelado(dict[Any, Any]):
    """Dicionário que recusa mutação; contratos congelados guardam mapas assim."""

    def _recusar(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise TypeError("mapa_congelado_nao_aceita_mutacao")

    __setitem__ = __delitem__ = __ior__ = _recusar
    clear = pop = popitem = setdefault = update = _recusar

    def __reduce__(self) -> tuple[type[MapaCongelado], tuple[dict[Any, Any]]]:
        return (MapaCongelado, (dict(self),))


class ContratoBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", coerce_numbers_to_str=False)

    @model_validator(mode="after")
    def _congelar_mapas(self) -> Self:
        for nome, valor in list(self.__dict__.items()):
            if type(valor) is dict:
                object.__setattr__(self, nome, MapaCongelado(valor))
        return self


CodigoProcedimento = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9]{10}$")]
CodigoCBO = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9A-Z]{6}$")]
CodigoCNES = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9]{7}$")]
CodigoMunicipio6 = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9]{6}$")]
CodigoMunicipio7 = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9]{7}$")]
CodigoUF = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9]{2}$")]
SiglaUF = Annotated[str, Strict(), StringConstraints(pattern=r"^[A-Z]{2}$")]
Sha256Hex = Annotated[str, Strict(), StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identificador = Annotated[str, Strict(), StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
DatasetId = Annotated[str, Strict(), StringConstraints(pattern=r"^ds_[0-9a-f]{64}$")]


def _inteiro(valor: object) -> object:
    if isinstance(valor, bool | float):
        raise ValueError(f"inteiro_invalido valor={valor!r}")
    if isinstance(valor, str):
        if not re.fullmatch(r"-?[0-9]+", valor):
            raise ValueError(f"inteiro_invalido valor={valor!r}")
        return int(valor)
    return valor


def _decimal(valor: object) -> object:
    if isinstance(valor, bool | float):
        raise ValueError(f"decimal_exige_texto_ou_inteiro valor={valor!r}")
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, str):
        if not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", valor):
            raise ValueError(f"decimal_invalido valor={valor!r}")
        try:
            return Decimal(valor)
        except InvalidOperation as erro:
            raise ValueError(f"decimal_invalido valor={valor!r}") from erro
    return valor


def _duas_casas(valor: Decimal) -> Decimal:
    expoente = valor.as_tuple().exponent
    if not isinstance(expoente, int) or expoente < -2:
        raise ValueError(f"valor_monetario_mais_de_duas_casas valor={valor}")
    return valor


def _booleano(valor: object) -> object:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor in {"true", "false"}:
        return valor == "true"
    raise ValueError(f"booleano_invalido valor={valor!r}")


def _instante(valor: object) -> object:
    if isinstance(valor, datetime):
        return valor
    if not isinstance(valor, str):
        raise ValueError(f"instante_exige_datetime_ou_iso valor={valor!r}")
    try:
        return datetime.fromisoformat(valor)
    except ValueError as erro:
        raise ValueError(f"instante_invalido valor={valor!r}") from erro


def _exige_utc(valor: datetime) -> datetime:
    if valor.tzinfo is None or valor.utcoffset() != timedelta(0):
        raise ValueError(f"instante_deve_ser_utc valor={valor.isoformat()}")
    return valor.astimezone(UTC)


def _data(valor: object) -> object:
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor)
        except ValueError as erro:
            raise ValueError(f"data_invalida valor={valor!r}") from erro
    return valor


Inteiro = Annotated[int, BeforeValidator(_inteiro)]
InteiroNaoNegativo = Annotated[int, BeforeValidator(_inteiro), Field(ge=0)]
DecimalExato = Annotated[Decimal, BeforeValidator(_decimal)]
ValorMonetario = Annotated[Decimal, BeforeValidator(_decimal), AfterValidator(_duas_casas)]
Booleano = Annotated[bool, BeforeValidator(_booleano)]
Verdadeiro = Annotated[Literal[True], BeforeValidator(_booleano)]
Falso = Annotated[Literal[False], BeforeValidator(_booleano)]
InstanteUTC = Annotated[datetime, BeforeValidator(_instante), AfterValidator(_exige_utc)]
Data = Annotated[date, BeforeValidator(_data)]


class FamiliaFonte(StrEnum):
    SIA_PA = "SIA_PA"
    CNES_ST = "CNES_ST"
    CNES_PF = "CNES_PF"
    CNES_SR = "CNES_SR"
    CNES_HB = "CNES_HB"
    SIGTAP = "SIGTAP"
    TERRITORIO_DRS = "TERRITORIO_DRS"
    DOCUMENTO = "DOCUMENTO"


class CanalPublicacao(StrEnum):
    ATUAL = "ATUAL"
    PRELIMINAR = "PRELIMINAR"
    HISTORICO = "HISTORICO"
    IMPORTACAO_MANUAL = "IMPORTACAO_MANUAL"
    DESCONHECIDO = "DESCONHECIDO"


class Proveniencia(StrEnum):
    OFICIAL_DOCUMENTO = "OFICIAL_DOCUMENTO"
    OFICIAL_ARQUIVO = "OFICIAL_ARQUIVO"
    OFICIAL_VISTO_EM_BUSCA = "OFICIAL_VISTO_EM_BUSCA"
    SECUNDARIA = "SECUNDARIA"
    INFERIDA = "INFERIDA"
    INFERIDA_PILOTO = "INFERIDA_PILOTO"


class Confirmacao(StrEnum):
    CONFIRMADO = "CONFIRMADO"
    A_CONFIRMAR = "A_CONFIRMAR"


class OrigemDados(StrEnum):
    SINTETICO = "SINTETICO"
    REAL = "REAL"


class MotivoAusencia(StrEnum):
    VAZIO = "VAZIO"
    DESCONHECIDO = "DESCONHECIDO"
    NAO_APLICAVEL = "NAO_APLICAVEL"
    SENTINELA = "SENTINELA"
    CODIFICACAO_INVALIDA = "CODIFICACAO_INVALIDA"


class ValorNormalizado(ContratoBase):
    bruto: str | None
    valor: str | None
    motivo: MotivoAusencia | None = None

    @model_validator(mode="after")
    def _valor_xor_motivo(self) -> ValorNormalizado:
        if (self.valor is None) == (self.motivo is None):
            raise ValueError("valor_normalizado_exige_valor_ou_motivo")
        if self.valor == "":
            raise ValueError("valor_vazio_exige_motivo_vazio")
        return self


class EstadoDocumento(StrEnum):
    PRESERVADO = "PRESERVADO"
    PENDENTE = "PENDENTE"


class DocRef(ContratoBase):
    doc_id: Identificador
    titulo: str
    url: str | None = None
    localizador: str | None = None
    trecho: Annotated[str, StringConstraints(max_length=400)] | None = None
    estado: EstadoDocumento
    sha256: Sha256Hex | None = None
    proveniencia: Proveniencia
    confirmacao: Confirmacao = Confirmacao.A_CONFIRMAR

    @model_validator(mode="after")
    def _preservado_exige_hash(self) -> DocRef:
        if (self.estado is EstadoDocumento.PRESERVADO) != (self.sha256 is not None):
            raise ValueError(f"docref_estado_e_hash_incoerentes doc_id={self.doc_id}")
        return self


class FileRef(ContratoBase):
    caminho: str
    sha256: Sha256Hex


def json_canonico(conteudo: object) -> str:
    return json.dumps(conteudo, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_canonico(conteudo: object) -> str:
    return hashlib.sha256(json_canonico(conteudo).encode("utf-8")).hexdigest()
