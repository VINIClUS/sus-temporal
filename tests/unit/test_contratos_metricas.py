from decimal import Decimal

import pytest
from pydantic import ValidationError

from sustemporal.contracts.evaluation import ValorMetrica
from sustemporal.contracts.experiment import BootstrapSpec


def _metrica(**campos: object) -> ValorMetrica:
    base = {"nome": "cobertura_rejeicoes", "numerador": 1, "denominador": 4, "valor": "0.25"}
    return ValorMetrica.model_validate(base | campos)


@pytest.mark.parametrize(
    ("numerador", "denominador", "valor"),
    [(1, 4, "0.5"), (1, 3, "0.3334"), (2, 3, "0.66"), (0, 5, "0.1")],
)
def test_razao_que_contradiz_a_contagem_e_rejeitada(
    numerador: int, denominador: int, valor: str
) -> None:
    with pytest.raises(ValidationError, match="metrica_valor_diverge_da_razao"):
        _metrica(numerador=numerador, denominador=denominador, valor=valor)


@pytest.mark.parametrize(
    ("numerador", "denominador", "valor"),
    [(1, 4, "0.25"), (1, 4, "0.250"), (1, 3, "0.3333"), (2, 3, "0.67"), (5, 5, "1"), (3, 2, "1.5")],
)
def test_razao_arredondada_na_escala_do_valor_e_aceita(
    numerador: int, denominador: int, valor: str
) -> None:
    metrica = _metrica(numerador=numerador, denominador=denominador, valor=valor)
    assert metrica.valor == Decimal(valor)


def test_estatistica_declarada_nao_e_conferida_como_razao() -> None:
    assert "tipo" in ValorMetrica.model_fields
    metrica = _metrica(numerador=40, denominador=50, valor="0.61", tipo="ESTATISTICA")
    assert metrica.valor == Decimal("0.61")


def test_tipo_padrao_da_metrica_e_razao() -> None:
    assert "tipo" in ValorMetrica.model_fields
    assert _metrica().tipo == "RAZAO"


@pytest.mark.parametrize(
    "campos",
    [
        {"reamostragens": 0},
        {"reamostragens": -5},
        {"confianca": "0"},
        {"confianca": "1"},
        {"confianca": "2"},
        {"confianca": "-0.5"},
    ],
)
def test_bootstrap_sem_intervalo_definido_e_rejeitado(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="bootstrap_invalido"):
        BootstrapSpec.model_validate(campos)
