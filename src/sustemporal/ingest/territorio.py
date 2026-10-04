"""Carga e checagem do território do piloto (catálogo SECUNDARIA, A_CONFIRMAR).

O dígito verificador do IBGE7 (pesos 1, 2, 1, 2, 1, 2 sobre o IBGE6, soma dos dígitos dos
produtos) só pega erro de digitação; não confirma a composição do território.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts import Territorio
from sustemporal.errors import ConfigInvalida
from sustemporal.yamlio import YamlInvalido, carregar_yaml

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["carregar_territorio", "municipios_ibge6"]

logger = logging.getLogger(__name__)


def _digito_verificador(ibge6: str) -> str:
    soma = 0
    for posicao, caractere in enumerate(ibge6):
        produto = (ord(caractere) - ord("0")) * (1 + posicao % 2)
        soma += produto // 10 + produto % 10
    return chr(ord("0") + (10 - soma % 10) % 10)


def carregar_territorio(caminho: Path, *, uf: str) -> Territorio:
    """Território validado: contrato, UF do piloto e dígito verificador do IBGE7.

    Raises:
        ConfigInvalida: arquivo ilegível, contrato inválido, UF divergente ou dígito inválido.
    """
    try:
        territorio = Territorio.model_validate(carregar_yaml(caminho))
    except (OSError, YamlInvalido, ValidationError) as erro:
        raise ConfigInvalida(f"territorio_invalido caminho={caminho}") from erro
    if territorio.uf != uf:
        raise ConfigInvalida(f"territorio_uf_divergente territorio={territorio.uf} piloto={uf}")
    invalidos = [
        m.ibge7 for m in territorio.municipios if _digito_verificador(m.ibge6) != m.ibge7[6]
    ]
    if invalidos:
        raise ConfigInvalida(f"territorio_digito_verificador ibge7={','.join(invalidos)}")
    logger.info(
        "territorio_carregado id=%s municipios=%s",
        territorio.territorio_id,
        len(territorio.municipios),
    )
    return territorio


def municipios_ibge6(territorio: Territorio) -> frozenset[str]:
    """Códigos IBGE de 6 dígitos dos municípios (os do DATASUS)."""
    return frozenset(municipio.ibge6 for municipio in territorio.municipios)
