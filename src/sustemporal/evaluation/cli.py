"""Comandos `sustemporal freeze` e `sustemporal evaluate --freeze FREEZE_ID` (T11).

Entradas por convenção, sempre resolvidas por id exato e nunca por "latest":
`<raiz_saidas>/split/<split_id>.json` (único) com `<split_id>.entradas.json` (dataset e rótulos
completos), execuções em `<raiz_saidas>/runs/<run_id>/run.json` e congelamentos em
`<dir_congelamentos>/<freeze_id>.json`. O registro append-only fica em
`<dir_congelamentos>/registro_execucoes.jsonl`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.experiment import (
    ModoExecucao,
    Particao,
    Portao,
    RunResult,
    SplitManifest,
)
from sustemporal.contracts.records import DatasetRef
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ConfigInvalida, ExitCode, PortaoRecusado
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.freeze import (
    Protocolo,
    carregar_freeze,
    congelar,
    referencia_decisao,
    verificar_compatibilidade,
)
from sustemporal.evaluation.freeze_registro import exigir_rodada_permitida, registrar_execucao
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs
from sustemporal.evaluation.split import SUFIXO_ENTRADAS
from sustemporal.gates import DIR_DECISOES, exigir_portao
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.insumos import politica_padrao
from sustemporal.runtime_info import versao_codigo
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import FreezeManifest, RuleSpec, RunConfig
    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = ["REGISTRO", "executar_evaluate", "executar_freeze", "versao_codigo"]

logger = logging.getLogger(__name__)

REGISTRO = "registro_execucoes.jsonl"


def _split_e_entradas(raiz: Path) -> tuple[SplitManifest, DatasetRef, DatasetRef]:
    pasta = raiz / "split"
    manifestos = [
        caminho
        for caminho in sorted(pasta.glob("spl_*.json"))
        if not caminho.name.endswith(SUFIXO_ENTRADAS)
    ]
    if len(manifestos) != 1:
        raise ConfigInvalida(f"split_ausente_ou_ambiguo pasta={pasta} n={len(manifestos)}")
    try:
        split = SplitManifest.model_validate_json(manifestos[0].read_text(encoding="utf-8"))
        entradas = json.loads((pasta / f"{split.split_id}{SUFIXO_ENTRADAS}").read_text())
        dataset = DatasetRef.model_validate(entradas["dataset"])
        rotulos = DatasetRef.model_validate(entradas["rotulos"])
    except (OSError, ValueError, KeyError, ValidationError) as erro:
        raise ConfigInvalida(f"split_ilegivel pasta={pasta} erro={erro}") from erro
    return split, dataset, rotulos


def _regras_do_catalogo() -> list[RuleSpec]:
    try:
        return carregar_regras()
    except CatalogoInvalido as erro:
        raise ConfigInvalida(f"freeze_catalogo_de_regras_invalido erro={erro}") from erro


def _politicas_do_catalogo(regras: list[RuleSpec]) -> list[PoliticaTemporal]:
    """Políticas de `catalog/policies` e as padrão dos baselines, como `validate` as resolve."""
    arquivos = sorted(DIRETORIO_POLITICAS.glob("*.yaml"))
    catalogo = [carregar_politica(arquivo.stem) for arquivo in arquivos]
    padrao = [politica_padrao(metodo, regras) for metodo in (MetodoId.B_ATEND, MetodoId.B_PROC)]
    return [*catalogo, *padrao]


def executar_freeze(args: argparse.Namespace, config: RunConfig) -> int:
    """Congela o protocolo a partir do split e das entradas em `<raiz_saidas>/split`.

    O manifesto registra também a identidade do catálogo de regras e das políticas do catálogo.

    Raises:
        ConfigInvalida: sem catálogos na config, split ausente, catálogo de regras ou políticas
            inválido, ou protocolo inválido.
        PortaoRecusado: G0 ausente ou que não libera.
    """
    if not config.catalogos:
        raise ConfigInvalida("freeze_sem_catalogos")
    split, dataset, rotulos = _split_e_entradas(Path(config.runtime.raiz_saidas))
    regras = _regras_do_catalogo()
    protocolo = Protocolo(
        config=config,
        split=split,
        features=FEATURES_PADRAO,
        dataset=dataset,
        rotulos=rotulos,
        catalogos={nome: Path(caminho) for nome, caminho in config.catalogos.items()},
        regras=regras,
        politicas=_politicas_do_catalogo(regras),
    )
    destino = Path(config.runtime.dir_congelamentos)
    manifesto = congelar(protocolo, destino, codigo=versao_codigo(Path.cwd()))
    logger.info("freeze_emitido freeze=%s comando=%s", manifesto.freeze_id, args.comando)
    return int(ExitCode.OK)


def _runs(pasta: Path, modo: ModoExecucao, freeze_id: str) -> list[RunResult]:
    runs = []
    for caminho in sorted(pasta.glob("*/run.json")):
        run = RunResult.model_validate_json(caminho.read_text(encoding="utf-8"))
        confirmatoria = modo is ModoExecucao.CONFIRMATORIO
        if run.modo is modo and (not confirmatoria or run.freeze_id == freeze_id):
            runs.append(run)
    return runs


def _conferir(
    manifesto: FreezeManifest,
    config: RunConfig,
    entradas: tuple[SplitManifest, DatasetRef, DatasetRef],
) -> None:
    split, dataset, rotulos = entradas
    try:
        verificar_compatibilidade(
            manifesto,
            config=config,
            split=split,
            features=FEATURES_PADRAO,
            datasets=[dataset, rotulos],
            codigo=versao_codigo(Path.cwd()),
        )
    except PortaoRecusado as erro:
        if config.modo is ModoExecucao.CONFIRMATORIO:
            raise
        logger.warning("evaluate_exploratorio_divergente_do_freeze erro=%s", erro)


def executar_evaluate(args: argparse.Namespace, config: RunConfig) -> int:
    """Avalia as execuções do congelamento e acrescenta o resultado ao registro.

    O confirmatório (já liberado por G2 na CLI) avalia o TESTE e recusa qualquer divergência
    do manifesto, inclusive a de cada execução (código, config, catálogo de regras, política e
    entradas); o exploratório explícito avalia a CALIBRACAO e só registra a divergência.

    Raises:
        ConfigInvalida: congelamento ou split ausente ou inválido.
        PortaoRecusado: confirmatório ou execução incompatível com o congelamento, ou sem G2.
    """
    diretorio = Path(config.runtime.dir_congelamentos)
    manifesto = carregar_freeze(diretorio, args.freeze)
    raiz = Path(config.runtime.raiz_saidas)
    entradas = _split_e_entradas(raiz)
    _conferir(manifesto, config, entradas)
    split = entradas[0]
    exigir_rodada_permitida(diretorio / REGISTRO, config.modo, args.freeze)
    confirmatorio = config.modo is ModoExecucao.CONFIRMATORIO
    particao = Particao.TESTE if confirmatorio else Particao.CALIBRACAO
    congelamento = ReferenciaCongelamento(args.freeze)
    if confirmatorio:
        g2 = exigir_portao(DIR_DECISOES, Portao.G2, freeze_id=args.freeze)
        congelamento = ReferenciaCongelamento(
            args.freeze, referencia_decisao(DIR_DECISOES, g2), manifesto=manifesto, config=config
        )
    relatorio = evaluate_runs(
        _runs(raiz / "runs", config.modo, args.freeze),
        (split.rotulos_por_particao or {})[particao],
        split,
        raiz / "avaliacao" / args.freeze,
        bootstrap=manifesto.bootstrap,
        congelamento=congelamento,
    )
    registrar_execucao(diretorio / REGISTRO, relatorio)
    logger.info("evaluate_registrado report=%s freeze=%s", relatorio.report_id, args.freeze)
    return int(ExitCode.OK)
