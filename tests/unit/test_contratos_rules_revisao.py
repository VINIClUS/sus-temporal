"""Regras: decisão G0 rastreável, avaliações sustentadas por insumos e agregados sem repetição."""

import pytest
from pydantic import ValidationError

from sustemporal.contracts.rules import (
    AgregadoRegistro,
    Aplicabilidade,
    EstadoAvaliacao,
    EstadoRegra,
    FamiliaCandidata,
    FamiliaRegra,
)
from sustemporal.contracts.temporal import EstadoSelecao
from tests.unit.test_contratos_rules import _ROW, _avaliacao, _familia, _regra, _selecao

_DECISAO_G0 = "experiments/decisions/G0.yaml"
_REFERENCIAS_INVALIDAS = ["", "   ", "G0.yaml", "experiments/decisions/../G0.yaml"]
_DECIDIDAS = [EstadoRegra.APROVADA_G0, EstadoRegra.CONGELADA]
_CONFORME = {"incompatibilidade_demonstrada": False}


@pytest.mark.parametrize("referencia", _REFERENCIAS_INVALIDAS)
def test_regra_aprovada_rejeita_decisao_g0_fora_de_experiments_decisions(referencia: str) -> None:
    assert _regra(estado=EstadoRegra.APROVADA_G0, decisao_g0=_DECISAO_G0).decisao_g0 == _DECISAO_G0
    with pytest.raises(ValidationError):
        _regra(estado=EstadoRegra.APROVADA_G0, decisao_g0=referencia)


@pytest.mark.parametrize("estado", _DECIDIDAS)
def test_familia_decidida_exige_decisao_g0(estado: EstadoRegra) -> None:
    assert "decisao_g0" in FamiliaCandidata.model_fields
    aprovada = _familia(FamiliaRegra.PROCEDIMENTO_CBO, estado=estado, decisao_g0=_DECISAO_G0)
    assert aprovada.decisao_g0 == _DECISAO_G0
    with pytest.raises(ValidationError, match="familia_sem_decisao_g0"):
        _familia(FamiliaRegra.PROCEDIMENTO_CBO, estado=estado)


@pytest.mark.parametrize("referencia", _REFERENCIAS_INVALIDAS)
def test_familia_rejeita_decisao_g0_fora_de_experiments_decisions(referencia: str) -> None:
    assert "decisao_g0" in FamiliaCandidata.model_fields
    with pytest.raises(ValidationError):
        _familia(FamiliaRegra.CID, estado=EstadoRegra.APROVADA_G0, decisao_g0=referencia)


def test_familia_candidata_pre_g0_dispensa_decisao() -> None:
    assert "decisao_g0" in FamiliaCandidata.model_fields
    assert _familia(FamiliaRegra.CID).decisao_g0 is None


@pytest.mark.parametrize(
    "estados",
    [(), (EstadoSelecao.AMBIGUA,), (EstadoSelecao.SELECIONADA, EstadoSelecao.INCOMPLETA)],
)
def test_conforme_exige_selecoes_todas_selecionadas(estados: tuple[EstadoSelecao, ...]) -> None:
    assert _avaliacao(EstadoAvaliacao.CONFORME, **_CONFORME).estado is EstadoAvaliacao.CONFORME
    selecoes = tuple(_selecao(estado) for estado in estados)
    with pytest.raises(ValidationError, match="conforme_sem_insumos"):
        _avaliacao(EstadoAvaliacao.CONFORME, selecoes=selecoes, **_CONFORME)


@pytest.mark.parametrize("evidencias", [("",), (" ",), ("ev 1",), ("ev_1", "")])
def test_evidencias_da_avaliacao_sao_identificadores_nao_vazios(
    evidencias: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        _avaliacao(EstadoAvaliacao.VIOLACAO, evidence_ids=evidencias)


@pytest.mark.parametrize(
    "campos",
    [
        {"violacoes": ("REGRA_A",), "conformes": ("REGRA_A",), "resultado": "ALERTA"},
        {"violacoes": ("REGRA_A", "REGRA_A"), "resultado": "ALERTA"},
        {"inconclusivas": ("REGRA_B",), "nao_aplicaveis": ("REGRA_B",), "resultado": "ABSTENCAO"},
        {"conformes": ("REGRA_A", "REGRA_A"), "resultado": "SEM_VIOLACAO_VERIFICADA"},
        {
            "conformes": ("REGRA_A",),
            "nao_aplicaveis": ("REGRA_A",),
            "resultado": "SEM_VIOLACAO_VERIFICADA",
        },
    ],
)
def test_agregado_rejeita_regra_repetida_ou_em_dois_grupos(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="agregado_regra_repetida"):
        AgregadoRegistro.model_validate({"run_id": "run_1", "row_id": _ROW} | campos)


def test_nao_aplicavel_exige_evidencia_da_nao_aplicabilidade() -> None:
    demonstrada = {"aplicabilidade": Aplicabilidade.NAO_APLICAVEL_DEMONSTRADA}
    assert _avaliacao(EstadoAvaliacao.NAO_APLICAVEL, **demonstrada).evidence_ids == ("ev_ausencia",)
    with pytest.raises(ValidationError, match="nao_aplicavel_sem_evidencia"):
        _avaliacao(EstadoAvaliacao.NAO_APLICAVEL, evidence_ids=(), **demonstrada)


def test_regra_exige_campos_necessarios() -> None:
    assert _regra().campos_necessarios == ("cnes", "cbo")
    with pytest.raises(ValidationError, match="regra_sem_campos_necessarios"):
        _regra(campos_necessarios=())
