"""Casos manuais SINTETICOS da família VIGENCIA_PROCEDIMENTO (model.md §4.4)."""

from pathlib import Path

from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import artefato_sigtap_vazio, cenario_base, registro, selecao

REGRA = "VIGENCIA_PROCEDIMENTO_SIGTAP"
LINHA = registro()["row_id"]


def _avaliacao(tmp_path: Path, cenario: CenarioRegras) -> dict[str, object]:
    resultado = executar(tmp_path, cenario)
    return avaliacoes_por_chave(resultado)[(LINHA, REGRA)]


def test_regra_vigencia_procedimento_esta_no_catalogo_como_candidata() -> None:
    regras = {regra.rule_id: regra for regra in carregar_regras()}
    assert REGRA in regras
    assert regras[REGRA].estado.value == "CANDIDATA_PRE_G0"


def test_procedimento_presente_na_versao_selecionada_e_conforme(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base())["estado"] == "CONFORME"


def test_procedimento_ausente_da_versao_selecionada_e_violacao(tmp_path: Path) -> None:
    assert _avaliacao(tmp_path, cenario_base(registro(procedimento="0202020202")))["estado"] == (
        "VIOLACAO"
    )


def test_versao_selecionada_sem_linhas_nunca_vira_ausencia(tmp_path: Path) -> None:
    vazio = artefato_sigtap_vazio()
    cenario = cenario_base()
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), artefatos=vazio)
        if s["rule_id"] == REGRA
        else s
        for s in cenario.selecoes
    )
    artefatos = {
        "sigtap_procedimento.v1": (
            cenario.auxiliares["sigtap_procedimento.v1"][0]["artifact_id"],
            vazio,
        )
    }
    avaliacao = _avaliacao(tmp_path, cenario.com(selecoes=selecoes, artefatos_auxiliar=artefatos))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")
