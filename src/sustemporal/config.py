"""Carregamento de configurações de execução com herança por `base:`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sustemporal.contracts.config import RunConfig
from sustemporal.errors import ConfigInvalida
from sustemporal.yamlio import carregar_yaml

_MAX_NIVEIS_BASE = 5


def _mesclar(base: dict[str, Any], sobreposicao: dict[str, Any]) -> dict[str, Any]:
    resultado = dict(base)
    for chave, valor in sobreposicao.items():
        anterior = resultado.get(chave)
        if isinstance(anterior, dict) and isinstance(valor, dict):
            resultado[chave] = _mesclar(anterior, valor)
        else:
            resultado[chave] = valor
    return resultado


def _ler_mapa(caminho: Path) -> dict[str, Any]:
    try:
        conteudo = carregar_yaml(caminho)
    except (OSError, ValueError) as erro:
        raise ConfigInvalida(f"config_ilegivel caminho={caminho} erro={erro}") from erro
    if not isinstance(conteudo, dict):
        raise ConfigInvalida(f"config_nao_e_mapa caminho={caminho}")
    return conteudo


def _resolver(caminho: Path, nivel: int) -> dict[str, Any]:
    if nivel > _MAX_NIVEIS_BASE:
        raise ConfigInvalida(f"config_base_profunda_demais caminho={caminho}")
    conteudo = _ler_mapa(caminho)
    base = conteudo.pop("base", None)
    if base is None:
        return conteudo
    if not isinstance(base, str):
        raise ConfigInvalida(f"config_base_invalida caminho={caminho}")
    return _mesclar(_resolver(caminho.parent / base, nivel + 1), conteudo)


def load_config(path: Path) -> RunConfig:
    """Lê e valida uma configuração antes de qualquer processamento.

    Raises:
        ConfigInvalida: arquivo ausente, ilegível ou inválido segundo `RunConfig`.
    """
    try:
        return RunConfig.model_validate(_resolver(Path(path), 0))
    except ValidationError as erro:
        raise ConfigInvalida(f"config_invalida caminho={path} erro={erro}") from erro
