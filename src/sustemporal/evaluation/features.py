"""Lista positiva de atributos do classificador histórico, com auditoria de origem (T10)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import (
    COLUNAS_PROIBIDAS_EM_ATRIBUTOS,
    Atributo,
    FeatureSpec,
    validar_features,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sustemporal.contracts.records import EsquemaCanonico

__all__ = [
    "CATEGORICA",
    "COLUNAS_DE_PARTICAO",
    "FEATURES_PADRAO",
    "NUMERICA",
    "TRANSFORMACOES",
    "OrigemAtributo",
    "auditar_features",
]

logger = logging.getLogger(__name__)

CATEGORICA = "CATEGORICA"
NUMERICA = "NUMERICA"
TRANSFORMACOES = frozenset({CATEGORICA, NUMERICA})
COLUNAS_DE_PARTICAO = frozenset({"competencia_processamento"})


def _atributo(coluna: str, transformacao: str = CATEGORICA) -> Atributo:
    return Atributo(nome=coluna, schema_id="sia_pa.v1", coluna=coluna, transformacao=transformacao)


FEATURES_PADRAO = FeatureSpec(
    feature_set_id="sia_pa_pre_processamento_v1",
    atributos=(
        _atributo("cnes"),
        _atributo("municipio_estabelecimento"),
        _atributo("procedimento"),
        _atributo("instrumento"),
        _atributo("cbo"),
        _atributo("cid_principal"),
        _atributo("carater_atendimento"),
        _atributo("sexo"),
        _atributo("idade", NUMERICA),
        _atributo("quantidade_apresentada", NUMERICA),
    ),
)


@dataclass(frozen=True)
class OrigemAtributo:
    """Rastro de um atributo até a coluna canônica e o campo de origem descrito no esquema."""

    nome: str
    schema_id: str
    coluna: str
    papel: str
    transformacao: str
    origem: str


def auditar_features(
    features: FeatureSpec, esquemas: Iterable[EsquemaCanonico]
) -> tuple[OrigemAtributo, ...]:
    """Exige atributos ATRIBUTO, sem derivado de rótulo, erro ou valor do processamento.

    Raises:
        ValueError: atributo proibido, de papel desconhecido ou com transformação não prevista.
    """
    esquemas = tuple(esquemas)
    for atributo in features.atributos:
        _exigir_permitido(atributo)
    validar_features(features, esquemas)
    por_id = {esquema.schema_id: esquema for esquema in esquemas}
    origens = []
    for atributo in features.atributos:
        coluna = next(c for c in por_id[atributo.schema_id].colunas if c.nome == atributo.coluna)
        origens.append(
            OrigemAtributo(
                nome=atributo.nome,
                schema_id=atributo.schema_id,
                coluna=coluna.nome,
                papel=coluna.papel.value,
                transformacao=atributo.transformacao,
                origem=coluna.descricao,
            )
        )
    logger.info("features_auditadas feature_set=%s n=%d", features.feature_set_id, len(origens))
    return tuple(origens)


def _exigir_permitido(atributo: Atributo) -> None:
    coluna = atributo.coluna.lower()
    if any(
        coluna == proibida or coluna.startswith(f"{proibida}_")
        for proibida in COLUNAS_PROIBIDAS_EM_ATRIBUTOS
    ):
        raise ValueError(
            f"feature_derivada_de_campo_proibido atributo={atributo.nome} coluna={atributo.coluna}"
        )
    if coluna in COLUNAS_DE_PARTICAO:
        raise ValueError(
            f"feature_coluna_de_particao atributo={atributo.nome} coluna={atributo.coluna}"
        )
    if atributo.transformacao not in TRANSFORMACOES:
        raise ValueError(
            f"feature_transformacao_invalida atributo={atributo.nome} "
            f"transformacao={atributo.transformacao}"
        )
