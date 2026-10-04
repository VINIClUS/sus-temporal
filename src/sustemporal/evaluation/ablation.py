"""Ablações de versão de regra e de fonte (T08): sensibilidade, não causalidade."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sustemporal.contracts.base import FamiliaFonte
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.records import DatasetRef

INTERPRETACAO_ABLACAO = ""


class TipoAblacao(StrEnum):
    VERSAO_REGRA = "VERSAO_REGRA"
    VERSAO_CNES = "VERSAO_CNES"
    VERSAO_SIGTAP = "VERSAO_SIGTAP"


class AblacaoNaoIsolada(ValueError):
    """As duas execuções diferem em mais do que o fator da ablação."""


def trocar_versao_fonte(
    selecoes: DatasetRef, fonte: FamiliaFonte, troca: Mapping[str, str], destino: Path
) -> DatasetRef:
    raise NotImplementedError


def comparar_ablacao(base: RunResult, variante: RunResult, tipo: TipoAblacao) -> object:
    raise NotImplementedError
