"""`VigilanciaSpec`: cadência e duração aditivas, opcionais e positivas."""

import pytest
from pydantic import ValidationError

from sustemporal.contracts.config import RunConfig, VigilanciaSpec

_HASHES_EMITIDOS = {
    "padrao": ({}, "bedf70034f809b895ec46d7b19674a0ca9b9998963f07d00e096088a699de1d3"),
    "preenchida": (
        {"familias_fontes": ["SIA_PA"], "janela_competencias": 12},
        "ec5c0b88ef89d0e3b1fd4666d9dd218fc7570978386db3b8558ad3640242c1dd",
    ),
}


def _config(**vigilancia: object) -> RunConfig:
    return RunConfig.model_validate({"versao": "1", "vigilancia": vigilancia})


def test_vigilancia_declara_cadencia_e_duracao_opcionais() -> None:
    campos = VigilanciaSpec.model_fields
    assert {"cadencia_dias", "duracao_meses"} <= set(campos)
    assert (campos["cadencia_dias"].default, campos["duracao_meses"].default) == (None, None)


def test_vigilancia_aceita_cadencia_e_duracao_positivas() -> None:
    assert {"cadencia_dias", "duracao_meses"} <= set(VigilanciaSpec.model_fields)
    vigilancia = _config(cadencia_dias=7, duracao_meses="12").vigilancia
    assert vigilancia is not None
    assert (vigilancia.cadencia_dias, vigilancia.duracao_meses) == (7, 12)


@pytest.mark.parametrize(
    ("campo", "valor", "mensagem"),
    [
        ("cadencia_dias", 0, "vigilancia_cadencia_deve_ser_positiva"),
        ("cadencia_dias", -7, "vigilancia_cadencia_deve_ser_positiva"),
        ("duracao_meses", 0, "vigilancia_duracao_deve_ser_positiva"),
        ("duracao_meses", "-1", "vigilancia_duracao_deve_ser_positiva"),
    ],
)
def test_vigilancia_recusa_cadencia_ou_duracao_menor_que_um(
    campo: str, valor: object, mensagem: str
) -> None:
    with pytest.raises(ValidationError, match=mensagem):
        _config(**{campo: valor})


@pytest.mark.parametrize("valor", [7.0, True, "sete"])
@pytest.mark.parametrize("campo", ["cadencia_dias", "duracao_meses"])
def test_vigilancia_recusa_cadencia_ou_duracao_nao_inteira(campo: str, valor: object) -> None:
    with pytest.raises(ValidationError, match="inteiro_invalido"):
        _config(**{campo: valor})


@pytest.mark.parametrize("caso", sorted(_HASHES_EMITIDOS))
def test_campos_novos_ausentes_mantem_o_config_hash_emitido(caso: str) -> None:
    vigilancia, esperado = _HASHES_EMITIDOS[caso]
    assert _config(**vigilancia).config_hash == esperado


def test_campos_novos_nulos_mantem_o_config_hash_emitido() -> None:
    esperado = _HASHES_EMITIDOS["padrao"][1]
    assert {"cadencia_dias", "duracao_meses"} <= set(VigilanciaSpec.model_fields)
    assert _config(cadencia_dias=None, duracao_meses=None).config_hash == esperado


def test_cadencia_definida_muda_o_config_hash() -> None:
    vigilancia, esperado = _HASHES_EMITIDOS["padrao"]
    assert {"cadencia_dias"} <= set(VigilanciaSpec.model_fields)
    assert _config(**vigilancia, cadencia_dias=7).config_hash != esperado
