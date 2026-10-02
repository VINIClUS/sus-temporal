"""Leitura de YAML com escalares sempre textuais (sem int, float, bool ou data implícitos)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

_TAGS_PRESERVADAS = {"tag:yaml.org,2002:null", "tag:yaml.org,2002:merge"}


class _CarregadorTexto(yaml.SafeLoader):
    pass


_CarregadorTexto.yaml_implicit_resolvers = {
    inicial: [(tag, padrao) for tag, padrao in resolvedores if tag in _TAGS_PRESERVADAS]
    for inicial, resolvedores in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def carregar_texto_yaml(texto: str) -> Any:
    carregador = _CarregadorTexto(texto)
    try:
        return carregador.get_single_data()
    finally:
        carregador.dispose()


def carregar_yaml(caminho: Path) -> Any:
    return carregar_texto_yaml(caminho.read_text(encoding="utf-8"))
