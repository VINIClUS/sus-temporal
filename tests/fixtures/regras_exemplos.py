"""Mundo SINTETICO mínimo em que as quatro regras candidatas ficam CONFORME para o registro base."""

from __future__ import annotations

from sustemporal.contracts.artifacts import EstadoIntegridade
from tests.fixtures.regras_cenario import ESQUEMA_DA_FONTE, CenarioRegras, artefato

__all__ = [
    "ART_CNES",
    "ART_SIA",
    "ART_SIGTAP",
    "COMPETENCIA",
    "FAMILIA_DA_REGRA",
    "REGRAS",
    "artefato_sigtap_vazio",
    "cenario_base",
    "cobertura_completa",
    "registro",
    "selecao",
    "selecoes_para",
]

ART_SIGTAP = artefato(1)
ART_CNES = artefato(2)
ART_SIA = artefato(9)
COMPETENCIA = "202001"
REGRAS = tuple(sorted(ESQUEMA_DA_FONTE))
FAMILIA_DA_REGRA = {
    "PROC_CBO_SIGTAP": "PROCEDIMENTO_CBO",
    "ESTAB_CBO_CNES": "ESTABELECIMENTO_CBO",
    "INSTRUMENTO_REGISTRO_SIGTAP": "INSTRUMENTO_REGISTRO",
    "VIGENCIA_PROCEDIMENTO_SIGTAP": "VIGENCIA_PROCEDIMENTO",
}


def registro(indice: int = 0, **campos: str | None) -> dict[str, str | None]:
    base: dict[str, str | None] = {
        "row_id": f"{ART_SIA}#{indice}",
        "artifact_id": ART_SIA,
        "instrumento": "C",
        "procedimento": "0301010072",
        "cbo": "225125",
        "cnes": "1234567",
        "competencia_atendimento": COMPETENCIA,
        "competencia_processamento": COMPETENCIA,
    }
    return base | campos


def selecao(
    row_id: str,
    rule_id: str,
    estado: str = "SELECIONADA",
    *,
    artefatos: str | None = None,
    competencia: str | None = COMPETENCIA,
    base: str | None = "ATENDIMENTO",
) -> dict[str, str | None]:
    fonte = ESQUEMA_DA_FONTE[rule_id][0]
    padrao = ART_CNES if fonte == "CNES_PF" else ART_SIGTAP
    return {
        "row_id": row_id,
        "rule_id": rule_id,
        "fonte": fonte,
        "base": base,
        "competencia_requerida": competencia,
        "estado": estado,
        "artifact_ids": padrao if artefatos is None else artefatos,
        "observation_ids": "",
        "motivo": "selecao_sintetica",
    }


def selecoes_para(
    registros: tuple[dict[str, str | None], ...],
) -> tuple[dict[str, str | None], ...]:
    return tuple(selecao(str(r["row_id"]), regra) for r in registros for regra in REGRAS)


def cobertura_completa(estado: str = "DISPONIVEL") -> tuple[dict[str, str | None], ...]:
    return tuple(
        {
            "familia_regra": familia,
            "instrumento": instrumento,
            "competencia": COMPETENCIA,
            "base_temporal": "ATENDIMENTO",
            "estado": estado,
            "motivo": None if estado == "DISPONIVEL" else "sintetico",
        }
        for familia in sorted(FAMILIA_DA_REGRA.values())
        for instrumento in ("C", "I", "P", "S", "A", "B")
    )


def _auxiliares() -> dict[str, tuple[dict[str, object], ...]]:
    sigtap = {"artifact_id": ART_SIGTAP, "dt_competencia": COMPETENCIA}
    return {
        "sigtap_proc_ocupacao.v1": (
            sigtap | {"co_procedimento": "0301010072", "co_ocupacao": "225125"},
            sigtap | {"co_procedimento": "0301010072", "co_ocupacao": "223505"},
        ),
        "cnes_estab_cbo.v1": (
            {
                "artifact_id": ART_CNES,
                "competencia_arquivo": COMPETENCIA,
                "cnes": "1234567",
                "cbo": "225125",
                "n_vinculos": 2,
            },
        ),
        "sigtap_proc_registro.v1": (
            sigtap | {"co_procedimento": "0301010072", "co_registro": "01"},
        ),
        "sigtap_procedimento.v1": (sigtap | {"co_procedimento": "0301010072"},),
    }


def cenario_base(*registros: dict[str, str | None]) -> CenarioRegras:
    linhas = registros or (registro(),)
    return CenarioRegras(
        registros=linhas,
        auxiliares=_auxiliares(),
        selecoes=selecoes_para(linhas),
        cobertura=cobertura_completa(),
        integridade=dict.fromkeys((ART_SIGTAP, ART_CNES, ART_SIA), EstadoIntegridade.OK),
    )


def artefato_sigtap_vazio() -> str:
    """Versão SIGTAP registrada no conjunto, mas sem nenhuma linha (escopo vazio)."""
    return artefato(3)
