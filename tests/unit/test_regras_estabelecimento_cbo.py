"""Casos manuais SINTETICOS da família ESTABELECIMENTO_CBO (model.md §4.2)."""

import json
from pathlib import Path

import pytest

from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import ART_CNES, ART_SIA, COMPETENCIA, cenario_base, registro
from tests.fixtures.regras_nao_aplicavel import CASOS_NAO_APLICAVEL, avaliar_caso

REGRA = "ESTAB_CBO_CNES"
LINHA = registro()["row_id"]
CNES = "cnes_estab_cbo.v1"


def _avaliacao(tmp_path: Path, cenario: CenarioRegras) -> dict[str, object]:
    resultado = executar(tmp_path, cenario)
    return avaliacoes_por_chave(resultado)[(LINHA, REGRA)]


def _vinculo(cbo: str, n_vinculos: int | None) -> dict[str, object]:
    return {
        "artifact_id": ART_CNES,
        "competencia_arquivo": COMPETENCIA,
        "cnes": "1234567",
        "cbo": cbo,
        "n_vinculos": n_vinculos,
    }


def test_regra_estabelecimento_cbo_e_cadastral_e_candidata() -> None:
    regras = {regra.rule_id: regra for regra in carregar_regras()}
    assert REGRA in regras
    assert regras[REGRA].unidade_avaliacao.value == "ESTABELECIMENTO_CBO"
    assert regras[REGRA].estado.value == "CANDIDATA_PRE_G0"


def test_par_estabelecimento_cbo_com_vinculo_e_conforme(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base())["estado"] == "CONFORME"


def test_par_ausente_com_estabelecimento_no_escopo_e_violacao(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base(registro(cbo="999999")))["estado"] == "VIOLACAO"


def test_par_com_zero_vinculos_conta_como_ausente(tmp_path: Path) -> None:
    cenario = cenario_base()
    cenario = cenario.com(auxiliares=cenario.auxiliares | {CNES: (_vinculo("225125", 0),)})
    assert _avaliacao(tmp_path, cenario)["estado"] == "VIOLACAO"


def test_estabelecimento_fora_do_escopo_e_cobertura_insuficiente(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(cnes="7654321")))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_contagem_de_vinculos_nula_e_campo_insuficiente(tmp_path: Path) -> None:
    cenario = cenario_base()
    cenario = cenario.com(auxiliares=cenario.auxiliares | {CNES: (_vinculo("225125", None),)})
    avaliacao = _avaliacao(tmp_path, cenario)
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "CAMPO_INSUFICIENTE")


def test_registros_do_mesmo_par_compartilham_resultado_e_evidencia(tmp_path: Path) -> None:
    resultado = executar(
        tmp_path, cenario_base(registro(0), registro(1, procedimento="0202020202"))
    )
    avaliacoes = avaliacoes_por_chave(resultado)
    primeira = avaliacoes[(registro(0)["row_id"], REGRA)]
    segunda = avaliacoes[(registro(1)["row_id"], REGRA)]
    assert primeira["estado"] == segunda["estado"] == "CONFORME"
    assert primeira["evidence_ids"] == segunda["evidence_ids"]


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
