"""Bateria determinística de cenários SINTETICOS (exemplos manuais) para o diferencial."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import CenarioRegras, artefato, coerente, politica
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIA,
    ART_SIGTAP,
    COMPETENCIA,
    REGRAS,
    cenario_base,
    cobertura_completa,
    registro,
    selecao,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts.rules import RuleSpec

__all__ = ["BATERIA", "regras_da_bateria"]

_VAZIO = artefato(3)
_DESLOCAMENTO = -1


def _linhas(**comuns: str | None) -> tuple[dict[str, str | None], ...]:
    variacoes: list[dict[str, str | None]] = [
        {},
        {"cbo": "999999"},
        {"cnes": "7654321"},
        {"instrumento": "I"},
        {"instrumento": "Z"},
        {"instrumento": None},
        {"procedimento": "0202020202"},
        {"procedimento": None},
        {"cbo": None},
        {"competencia_atendimento": None},
        {"competencia_processamento": None},
    ]
    return tuple(registro(indice, **(comuns | campos)) for indice, campos in enumerate(variacoes))


def _base() -> CenarioRegras:
    return cenario_base(*_linhas())


def _integridade_ruim() -> CenarioRegras:
    cenario = _base()
    return cenario.com(
        integridade=cenario.integridade | {ART_SIGTAP: EstadoIntegridade.QUARENTENA_TRUNCADO}
    )


def _escopo_vazio() -> CenarioRegras:
    cenario = _base()
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), artefatos=_VAZIO) for s in cenario.selecoes
    )
    registrados = dict.fromkeys(cenario.auxiliares, (ART_SIGTAP, ART_CNES, _VAZIO))
    return cenario.com(selecoes=selecoes, artefatos_auxiliar=registrados)


def _versao_parcialmente_vazia() -> CenarioRegras:
    cenario = _base()
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), artefatos=f"{ART_SIGTAP};{_VAZIO}")
        if s["fonte"] == "SIGTAP"
        else s
        for s in cenario.selecoes
    )
    registrados = dict.fromkeys(cenario.auxiliares, (ART_SIGTAP, ART_CNES, _VAZIO))
    integridade = cenario.integridade | {_VAZIO: EstadoIntegridade.OK}
    return cenario.com(selecoes=selecoes, artefatos_auxiliar=registrados, integridade=integridade)


def _selecoes_variadas() -> CenarioRegras:
    cenario = _base()
    estados = ("AUSENTE", "INCOMPLETA", "EM_QUARENTENA", "FORA_DO_CORTE", "NAO_RESOLVIDA")
    selecoes = []
    for indice, original in enumerate(cenario.selecoes):
        estado = estados[indice % len(estados)] if indice % 3 == 0 else "SELECIONADA"
        vazia = estado in {"AUSENTE", "NAO_RESOLVIDA"}
        selecoes.append(
            selecao(
                str(original["row_id"]),
                str(original["rule_id"]),
                estado,
                artefatos="" if vazia else None,
                competencia=None if estado == "NAO_RESOLVIDA" else COMPETENCIA,
                base=None if estado == "NAO_RESOLVIDA" else "ATENDIMENTO",
            )
        )
    return cenario.com(selecoes=tuple(selecoes[: -len(REGRAS)]))


def _chaves_nulas() -> CenarioRegras:
    cenario = cenario_base(*_linhas(), registro(90, cbo="22512"), registro(91, cnes=""))
    sigtap = {"artifact_id": ART_SIGTAP, "dt_competencia": COMPETENCIA}
    nulas: dict[str, tuple[dict[str, object], ...]] = {
        "sigtap_proc_ocupacao.v1": (
            sigtap | {"co_procedimento": "0301010072", "co_ocupacao": None},
        ),
        "cnes_estab_cbo.v1": (
            {
                "artifact_id": ART_CNES,
                "competencia_arquivo": COMPETENCIA,
                "cnes": None,
                "cbo": "999999",
                "n_vinculos": 1,
            },
        ),
        "sigtap_proc_registro.v1": (sigtap | {"co_procedimento": None, "co_registro": "02"},),
        "sigtap_procedimento.v1": (sigtap | {"co_procedimento": None},),
    }
    auxiliares = {nome: linhas + nulas[nome] for nome, linhas in cenario.auxiliares.items()}
    return cenario.com(auxiliares=auxiliares)


def _sia_em_quarentena() -> CenarioRegras:
    cenario = _base()
    return cenario.com(
        integridade=cenario.integridade | {ART_SIA: EstadoIntegridade.QUARENTENA_LEIAUTE}
    )


def _politica_deslocada() -> PoliticaTemporal:
    return PoliticaTemporal(
        politica_id="m_temp_deslocada_sintetica",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo=MetodoId.M_TEMP,
        criterios=tuple(
            CriterioTemporal(
                fonte=fonte, base=BaseTemporal.ATENDIMENTO, deslocamento_meses=_DESLOCAMENTO
            )
            for fonte in (FamiliaFonte.CNES_PF, FamiliaFonte.SIGTAP)
        ),
    )


def _deslocamento_de_um_mes() -> CenarioRegras:
    """Atendimento 202002 consulta as versões de 202001; a matriz só tem a chave Q(r)."""
    linhas = _linhas(competencia_atendimento="202002")
    return cenario_base(*linhas).com(politica=_politica_deslocada())


def _com_criterio_deslocado(regra: RuleSpec) -> RuleSpec:
    fonte = next(r.fonte for r in regra.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)
    criterio = CriterioTemporal(
        fonte=fonte, base=BaseTemporal.ATENDIMENTO, deslocamento_meses=_DESLOCAMENTO
    )
    return regra.model_copy(update={"criterios_temporais": (criterio,)})


def _cenarios() -> dict[str, CenarioRegras]:
    base = _base()
    ausentes = {
        nome: frozenset({colunas})
        for nome, colunas in (
            ("sigtap_proc_ocupacao.v1", "co_ocupacao"),
            ("cnes_estab_cbo.v1", "n_vinculos"),
        )
    }
    return {
        "base": base,
        "cobertura_insuficiente": base.com(cobertura=cobertura_completa("INSUFICIENTE")),
        "sem_matriz_de_cobertura": base.com(cobertura=None),
        "integridade_ruim": _integridade_ruim(),
        "escopo_vazio": _escopo_vazio(),
        "versao_parcialmente_vazia": _versao_parcialmente_vazia(),
        "selecoes_variadas": _selecoes_variadas(),
        "politica_nao_resolvida": base.com(politica=politica(MetodoId.M_TEMP)),
        "auxiliar_omitido": base.com(auxiliares_omitidos=frozenset({"sigtap_procedimento.v1"})),
        "leiaute_incompativel": base.com(colunas_ausentes_auxiliar=ausentes),
        "coluna_ausente": base.com(colunas_ausentes_registro=frozenset({"cnes"})),
        "chaves_nulas_e_codigos_fora_do_padrao": _chaves_nulas(),
        "sia_em_quarentena": _sia_em_quarentena(),
        "deslocamento_de_um_mes": _deslocamento_de_um_mes(),
    }


BATERIA = {nome: coerente(cenario) for nome, cenario in _cenarios().items()}
_AJUSTE_DAS_REGRAS: dict[str, Callable[[RuleSpec], RuleSpec]] = {
    "deslocamento_de_um_mes": _com_criterio_deslocado,
}


def regras_da_bateria(nome: str) -> list[RuleSpec]:
    """Regras do catálogo com o ajuste SINTETICO que o cenário pede (critério temporal)."""
    ajuste = _AJUSTE_DAS_REGRAS.get(nome)
    regras = carregar_regras()
    return regras if ajuste is None else [ajuste(regra) for regra in regras]
