"""Leitura de YAML com escalares sempre textuais (sem int, float, bool ou data implícitos)."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, NoReturn

import yaml
from yaml.constructor import BaseConstructor

if TYPE_CHECKING:
    from collections.abc import Hashable
    from pathlib import Path

_TAG_YAML = "tag:yaml.org,2002:"
_TAGS_IMPLICITAS = {f"{_TAG_YAML}null"}
_TAGS_CONSTRUIDAS = {f"{_TAG_YAML}{nome}" for nome in ("str", "seq", "map", "null")}


class YamlInvalido(ValueError):
    """YAML ilegível ou com recurso recusado (tag, âncora, alias ou chave repetida)."""


class _CarregadorTexto(yaml.SafeLoader):
    def compose_node(self, parent: yaml.Node | None, index: int) -> yaml.Node | None:
        if self.check_event(yaml.NodeEvent) and self.current_event.anchor is not None:
            raise YamlInvalido(f"yaml_alias_nao_permitido ancora={self.current_event.anchor}")
        return super().compose_node(parent, index)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        mapa = BaseConstructor.construct_mapping(self, node, deep=deep)
        if len(mapa) != len(node.value):
            chaves = Counter(self.construct_object(chave, deep=deep) for chave, _ in node.value)
            repetidas = sorted(repr(chave) for chave, total in chaves.items() if total > 1)
            raise YamlInvalido(f"yaml_chave_duplicada chaves={','.join(repetidas)}")
        return mapa


def _recusar_tag(_carregador: _CarregadorTexto, no: yaml.Node) -> NoReturn:
    raise YamlInvalido(f"yaml_tag_nao_permitida tag={no.tag}")


_CarregadorTexto.yaml_implicit_resolvers = {
    inicial: [(tag, padrao) for tag, padrao in resolvedores if tag in _TAGS_IMPLICITAS]
    for inicial, resolvedores in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_CarregadorTexto.yaml_constructors = {
    **{
        tag: construtor
        for tag, construtor in yaml.SafeLoader.yaml_constructors.items()
        if tag in _TAGS_CONSTRUIDAS
    },
    None: _recusar_tag,
}


def carregar_texto_yaml(texto: str) -> Any:
    """Lê YAML com escalares textuais; só constrói texto, sequência, mapa e nulo.

    Raises:
        YamlInvalido: texto ilegível, tag não textual, âncora, alias ou chave repetida.
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
