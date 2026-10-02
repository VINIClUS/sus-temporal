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


def _recusar_nulos(conteudo: dict[str, Any], caminho: Path, prefixo: str = "") -> None:
    for chave, valor in conteudo.items():
        nome = f"{prefixo}{chave}"
        if valor is None:
            raise ConfigInvalida(f"config_null_nao_permitido chave={nome} caminho={caminho}")
        if isinstance(valor, dict):
            _recusar_nulos(valor, caminho, f"{nome}.")


def _caminho_da_base(caminho: Path, base: str, raiz: Path) -> Path:
    destino = (caminho.parent / base).resolve()
    if Path(base).is_absolute() or not destino.is_relative_to(raiz):
        raise ConfigInvalida(f"config_base_fora_do_diretorio caminho={caminho} base={base}")
    return destino


def _resolver(caminho: Path, nivel: int, raiz: Path) -> dict[str, Any]:
    if nivel > _MAX_NIVEIS_BASE:
        raise ConfigInvalida(f"config_base_profunda_demais caminho={caminho}")
    conteudo = _ler_mapa(caminho)
    base = conteudo.pop("base", None)
    if base is None:
        return conteudo
    if not isinstance(base, str):
        raise ConfigInvalida(f"config_base_invalida caminho={caminho}")
    _recusar_nulos(conteudo, caminho)
    anterior = _resolver(_caminho_da_base(caminho, base, raiz), nivel + 1, raiz)
    return _mesclar(anterior, conteudo)


def load_config(path: Path) -> RunConfig:
    """Lê e valida uma configuração antes de qualquer processamento.

    `base:` é relativa e não sai do diretório da config raiz; a filha não usa null.

    Raises:
        ConfigInvalida: arquivo ausente, ilegível, herança recusada ou inválido segundo
            `RunConfig`.
    """
    caminho = Path(path)
    try:
        return RunConfig.model_validate(_resolver(caminho, 0, caminho.parent.resolve()))
    except ValidationError as erro:
        raise ConfigInvalida(f"config_invalida caminho={path} erro={erro}") from erro
