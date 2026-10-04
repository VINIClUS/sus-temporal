"""Casos manuais SINTETICOS da família INSTRUMENTO_REGISTRO (model.md §4.3)."""

from pathlib import Path

from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import cenario_base, registro

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
