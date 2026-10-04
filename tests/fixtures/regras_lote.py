"""Ponta a ponta SINTETICO: SIA-PA canônico, registro temporal e seleção em lote (T06 → T07).

Fevereiro difere de janeiro só no CNES: o par (1234567, 225125) existe em 202301 e falta em
202302. Assim B_ATEND e B_PROC divergem no registro atendido em janeiro e processado em fevereiro.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte, ValorNormalizado
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.records import ProductionRecord, RowLocator
from sustemporal.temporal.registry import registro_de
from tests.fixtures.regras_cenario import CenarioRegras, materializar
from tests.fixtures.regras_exemplos import ART_SIA, FAMILIA_DA_REGRA, registro
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.rules.insumos import InsumosAvaliacao
    from sustemporal.temporal.registry import RegistroTemporal


__all__ = ["COMPETENCIAS", "MundoLote", "config_lote", "mundo_lote", "registros_de_producao"]

JANEIRO, FEVEREIRO = "202301", "202302"
COMPETENCIAS = (JANEIRO, FEVEREIRO)
_PROCEDIMENTO, _CBO, _CNES = "0301010072", "225125", "1234567"
_REGISTROS = (
    registro(0, competencia_atendimento=JANEIRO, competencia_processamento=FEVEREIRO),
    registro(1, competencia_atendimento=FEVEREIRO, competencia_processamento=FEVEREIRO),
    registro(2, competencia_atendimento=JANEIRO, competencia_processamento=JANEIRO),
    registro(3, competencia_atendimento=None, competencia_processamento=JANEIRO),
)


@dataclass(frozen=True)
class MundoLote:
    dataset: DatasetRef
    insumos: InsumosAvaliacao
    registro: RegistroTemporal


def _observacoes(
    *, cnes_fev_quarentena: bool, sigtap_fev_ausente: bool
) -> list[tuple[ArtifactObservation, ArtifactVersion | None]]:
    quarentena = EstadoIntegridade.QUARENTENA_TRUNCADO
    sem_sigtap = ResultadoTentativa.NAO_ENCONTRADO
    return [
        observar(FamiliaFonte.CNES_PF, JANEIRO, "cnes-jan", 1),
        observar(
            FamiliaFonte.CNES_PF,
            FEVEREIRO,
            "cnes-fev",
            2,
            integridade=quarentena if cnes_fev_quarentena else EstadoIntegridade.OK,
        ),
        observar(FamiliaFonte.SIGTAP, JANEIRO, "sigtap-jan", 1, uf=None),
        observar(
            FamiliaFonte.SIGTAP,
            FEVEREIRO,
            "sigtap-fev",
            2,
            uf=None,
            resultado=sem_sigtap if sigtap_fev_ausente else ResultadoTentativa.OBTIDO,
        ),
    ]


def _sigtap(artefato: str, competencia: str) -> dict[str, tuple[dict[str, object], ...]]:
    base: dict[str, object] = {"artifact_id": artefato, "dt_competencia": competencia}
    return {
        "sigtap_proc_ocupacao.v1": (
            base | {"co_procedimento": _PROCEDIMENTO, "co_ocupacao": _CBO},
        ),
        "sigtap_proc_registro.v1": (
            base | {"co_procedimento": _PROCEDIMENTO, "co_registro": "01"},
        ),
        "sigtap_procedimento.v1": (base | {"co_procedimento": _PROCEDIMENTO},),
    }


def _cnes(artefato: str, competencia: str, cbo: str) -> dict[str, object]:
    return {
        "artifact_id": artefato,
        "competencia_arquivo": competencia,
        "cnes": _CNES,
        "cbo": cbo,
        "n_vinculos": 1,
    }


def _auxiliares(versoes: list[ArtifactVersion]) -> dict[str, tuple[dict[str, object], ...]]:
    linhas: dict[str, tuple[dict[str, object], ...]] = {"cnes_estab_cbo.v1": ()}
    for versao in sorted(versoes, key=lambda v: v.artifact_id):
        competencia = str(versao.chave.competencia_arquivo)
        if versao.chave.fonte is FamiliaFonte.CNES_PF:
            cbo = _CBO if competencia == JANEIRO else "223505"
            linhas["cnes_estab_cbo.v1"] += (_cnes(versao.artifact_id, competencia, cbo),)
            continue
        for schema_id, novas in _sigtap(versao.artifact_id, competencia).items():
            linhas[schema_id] = linhas.get(schema_id, ()) + novas
    return linhas


def _cobertura() -> tuple[dict[str, str | None], ...]:
    return tuple(
        {
            "familia_regra": familia,
            "instrumento": instrumento,
            "competencia": competencia,
            "base_temporal": base,
            "estado": "DISPONIVEL",
            "motivo": None,
        }
        for familia in sorted(FAMILIA_DA_REGRA.values())
        for instrumento in ("C", "I")
        for competencia in COMPETENCIAS
        for base in ("ATENDIMENTO", "PROCESSAMENTO")
    )


def mundo_lote(
    raiz: Path, *, cnes_fev_quarentena: bool = False, sigtap_fev_ausente: bool = False
) -> MundoLote:
    """SIA-PA canônico, auxiliares e registro temporal coerentes entre si (SINTETICO)."""
    itens = _observacoes(
        cnes_fev_quarentena=cnes_fev_quarentena, sigtap_fev_ausente=sigtap_fev_ausente
    )
    versoes = [v for _, v in itens if v is not None]
    integridade = {v.artifact_id: v.integridade for v in versoes}
    integridade[ART_SIA] = EstadoIntegridade.OK
    cenario = CenarioRegras(
        registros=_REGISTROS,
        auxiliares=_auxiliares(versoes),
        selecoes=(),
        cobertura=_cobertura(),
        integridade=integridade,
    )
    dataset, insumos = materializar(cenario, raiz)
    sem_selecao = replace(insumos, selecoes=None, politica=None)
    return MundoLote(dataset, sem_selecao, registro_de([o for o, _ in itens], versoes))


def registros_de_producao() -> list[ProductionRecord]:
    """Os mesmos registros do parquet como `ProductionRecord` (seleção por registro do T06)."""
    registros = []
    for indice, linha in enumerate(_REGISTROS):
        origem = RowLocator(artifact_id=ART_SIA, indice=indice)
        registros.append(
            ProductionRecord(
                row_id=origem.row_id(),
                origem=origem,
                competencia_atendimento=linha["competencia_atendimento"],
                competencia_processamento=linha["competencia_processamento"],
                instrumento=ValorNormalizado(bruto="C", valor="C"),
            )
        )
    return registros


def config_lote(politica_id: str | None, **campos: object) -> RunConfig:
    piloto = {
        "uf": "SP",
        "competencias_processamento": list(COMPETENCIAS),
        "territorio": "catalog/territorio/drs_xi.yaml",
        "familias_fontes": ["SIA_PA", "CNES_PF", "SIGTAP"],
    }
    base: dict[str, object] = {"versao": "1", "politica_id": politica_id, "piloto": piloto}
    return RunConfig.model_validate(base | campos)
