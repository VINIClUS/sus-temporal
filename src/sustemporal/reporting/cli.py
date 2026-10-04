"""Comando `sustemporal pilot-report`: relatório do piloto de observabilidade (T05).

Lê a execução mais recente do `ingest` (`<raiz_saidas>/ingest/execucao_*/datasets.jsonl`), faz a
seleção temporal em lote (B_PROC e B_ATEND) de cada conjunto SIA-PA contra o prefixo do
manifesto de aquisição que a ingestão leu (`manifesto_lido.json`) e grava, numa pasta nova
`<raiz_saidas>/pilot/execucao_<instante>_<id>/`, as tabelas do relatório, as seleções e
`relatorio.json` (o `EvaluationReport`).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import EstadoManifesto, Manifesto
from sustemporal.contracts import CohortSpec, DatasetRef
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro
from sustemporal.ingest.cli import NOME_POSICAO_MANIFESTO
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


def _ultima_ingestao(raiz_saidas: Path) -> Path:
    raiz = raiz_saidas / "ingest"
    execucoes = sorted(p for p in raiz.iterdir() if p.is_dir()) if raiz.is_dir() else []
    if not execucoes:
        raise FalhaOperacionalErro(f"pilot_report_sem_ingest raiz={raiz}")
    return execucoes[-1]


def _datasets_do_ingest(execucao: Path) -> list[DatasetRef]:
    linhas = (execucao / "datasets.jsonl").read_text(encoding="utf-8").splitlines()
    return [DatasetRef.model_validate(json.loads(linha)) for linha in linhas if linha]


def _manifesto_lido(execucao: Path, manifesto: Path) -> EstadoManifesto:
    """O prefixo do manifesto que a ingestão leu, conferido pelo hash encadeado da última linha.

    Raises:
        ConfigInvalida: posição não registrada, além do manifesto atual ou com hash divergente.
    """
    caminho = execucao / NOME_POSICAO_MANIFESTO
    if not caminho.is_file():
        raise ConfigInvalida(f"pilot_report_sem_posicao_do_manifesto ingest={execucao.name}")
    try:
        posicao = json.loads(caminho.read_text(encoding="utf-8"))
        linhas, cabeca = posicao["linhas"], posicao["cabeca_sha256"]
    except (ValueError, KeyError, TypeError) as erro:
        raise ConfigInvalida(f"pilot_report_posicao_ilegivel ingest={execucao.name}") from erro
    atual = Manifesto(manifesto).ler()
    if type(linhas) is not int or not 0 <= linhas <= len(atual.linhas):
        raise ConfigInvalida(f"pilot_report_posicao_alem_do_manifesto linhas={linhas}")
    prefixo = EstadoManifesto(atual.linhas[:linhas])
    if prefixo.cabeca_sha256 != cabeca:
        raise ConfigInvalida(f"pilot_report_manifesto_divergente linhas={linhas}")
    return prefixo


def _pasta_execucao(raiz: Path) -> Path:
    pasta = raiz / f"execucao_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex[:8]}"
    pasta.mkdir(parents=True, exist_ok=False)
    return pasta


def _selecoes(
    datasets: list[DatasetRef], config: RunConfig, lido: EstadoManifesto, saida: Path
) -> list[DatasetRef]:
    registro = RegistroTemporal(
        lido.observacoes, dict(lido.versoes), dict(partes_esperadas_do_catalogo(config))
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
        ConfigInvalida: configuração sem piloto, território inválido ou posição do manifesto
            lida pela ingestão ausente ou divergente do manifesto atual.
        FalhaOperacionalErro: nenhuma execução do `ingest` em `raiz_saidas`.
    """
    if config.piloto is None:
        raise ConfigInvalida("pilot_report_exige_piloto")
    raiz_saidas = Path(config.runtime.raiz_saidas)
    ingestao = _ultima_ingestao(raiz_saidas)
    datasets = _datasets_do_ingest(ingestao)
    manifesto = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
    lido = _manifesto_lido(ingestao, manifesto)
    saida = _pasta_execucao(raiz_saidas / "pilot")
    selecoes = _selecoes(datasets, config, lido, saida)
    observacoes = {o.observation_id: o.resultado for o in lido.observacoes}
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
