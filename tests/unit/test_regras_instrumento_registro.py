"""Casos manuais SINTETICOS da família INSTRUMENTO_REGISTRO (model.md §4.3)."""

import json
from pathlib import Path

import pytest

from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import ART_SIA, cenario_base, registro
from tests.fixtures.regras_nao_aplicavel import CASOS_NAO_APLICAVEL, avaliar_caso

REGRA = "INSTRUMENTO_REGISTRO_SIGTAP"
LINHA = registro()["row_id"]


def _avaliacao(tmp_path: Path, cenario: CenarioRegras) -> dict[str, object]:
    resultado = executar(tmp_path, cenario)
    return avaliacoes_por_chave(resultado)[(LINHA, REGRA)]


def test_regra_instrumento_registro_esta_no_catalogo_como_candidata() -> None:
    regras = {regra.rule_id: regra for regra in carregar_regras()}
    assert REGRA in regras
    assert regras[REGRA].estado.value == "CANDIDATA_PRE_G0"


def test_instrumento_admitido_para_o_procedimento_e_conforme(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base())["estado"] == "CONFORME"


def test_instrumento_nao_admitido_e_violacao(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base(registro(instrumento="I")))["estado"] == "VIOLACAO"


def test_procedimento_sem_registro_listado_e_cobertura_insuficiente(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(procedimento="0202020202")))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


@pytest.mark.parametrize("caso", sorted(CASOS_NAO_APLICAVEL))
def test_fora_dos_instrumentos_ou_da_vigencia_e_nao_aplicavel_com_evidencia(
    tmp_path: Path, caso: str
) -> None:
    avaliacao, evidencia, sia = avaliar_caso(tmp_path, caso, REGRA)
    assert (avaliacao["estado"], avaliacao["aplicabilidade"], avaliacao["motivos"]) == (
        "NAO_APLICAVEL",
        "NAO_APLICAVEL_DEMONSTRADA",
        "",
    )
    assert (avaliacao["insumos_completos"], avaliacao["incompatibilidade_demonstrada"]) == (
        True,
        None,
    )
    esperado = CASOS_NAO_APLICAVEL[caso]
    assert (evidencia["tipo"], evidencia["query_id"]) == ("APLICABILIDADE", esperado.query_id)
    assert json.loads(evidencia["parametros"]) == esperado.parametros | {"rule_id": REGRA}
    assert (evidencia["dataset_id"], evidencia["artifact_ids"]) == (sia, ART_SIA)
