"""Lista positiva de atributos do classificador histórico, com auditoria de origem (T10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import Atributo, FeatureSpec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sustemporal.contracts.records import EsquemaCanonico

__all__ = [
    "CATEGORICA",
    "FEATURES_PADRAO",
    "NUMERICA",
    "TRANSFORMACOES",
    "OrigemAtributo",
    "auditar_features",
]

CATEGORICA = "CATEGORICA"
NUMERICA = "NUMERICA"
TRANSFORMACOES = frozenset({CATEGORICA, NUMERICA})


def _atributo(coluna: str, transformacao: str = CATEGORICA) -> Atributo:
    return Atributo(
        nome=coluna, schema_id="sia_pa.v1", coluna=coluna, transformacao=transformacao
    )


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
    raise NotImplementedError
