"""Amostra estratificada para avaliação humana cega (T12)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sustemporal.contracts import (
        AnnotationSample,
        DatasetRef,
        Particao,
        RunConfig,
        SplitManifest,
    )

__all__ = [
    "COLUNAS_PACOTE",
    "DIMENSOES_OBSERVAVEIS",
    "FORMULARIO_VERSAO",
    "carregar_mapa",
    "prepare_annotation_sample",
]

FORMULARIO_VERSAO = "anotacao_formulario.v1"
DIMENSOES_OBSERVAVEIS = ("instrumento", "periodo", "estabelecimento", "defasagem")
COLUNAS_PACOTE = (
    "cnes",
    "municipio_estabelecimento",
    "tipo_unidade",
    "pa_gestao",
    "pa_condic",
    "pa_regct",
    "pa_incout",
    "pa_incurg",
    "pa_srv_c",
    "competencia_processamento",
    "competencia_atendimento",
    "procedimento",
    "instrumento",
    "cbo",
    "pa_tpfin",
    "pa_subfin",
    "pa_nivcpl",
    "cid_principal",
    "cid_secundario",
    "cid_causas_associadas",
    "carater_atendimento",
    "idade",
    "idade_unidade",
    "sexo",
    "quantidade_apresentada",
    "quantidade_aprovada",
    "valor_apresentado",
    "valor_aprovado",
    "pa_codoco",
    "pa_flqt",
    "pa_fler",
    "pa_flidade",
)


def prepare_annotation_sample(
    labels: DatasetRef,
    split: SplitManifest,
    config: RunConfig,
    out: Path,
    *,
    particoes: Mapping[Particao, DatasetRef] | None = None,
    tamanho: int = 400,
    tamanho_treino: int = 20,
    dimensoes: tuple[str, ...] = DIMENSOES_OBSERVAVEIS,
) -> AnnotationSample:
    """Sorteia a amostra estratificada e prepara pacotes sem saídas do motor."""
    raise NotImplementedError


def carregar_mapa(out: Path) -> dict[str, str]:
    """Mapa privado caso_id → row_id gravado fora do pacote cego."""
    raise NotImplementedError
