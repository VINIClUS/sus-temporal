"""Comando `sustemporal pilot-report`: relatório do piloto de observabilidade (T05).

Lê a execução mais recente do `ingest` (`<raiz_saidas>/ingest/execucao_*/datasets.jsonl`), faz a
seleção temporal em lote (B_PROC e B_ATEND) de cada conjunto SIA-PA contra o manifesto de
aquisição e grava, numa pasta nova `<raiz_saidas>/pilot/execucao_<instante>_<id>/`, as tabelas do
relatório, as seleções e `relatorio.json` (o `EvaluationReport`).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import CohortSpec, DatasetRef
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro
from sustemporal.reporting.report import build_pilot_report
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.insumos import InsumosAvaliacao
from sustemporal.rules.lote import selecionar_em_lote
from sustemporal.temporal.politicas import carregar_politica
from sustemporal.temporal.registry import RegistroTemporal
from sustemporal.temporal.selector import partes_esperadas_do_catalogo

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import PilotSpec, RunConfig

__all__ = ["executar_pilot_report"]

logger = logging.getLogger(__name__)

# O piloto mede a disponibilidade nas duas bases temporais (B_PROC e B_ATEND); M_TEMP segue
# NAO_RESOLVIDA até o G0.
POLITICAS_PILOTO = ("B_PROC", "B_ATEND")


def _coorte(config: RunConfig, piloto: PilotSpec) -> CohortSpec:
    """A coorte da configuração; sem ela, a do piloto (UF, território e competências)."""
    if config.coorte is not None:
        return config.coorte
    competencias = sorted(c.valor for c in piloto.competencias_processamento)
    return CohortSpec.model_validate(
        {
            "cohort_id": f"piloto_{piloto.uf}",
            "uf": piloto.uf,
            "territorio": piloto.territorio,
            "inicio": competencias[0],
            "fim": competencias[-1],
        }
    )


def _datasets_do_ingest(raiz_saidas: Path) -> list[DatasetRef]:
    raiz = raiz_saidas / "ingest"
    execucoes = sorted(p for p in raiz.iterdir() if p.is_dir()) if raiz.is_dir() else []
    if not execucoes:
        raise FalhaOperacionalErro(f"pilot_report_sem_ingest raiz={raiz}")
    linhas = (execucoes[-1] / "datasets.jsonl").read_text(encoding="utf-8").splitlines()
    return [DatasetRef.model_validate(json.loads(linha)) for linha in linhas if linha]


def _pasta_execucao(raiz: Path) -> Path:
    pasta = raiz / f"execucao_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex[:8]}"
    pasta.mkdir(parents=True, exist_ok=False)
    return pasta


def _selecoes(
    datasets: list[DatasetRef], config: RunConfig, manifesto: Path, saida: Path
) -> list[DatasetRef]:
    registro = RegistroTemporal.de_manifesto(
        manifesto, partes_esperadas=partes_esperadas_do_catalogo(config)
    )
    regras = carregar_regras()
    selecoes = []
    for politica_id in POLITICAS_PILOTO:
        insumos = InsumosAvaliacao(politica=carregar_politica(politica_id))
        for dataset in (d for d in datasets if d.schema_id == "sia_pa.v1"):
            lote = selecionar_em_lote(
                dataset, regras, config, registro, saida / "selecoes", insumos=insumos
            )
            selecoes.append(lote.selecoes)
    return selecoes


def executar_pilot_report(args: argparse.Namespace, config: RunConfig) -> int:
    """Lê a última execução do `ingest`, seleciona as versões e grava o relatório do piloto.

    Raises:
        ConfigInvalida: configuração sem piloto ou com território inválido.
        FalhaOperacionalErro: nenhuma execução do `ingest` em `raiz_saidas`.
    """
    if config.piloto is None:
        raise ConfigInvalida("pilot_report_exige_piloto")
    raiz_saidas = Path(config.runtime.raiz_saidas)
    datasets = _datasets_do_ingest(raiz_saidas)
    manifesto = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
    saida = _pasta_execucao(raiz_saidas / "pilot")
    selecoes = _selecoes(datasets, config, manifesto, saida)
    observacoes = {o.observation_id: o.resultado for o in Manifesto(manifesto).ler().observacoes}
    relatorio = build_pilot_report(
        [*datasets, *selecoes],
        _coorte(config, config.piloto),
        saida,
        observacoes=observacoes,
        runtime=config.runtime,
    )
    destino = saida / "relatorio.json"
    temporario = destino.with_name(f".{destino.name}.tmp")
    temporario.write_text(relatorio.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporario.replace(destino)
    logger.info(
        "pilot_report_concluido report=%s saida=%s args=%s",
        relatorio.report_id,
        saida,
        vars(args).get("comando"),
    )
    return ExitCode.OK
