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
    "ART_CNES_OUTRA",
    "ART_CNES_PROC",
    "ART_SIGTAP_ALT",
    "ART_SIGTAP_PROC",
    "LINHA_CONFORME",
    "LINHA_INCONCLUSIVA",
    "LINHA_NAO_APLICAVEL",
    "LINHA_VIOLACAO",
    "PROCESSAMENTO",
    "cenario_ablacao",
    "cenario_diferencial",
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
ART_CNES_OUTRA = artefato(23)


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
    saida: Path | None = None,
) -> RunResult:
    """Sem `regras`, o catálogo inteiro; `regras_so_de_c` deixa a linha 3 não aplicável.

    `saida` é a pasta que recebe `<run_id>/` (padrão: `<tmp_path>/<nome>/saida`).
    """
    dataset, insumos = materializar(cenario or cenario_explicacao(), tmp_path / nome / "entrada")
    return evaluate_rules(
        dataset,
        SnapshotSet.criar(artifact_ids=(), observation_ids=(), dataset_hashes=(), selecoes=()),
        regras if regras is not None else carregar_regras(),
        RunConfig(versao="1"),
        saida or tmp_path / nome / "saida",
        insumos=insumos,
    )


def _cobertura_temporal(processamento: str) -> tuple[dict[str, str | None], ...]:
    return tuple(
        {
            "familia_regra": familia,
            "instrumento": "C",
            "competencia": processamento,
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


def cenario_temporal(metodo: MetodoId, processamento: str = PROCESSAMENTO) -> CenarioRegras:
    """Atendimento 202001 e processamento 202002: só a política decide a versão consultada."""
    linhas = (registro(0, competencia_processamento=processamento),)
    artefatos = (ART_SIGTAP, ART_CNES, ART_SIGTAP_PROC, ART_CNES_PROC, ART_SIA)
    return coerente(
        CenarioRegras(
            registros=linhas,
            auxiliares=_auxiliares_temporais(),
            selecoes=(),
            cobertura=_cobertura_temporal(processamento),
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


def snapshot_temporal(processamento: str = PROCESSAMENTO) -> SnapshotSet:
    """Mesmo conjunto de versões para as duas políticas (correspondência exata por base)."""
    mesma = processamento == COMPETENCIA
    sigtap_proc = ART_SIGTAP if mesma else ART_SIGTAP_PROC
    cnes_proc = ART_CNES if mesma else ART_CNES_PROC
    proc = BaseTemporal.PROCESSAMENTO
    selecoes = (
        _selecao(FamiliaFonte.SIGTAP, BaseTemporal.ATENDIMENTO, COMPETENCIA, ART_SIGTAP),
        _selecao(FamiliaFonte.CNES_PF, BaseTemporal.ATENDIMENTO, COMPETENCIA, ART_CNES),
        _selecao(FamiliaFonte.SIGTAP, proc, processamento, sigtap_proc),
        _selecao(FamiliaFonte.CNES_PF, proc, processamento, cnes_proc),
    )
    artefatos = tuple(sorted({a for s in selecoes for a in s.artifact_ids}))
    return SnapshotSet.criar(
        artifact_ids=artefatos, observation_ids=(), dataset_hashes=(), selecoes=selecoes
    )


def executar_metodo(
    tmp_path: Path, metodo: MetodoId, *, processamento: str = PROCESSAMENTO
) -> RunResult:
    """B_ATEND ou B_PROC sobre os mesmos parquet, catálogo e snapshot; seleção derivada."""
    cenario = cenario_temporal(metodo, processamento)
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    return evaluate_rules(
        dataset,
        snapshot_temporal(processamento),
        carregar_regras(),
        RunConfig(versao="1", metodos=(metodo,)),
        tmp_path / "saida",
        insumos=replace(insumos, selecoes=None),
    )


def cenario_ablacao(*registros: dict[str, str | None]) -> CenarioRegras:
    """Versões alternativas da mesma competência (republicação SINTETICA) sem o par do registro."""
    base = cenario_base(*(registros or (registro(0),)))
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
    auxiliares["cnes_estab_cbo.v1"] = (
        *auxiliares["cnes_estab_cbo.v1"],
        {
            "artifact_id": ART_CNES_OUTRA,
            "competencia_arquivo": PROCESSAMENTO,
            "cnes": "1234567",
            "cbo": "225125",
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
        (ART_SIGTAP_ALT, ART_CNES_ALT, ART_CNES_OUTRA), EstadoIntegridade.OK
    )
    return base.com(auxiliares=auxiliares, integridade=integridade)


def _cnes(artifact_id: str, cbo: str, n_vinculos: int) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "competencia_arquivo": COMPETENCIA,
        "cnes": "1234567",
        "cbo": cbo,
        "n_vinculos": n_vinculos,
    }


def _auxiliares_diferenciais() -> dict[str, tuple[dict[str, object], ...]]:
    """Duas versões selecionadas por fonte, `n_vinculos = 0` e linhas com nulos (SINTETICO)."""
    versoes = (
        {"artifact_id": a, "dt_competencia": COMPETENCIA} for a in (ART_SIGTAP, ART_SIGTAP_ALT)
    )
    sigtap = list(versoes)
    return {
        "sigtap_proc_ocupacao.v1": (
            *(v | {"co_procedimento": "0301010072", "co_ocupacao": "225125"} for v in sigtap),
            sigtap[1] | {"co_procedimento": "0301010072", "co_ocupacao": "223505"},
            sigtap[0] | {"co_procedimento": "0202020202", "co_ocupacao": None},
        ),
        "cnes_estab_cbo.v1": (
            _cnes(ART_CNES, "225125", 0),
            _cnes(ART_CNES, "223505", 2),
            _cnes(ART_CNES_ALT, "225125", 3),
            _cnes(ART_CNES_ALT, "223505", 0),
            _cnes(ART_CNES_ALT, "322205", 0),
        ),
        "sigtap_proc_registro.v1": tuple(
            v | {"co_procedimento": "0301010072", "co_registro": "01"} for v in sigtap
        ),
        "sigtap_procedimento.v1": (
            *(v | {"co_procedimento": "0301010072"} for v in sigtap),
            sigtap[1] | {"co_procedimento": None},
        ),
    }


def cenario_diferencial() -> CenarioRegras:
    """Para comparar o motor com a reexecução das evidências nas quatro famílias."""
    linhas = (registro(0), registro(1, cbo="223505"), registro(2, cbo="322205"))
    artefatos = {
        "CNES_PF": ";".join(sorted((ART_CNES, ART_CNES_ALT))),
        "SIGTAP": ";".join(sorted((ART_SIGTAP, ART_SIGTAP_ALT))),
    }
    base = cenario_base(*linhas)
    selecoes = tuple(s | {"artifact_ids": artefatos[str(s["fonte"])]} for s in base.selecoes)
    integridade = dict(base.integridade) | dict.fromkeys(
        (ART_SIGTAP_ALT, ART_CNES_ALT), EstadoIntegridade.OK
    )
    return base.com(
        auxiliares=_auxiliares_diferenciais(), selecoes=selecoes, integridade=integridade
    )
