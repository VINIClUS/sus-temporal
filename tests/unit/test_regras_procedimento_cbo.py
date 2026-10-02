"""Casos manuais SINTETICOS da família PROCEDIMENTO_CBO (model.md §4.1)."""

from pathlib import Path

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, tabela
from tests.fixtures.regras_exemplos import ART_SIGTAP, cenario_base, cobertura_completa, registro

REGRA = "PROC_CBO_SIGTAP"
LINHA = registro()["row_id"]


def _avaliacao(tmp_path: Path, cenario: CenarioRegras) -> dict[str, object]:
    resultado = executar(tmp_path, cenario)
    return avaliacoes_por_chave(resultado)[(LINHA, REGRA)]


def test_regra_procedimento_cbo_esta_no_catalogo_como_candidata() -> None:
    regras = {regra.rule_id: regra for regra in carregar_regras()}
    assert REGRA in regras
    assert regras[REGRA].estado.value == "CANDIDATA_PRE_G0"
    assert regras[REGRA].referencia.estado.value == "PENDENTE"


def test_cbo_listado_para_o_procedimento_e_conforme(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base())
    assert (avaliacao["estado"], avaliacao["incompatibilidade_demonstrada"]) == ("CONFORME", False)


def test_cbo_nao_listado_com_cobertura_e_integridade_e_violacao(tmp_path: Path) -> None:
    resultado = executar(tmp_path, cenario_base(registro(cbo="999999")))
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, REGRA)]
    assert avaliacao["estado"] == "VIOLACAO"
    evidencia = next(
        e
        for e in tabela(resultado, "evidencias.v1")
        if e["evidence_id"] == avaliacao["evidence_ids"]
    )
    assert evidencia["tipo"] == "AUSENCIA_NA_FONTE"
    assert (evidencia["n_resultados"], evidencia["cobertura"]) == (0, "DISPONIVEL")
    assert evidencia["artifact_ids"] == ART_SIGTAP


@pytest.mark.parametrize("estado_cobertura", ["INSUFICIENTE", "AUSENTE"])
def test_not_exists_sem_cobertura_disponivel_e_inconclusivo(
    tmp_path: Path, estado_cobertura: str
) -> None:
    cenario = cenario_base(registro(cbo="999999")).com(
        cobertura=cobertura_completa(estado_cobertura)
    )
    avaliacao = _avaliacao(tmp_path, cenario)
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_not_exists_sem_matriz_de_cobertura_e_inconclusivo(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(cbo="999999")).com(cobertura=None))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


@pytest.mark.parametrize(
    ("integridade", "motivo"),
    [
        (EstadoIntegridade.QUARENTENA_TRUNCADO, "ARQUIVO_EM_QUARENTENA"),
        (EstadoIntegridade.NAO_VERIFICADO, "COBERTURA_INSUFICIENTE"),
        (None, "COBERTURA_INSUFICIENTE"),
    ],
)
def test_not_exists_sem_integridade_ok_e_inconclusivo(
    tmp_path: Path, integridade: EstadoIntegridade | None, motivo: str
) -> None:
    cenario = cenario_base(registro(cbo="999999"))
    estados = dict(cenario.integridade)
    estados.pop(ART_SIGTAP)
    if integridade is not None:
        estados[ART_SIGTAP] = integridade
    avaliacao = _avaliacao(tmp_path, cenario.com(integridade=estados))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", motivo)


def test_procedimento_sem_ocupacao_listada_tem_aplicabilidade_desconhecida(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(procedimento="0202020202")))
    assert avaliacao["estado"] == "INCONCLUSIVO"
    assert avaliacao["aplicabilidade"] == "DESCONHECIDA"
    assert avaliacao["motivos"] == "APLICABILIDADE_DESCONHECIDA"


def test_instrumento_fora_da_regra_e_nao_aplicavel_com_evidencia(tmp_path: Path) -> None:
    resultado = executar(tmp_path, cenario_base(registro(instrumento="Z")))
    avaliacao = avaliacoes_por_chave(resultado)[(LINHA, REGRA)]
    assert (avaliacao["estado"], avaliacao["aplicabilidade"]) == (
        "NAO_APLICAVEL",
        "NAO_APLICAVEL_DEMONSTRADA",
    )
    tipos = {e["evidence_id"]: e["tipo"] for e in tabela(resultado, "evidencias.v1")}
    assert tipos[avaliacao["evidence_ids"]] == "APLICABILIDADE"


def test_instrumento_nulo_deixa_aplicabilidade_desconhecida(tmp_path: Path) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(instrumento=None)))
    assert (avaliacao["estado"], avaliacao["aplicabilidade"]) == ("INCONCLUSIVO", "DESCONHECIDA")
    assert avaliacao["motivos"] == "APLICABILIDADE_DESCONHECIDA;CAMPO_INSUFICIENTE"
    assert avaliacao["insumos_completos"] is False


@pytest.mark.parametrize("campo", ["procedimento", "cbo"])
def test_campo_nulo_e_inconclusivo_e_nunca_violacao(tmp_path: Path, campo: str) -> None:
    avaliacao = _avaliacao(tmp_path, cenario_base(registro(**{campo: None})))
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "CAMPO_INSUFICIENTE")


def test_coluna_ausente_do_conjunto_e_campo_insuficiente(tmp_path: Path) -> None:
    cenario = cenario_base().com(colunas_ausentes_registro=frozenset({"cbo"}))
    avaliacao = _avaliacao(tmp_path, cenario)
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "CAMPO_INSUFICIENTE")
