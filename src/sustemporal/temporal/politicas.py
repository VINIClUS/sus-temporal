"""Políticas temporais do catálogo (`catalog/policies/<politica_id>.yaml`)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from sustemporal.contracts.temporal import PoliticaTemporal
from sustemporal.errors import ConfigInvalida
from sustemporal.yamlio import carregar_yaml

__all__ = ["DIRETORIO_POLITICAS", "carregar_politica"]

DIRETORIO_POLITICAS = Path(__file__).resolve().parents[3] / "catalog" / "policies"
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


def carregar_politica(politica_id: str, diretorio: Path = DIRETORIO_POLITICAS) -> PoliticaTemporal:
    """Lê `<diretorio>/<politica_id>.yaml` com escalares só texto.

    Raises:
        ConfigInvalida: id fora do padrão, arquivo ilegível, modelo inválido ou id divergente.
    """
    if not _ID.fullmatch(politica_id):
        raise ConfigInvalida(f"politica_id_invalido politica={politica_id!r}")
    caminho = diretorio / f"{politica_id}.yaml"
    try:
        politica = PoliticaTemporal.model_validate(carregar_yaml(caminho))
    except (OSError, ValueError, ValidationError) as erro:
        raise ConfigInvalida(f"politica_invalida caminho={caminho} erro={erro}") from erro
    if politica.politica_id != politica_id:
        raise ConfigInvalida(f"politica_id_divergente arquivo={caminho} id={politica.politica_id}")
    return politica
