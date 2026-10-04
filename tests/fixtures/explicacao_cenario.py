"""Execuções SINTETICAS do motor para explicações, PROV e baselines (T08)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    EstadoSelecao,
    MetodoId,
    SelecaoVersao,
    SnapshotSet,
)
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import CenarioRegras, artefato, coerente, materializar, politica
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIA,
    ART_SIGTAP,
    COMPETENCIA,
    FAMILIA_DA_REGRA,
    cenario_base,
    registro,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "ART_CNES_ALT",
    "ART_CNES_PROC",
    "ART_SIGTAP_ALT",
    "ART_SIGTAP_PROC",
    "LINHA_CONFORME",
    "LINHA_INCONCLUSIVA",
    "LINHA_NAO_APLICAVEL",
    "LINHA_VIOLACAO",
    "PROCESSAMENTO",
    "cenario_ablacao",
    "cenario_explicacao",
    "cenario_temporal",
    "executar_cenario",
    "executar_metodo",
    "snapshot_temporal",
]

LINHA_CONFORME = f"{ART_SIA}#0"
LINHA_VIOLACAO = f"{ART_SIA}#1"
LINHA_INCONCLUSIVA = f"{ART_SIA}#2"
LINHA_NAO_APLICAVEL = f"{ART_SIA}#3"
PROCESSAMENTO = "202002"
ART_SIGTAP_PROC = artefato(11)
ART_CNES_PROC = artefato(12)
ART_SIGTAP_ALT = artefato(21)
ART_CNES_ALT = artefato(22)


def cenario_explicacao() -> CenarioRegras:
    """Conforme, violação (par CNES–CBO sem vínculo), inconclusiva (CNES fora) e instrumento I."""
    return cenario_base(
        registro(0),
        registro(1, cbo="223505"),
        registro(2, cnes="7654321"),
        registro(3, instrumento="I"),
    )


def executar_cenario(
    tmp_path: Path,
    cenario: CenarioRegras | None = None,
    *,
    nome: str = "execucao",
    regras: list[RuleSpec] | None = None,
) -> RunResult:
    """Sem `regras`, o catálogo inteiro; `regras_so_de_c` deixa a linha 3 não aplicável."""
    dataset, insumos = materializar(cenario or cenario_explicacao(), tmp_path / nome / "entrada")
    return evaluate_rules(
        dataset,
        SnapshotSet.criar(artifact_ids=(), observation_ids=(), dataset_hashes=(), selecoes=()),
        regras if regras is not None else carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / nome / "saida",
        insumos=insumos,
    )


def _cobertura_temporal() -> tuple[dict[str, str | None], ...]:
    return tuple(
        {
            "familia_regra": familia,
            "instrumento": "C",
            "competencia": PROCESSAMENTO,
            "base_temporal": base,
            "estado": "DISPONIVEL",
            "motivo": None,
        }
        for familia in sorted(FAMILIA_DA_REGRA.values())
        for base in ("ATENDIMENTO", "PROCESSAMENTO")
    )


def _auxiliares_temporais() -> dict[str, tuple[dict[str, object], ...]]:
    """Duas versões por fonte: 202001 (atendimento) e 202002 (processamento) sem o par CBO."""
    proc = {"artifact_id": ART_SIGTAP_PROC, "dt_competencia": PROCESSAMENTO}
    atend = {"artifact_id": ART_SIGTAP, "dt_competencia": COMPETENCIA}
    cnes = {"cnes": "1234567", "cbo": "225125", "n_vinculos": 2}
    return {
        "sigtap_proc_ocupacao.v1": (
            atend | {"co_procedimento": "0301010072", "co_ocupacao": "225125"},
            proc | {"co_procedimento": "0301010072", "co_ocupacao": "223505"},
        ),
        "cnes_estab_cbo.v1": (
            {"artifact_id": ART_CNES, "competencia_arquivo": COMPETENCIA} | cnes,
            {"artifact_id": ART_CNES_PROC, "competencia_arquivo": PROCESSAMENTO}
            | cnes
            | {"cbo": "223505"},
        ),
        "sigtap_proc_registro.v1": (
            atend | {"co_procedimento": "0301010072", "co_registro": "01"},
            proc | {"co_procedimento": "0301010072", "co_registro": "01"},
        ),
        "sigtap_procedimento.v1": (
            atend | {"co_procedimento": "0301010072"},
            proc | {"co_procedimento": "0301010072"},
        ),
    }


def cenario_temporal(metodo: MetodoId) -> CenarioRegras:
    """Atendimento 202001 e processamento 202002: só a política decide a versão consultada."""
    linhas = (registro(0, competencia_processamento=PROCESSAMENTO),)
    artefatos = (ART_SIGTAP, ART_CNES, ART_SIGTAP_PROC, ART_CNES_PROC, ART_SIA)
    return coerente(
        CenarioRegras(
            registros=linhas,
            auxiliares=_auxiliares_temporais(),
            selecoes=(),
            cobertura=_cobertura_temporal(),
            integridade=dict.fromkeys(artefatos, EstadoIntegridade.OK),
            politica=politica(metodo),
        )
    )


def _selecao(fonte: FamiliaFonte, base: BaseTemporal, competencia: str, art: str) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=fonte,
        base=base,
        competencia_requerida=CompetenciaArquivo(competencia),
        estado=EstadoSelecao.SELECIONADA,
        artifact_ids=(art,),
        motivo=f"selecao_sintetica base={base} competencia={competencia}",
    )


def snapshot_temporal() -> SnapshotSet:
    """Mesmo conjunto de versões para as duas políticas (correspondência exata por base)."""
    selecoes = (
        _selecao(FamiliaFonte.SIGTAP, BaseTemporal.ATENDIMENTO, COMPETENCIA, ART_SIGTAP),
        _selecao(FamiliaFonte.CNES_PF, BaseTemporal.ATENDIMENTO, COMPETENCIA, ART_CNES),
        _selecao(FamiliaFonte.SIGTAP, BaseTemporal.PROCESSAMENTO, PROCESSAMENTO, ART_SIGTAP_PROC),
        _selecao(FamiliaFonte.CNES_PF, BaseTemporal.PROCESSAMENTO, PROCESSAMENTO, ART_CNES_PROC),
    )
    artefatos = tuple(sorted({a for s in selecoes for a in s.artifact_ids}))
    return SnapshotSet.criar(
        artifact_ids=artefatos, observation_ids=(), dataset_hashes=(), selecoes=selecoes
    )


def executar_metodo(tmp_path: Path, metodo: MetodoId) -> RunResult:
    """B_ATEND ou B_PROC sobre os mesmos parquet, catálogo e snapshot; seleção derivada."""
    dataset, insumos = materializar(cenario_temporal(metodo), tmp_path / "entrada")
    return evaluate_rules(
        dataset,
        snapshot_temporal(),
        carregar_regras(),
        RunConfig(versao="1", metodos=(metodo,)),
        tmp_path / "saida",
        insumos=replace(insumos, selecoes=None),
    )


def cenario_ablacao() -> CenarioRegras:
    """Versões alternativas da mesma competência (republicação SINTETICA) sem o par do registro."""
    base = cenario_base(registro(0))
    auxiliares = dict(base.auxiliares)
    sigtap = {"artifact_id": ART_SIGTAP_ALT, "dt_competencia": COMPETENCIA}
    auxiliares["cnes_estab_cbo.v1"] = (
        *auxiliares["cnes_estab_cbo.v1"],
        {
            "artifact_id": ART_CNES_ALT,
            "competencia_arquivo": COMPETENCIA,
            "cnes": "1234567",
            "cbo": "223505",
            "n_vinculos": 1,
        },
    )
    auxiliares["sigtap_proc_ocupacao.v1"] = (
        *auxiliares["sigtap_proc_ocupacao.v1"],
        sigtap | {"co_procedimento": "0301010072", "co_ocupacao": "223505"},
    )
    for schema_id in ("sigtap_proc_registro.v1", "sigtap_procedimento.v1"):
        auxiliares[schema_id] = (
            *auxiliares[schema_id],
            *(linha | {"artifact_id": ART_SIGTAP_ALT} for linha in auxiliares[schema_id]),
        )
    integridade = dict(base.integridade) | dict.fromkeys(
        (ART_SIGTAP_ALT, ART_CNES_ALT), EstadoIntegridade.OK
    )
    return base.com(auxiliares=auxiliares, integridade=integridade)
