"""Comando `sustemporal annotation-export --freeze FREEZE_ID` (T12).

O freeze_id resolve um manifesto congelado exato; rótulos e partições saem dos `DatasetRef` do
manifesto pelo hash lógico declarado no split, nunca de um diretório "latest".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.evaluation.annotation import (
    SCHEMA_REGISTROS,
    SCHEMA_ROTULOS,
    prepare_annotation_sample,
)
from sustemporal.evaluation.freeze import carregar_freeze

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import DatasetRef, FreezeManifest, Particao, RunConfig

__all__ = ["carregar_congelamento", "executar_annotation_export"]

logger = logging.getLogger(__name__)


def carregar_congelamento(diretorio: Path, freeze_id: str) -> FreezeManifest:
    """Manifesto `<diretorio>/<freeze_id>.json` cujo id confere com o conteúdo.

    Raises:
        ConfigInvalida: o de `carregar_freeze` (ausente, ilegível, adulterado ou de outro id).
    """
    return carregar_freeze(diretorio, freeze_id)


def _rotulos(manifesto: FreezeManifest) -> DatasetRef:
    candidatos = [d for d in manifesto.datasets if d.schema_id == SCHEMA_ROTULOS]
    if len(candidatos) != 1:
        raise ConfigInvalida(
            f"congelamento_sem_rotulos_unicos freeze={manifesto.freeze_id} "
            f"encontrados={len(candidatos)}"
        )
    return candidatos[0]


def _particoes(manifesto: FreezeManifest) -> dict[Particao, DatasetRef]:
    split = manifesto.split
    resolvidas: dict[Particao, DatasetRef] = dict(getattr(split, "particoes", None) or {})
    for particao, hash_logico in split.hash_por_particao.items():
        for dataset in manifesto.datasets:
            if dataset.schema_id == SCHEMA_REGISTROS and dataset.hash_logico == hash_logico:
                resolvidas[particao] = dataset
    return resolvidas


def executar_annotation_export(args: argparse.Namespace, config: RunConfig) -> int:
    """Resolve o congelamento exato e exporta amostra, pacote cego e formulário.

    Raises:
        ConfigInvalida: freeze divergente da config ou manifesto ausente, inválido ou sem
            rótulos e partições resolvíveis.
    """
    freeze_id = str(args.freeze)
    if config.freeze_id is not None and config.freeze_id != freeze_id:
        raise ConfigInvalida(
            f"annotation_freeze_diverge_da_config freeze={freeze_id} config={config.freeze_id}"
        )
    manifesto = carregar_congelamento(Path(config.runtime.dir_congelamentos), freeze_id)
    destino = Path(config.runtime.raiz_saidas) / "anotacao" / manifesto.freeze_id
    amostra = prepare_annotation_sample(
        _rotulos(manifesto),
        manifesto.split,
        config.model_copy(update={"freeze_id": manifesto.freeze_id}),
        destino,
        particoes=_particoes(manifesto),
    )
    logger.info(
        "annotation_export freeze=%s amostra=%s destino=%s",
        manifesto.freeze_id,
        amostra.sample_id,
        destino,
    )
    return int(ExitCode.OK)
