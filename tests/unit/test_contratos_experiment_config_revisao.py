"""Protocolo: decisões de portão rastreáveis e manifestos de partição completos."""

import pytest
from pydantic import ValidationError

from sustemporal.contracts.experiment import (
    A_DEFINIR,
    FreezeManifest,
    Particao,
    Portao,
    SplitManifest,
)
from sustemporal.contracts.rules import FamiliaRegra
from tests.unit.test_contratos_experiment_config import _campos_freeze, _decisao, _split

_HASH = f"lh1:{'c' * 64}"
_LINHAS = dict.fromkeys(Particao, 1)
_HASHES = dict.fromkeys(Particao, _HASH)


def _manifesto(**campos: object) -> SplitManifest:
    base = {
        "split_id": "split_1",
        "spec": _split(),
        "dataset_hash": _HASH,
        "linhas_por_particao": _LINHAS,
        "hash_por_particao": _HASHES,
    }
    return SplitManifest.model_validate(base | campos)


@pytest.mark.parametrize(
    "referencia", ["", "   ", "G0.yaml", "experiments/decisions/G0.txt", A_DEFINIR]
)
def test_congelamento_exige_decisao_g0_em_experiments_decisions(referencia: str) -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        FreezeManifest.criar(**_campos_freeze(decisao_g0=referencia))


def test_decisao_com_data_numerica_e_recusada() -> None:
    assert _decisao(Portao.G0, "CONTINUAR").data.isoformat() == "2026-11-30"
    with pytest.raises(ValidationError, match="data_exige_date_ou_iso"):
        _decisao(Portao.G0, "CONTINUAR", data=0)


def test_restringir_familias_exige_familias_aprovadas() -> None:
    aprovada = _decisao(Portao.G0, "RESTRINGIR_FAMILIAS", familias_aprovadas=("PROCEDIMENTO_CBO",))
    assert aprovada.familias_aprovadas[0] is FamiliaRegra.PROCEDIMENTO_CBO
    with pytest.raises(ValidationError, match="decisao_restringir_familias_sem_familias"):
        _decisao(Portao.G0, "RESTRINGIR_FAMILIAS")


@pytest.mark.parametrize("familias", [("FAMILIA_INVENTADA",), ("procedimento_cbo",), ("",)])
def test_familias_aprovadas_so_aceitam_familias_de_regra(familias: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G0, "RESTRINGIR_FAMILIAS", familias_aprovadas=familias)


@pytest.mark.parametrize("responsaveis", [(" ",), ("pesquisador", "\t"), ("\n",)])
def test_decisao_rejeita_responsavel_em_branco(responsaveis: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G1, "APROVADO", responsaveis=responsaveis)


@pytest.mark.parametrize("ausente", list(Particao))
@pytest.mark.parametrize("campo", ["linhas_por_particao", "hash_por_particao"])
def test_manifesto_exige_contagem_e_hash_de_cada_particao_declarada(
    ausente: Particao, campo: str
) -> None:
    assert _manifesto().linhas_por_particao == _LINHAS
    completo = _LINHAS if campo == "linhas_por_particao" else _HASHES
    incompleto = {
        particao: valor for particao, valor in completo.items() if particao is not ausente
    }
    with pytest.raises(ValidationError, match="split_manifesto_particoes_divergentes"):
        _manifesto(**{campo: incompleto})
