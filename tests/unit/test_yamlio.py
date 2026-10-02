"""Leitura de YAML de catálogo e configuração: só texto, sem tags, âncoras nem chaves repetidas."""

import pytest

from sustemporal.yamlio import YamlInvalido, carregar_texto_yaml

_BOMBA_DE_ALIASES = "a: &a [x, x, x]\nb: &b [*a, *a, *a]\nc: &c [*b, *b, *b]\n"


@pytest.mark.parametrize(
    "texto",
    [
        "a: 1\na: 2\n",
        "raiz:\n  a: 1\n  b: 2\n  a: 3\n",
        "a: 1\n'a': 2\n",
        "~: 1\nnull: 2\n",
        "- {x: 1, x: 2}\n",
    ],
)
def test_chave_duplicada_no_mapeamento_e_recusada(texto: str) -> None:
    with pytest.raises(YamlInvalido, match="yaml_chave_duplicada"):
        carregar_texto_yaml(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "!!float 1.5",
        "!!bool true",
        "!!timestamp 2027-01-15",
        "!!binary aGVsbG8=",
        "!!set {a: null}",
        "!!omap [a: 1]",
        "!!pairs [a: 1]",
        "!!python/name:os.system",
        "!!python/object/apply:os.system [ls]",
        "!local x",
        "!!merge <<: {a: 1}\n",
    ],
)
def test_tag_explicita_que_nao_e_texto_sequencia_mapa_ou_nulo_e_recusada(texto: str) -> None:
    with pytest.raises(YamlInvalido, match="yaml_tag_nao_permitida"):
        carregar_texto_yaml(texto)


def test_tag_int_nao_converte_codigo_com_zero_a_esquerda() -> None:
    assert carregar_texto_yaml("!!str 0301010072") == "0301010072"
    with pytest.raises(YamlInvalido, match="yaml_tag_nao_permitida"):
        carregar_texto_yaml("!!int 0301010072")


def test_so_texto_sequencia_mapa_e_nulo_sao_construidos() -> None:
    texto = "a: !!str 1\nb: !!seq [2]\nc: !!map {d: 3}\ne: !!null ''\nf: ~\n"
    assert carregar_texto_yaml(texto) == {
        "a": "1",
        "b": ["2"],
        "c": {"d": "3"},
        "e": None,
        "f": None,
    }
    with pytest.raises(YamlInvalido, match="yaml_tag_nao_permitida"):
        carregar_texto_yaml("a: !!timestamp 2027-01-15\n")


@pytest.mark.parametrize(
    "texto",
    [
        "a: &x 1\nb: *x\n",
        "a: &x 1\n",
        "a: &x [1]\n",
        "&x {a: 1}\n",
        "base: &b {c: 1}\nfilho:\n  <<: *b\n",
        _BOMBA_DE_ALIASES,
    ],
)
def test_ancora_e_alias_sao_recusados(texto: str) -> None:
    with pytest.raises(YamlInvalido, match="yaml_alias_nao_permitido"):
        carregar_texto_yaml(texto)


def test_chave_de_mesclagem_deixa_de_ser_especial() -> None:
    assert carregar_texto_yaml("<<: {a: 1}\nb: 2\n") == {"<<": {"a": "1"}, "b": "2"}
