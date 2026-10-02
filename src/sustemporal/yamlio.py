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


class YamlInvalido(ValueError):
    """Texto que não é YAML legível (sintaxe ou caractere não imprimível)."""


def carregar_texto_yaml(texto: str) -> Any:
    """Lê YAML com escalares textuais.

    Raises:
        YamlInvalido: texto ilegível como YAML.
    """
    try:
        carregador = _CarregadorTexto(texto)
    except yaml.YAMLError as erro:
        raise YamlInvalido(f"yaml_invalido erro={erro}") from erro
    try:
        return carregador.get_single_data()
    except yaml.YAMLError as erro:
        raise YamlInvalido(f"yaml_invalido erro={erro}") from erro
    finally:
        carregador.dispose()


def carregar_yaml(caminho: Path) -> Any:
    return carregar_texto_yaml(caminho.read_text(encoding="utf-8"))
