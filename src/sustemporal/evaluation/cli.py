"""Comandos `sustemporal freeze` e `sustemporal evaluate --freeze FREEZE_ID` (T11).

Entradas por convenção, sempre resolvidas por id exato e nunca por "latest":
`<raiz_saidas>/split/<split_id>.json` (único) com `<split_id>.entradas.json` (dataset e rótulos
completos), `<raiz_saidas>/split/insumos/<politica_id>.json` (a `entrada_validacao.json` de cada
política sobre o TESTE, que o `freeze` congela), execuções em `raiz_execucoes(config)` =
`<raiz_saidas>/runs/<run_id>/` e congelamentos em `<dir_congelamentos>/<freeze_id>.json`. A
execução é o `run_result.json` que o motor de regras grava por padrão ali (`validate`) ou o
`run.json` do baseline, nunca os dois no mesmo diretório. O registro append-only fica em
`<dir_congelamentos>/registro_execucoes.jsonl`.

Depois da abertura do teste, a segunda rodada confirmatória só entra como correção declarada:
`evaluate --corrige <report_id> --declaracao <texto>`, os dois juntos, com alvo confirmatório
do mesmo congelamento.
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
from sustemporal.evaluation.freeze import Protocolo, carregar_freeze, congelar, referencia_decisao
from sustemporal.evaluation.freeze_conferencia import (
    EstadoAtual,
    entradas_do_congelamento,
    verificar_congelamento_completo,
)
from sustemporal.evaluation.freeze_registro import exigir_rodada_permitida, registrar_execucao
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs
from sustemporal.evaluation.split import SUFIXO_ENTRADAS
from sustemporal.execucoes import raiz_execucoes
from sustemporal.gates import DIR_DECISOES, exigir_portao
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.entrada import EntradaValidacao
from sustemporal.rules.insumos import politica_padrao
from sustemporal.runtime_info import ambiente, versao_codigo
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import FreezeManifest, RuleSpec, RunConfig
    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = [
    "REGISTRO",
    "ambiente",
    "configurar_parser",
    "executar_evaluate",
    "executar_freeze",
    "versao_codigo",
]

logger = logging.getLogger(__name__)

REGISTRO = "registro_execucoes.jsonl"
_ARQUIVOS_DA_EXECUCAO = ("run.json", "run_result.json")


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


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    if parser.prog.endswith("evaluate"):
        parser.add_argument("--corrige", metavar="REPORT_ID", default=None)
        parser.add_argument("--declaracao", metavar="TEXTO", default=None)


def _regras_do_catalogo() -> list[RuleSpec]:
    try:
        return carregar_regras()
    except (OSError, ValueError) as erro:
        raise ConfigInvalida(f"freeze_catalogo_de_regras_invalido erro={erro}") from erro


def _politicas_do_catalogo(regras: list[RuleSpec]) -> list[PoliticaTemporal]:
    """Políticas de `catalog/policies` e as padrão dos baselines, como `validate` as resolve."""
    arquivos = sorted(DIRETORIO_POLITICAS.glob("*.yaml"))
    catalogo = [carregar_politica(arquivo.stem) for arquivo in arquivos]
    padrao = [politica_padrao(metodo, regras) for metodo in (MetodoId.B_ATEND, MetodoId.B_PROC)]
    return [*catalogo, *padrao]


def _insumos_do_split(raiz: Path) -> dict[str, EntradaValidacao]:
    """`<raiz_saidas>/split/insumos/<politica_id>.json`: a `entrada_validacao.json` da política."""
    pasta = raiz / "split" / "insumos"
    arquivos = sorted(pasta.glob("*.json"))
    if not arquivos:
        raise ConfigInvalida(f"freeze_sem_insumos_das_execucoes pasta={pasta}")
    insumos = {}
    for arquivo in arquivos:
        try:
            insumos[arquivo.stem] = EntradaValidacao.model_validate_json(
                arquivo.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as erro:
            raise ConfigInvalida(f"freeze_insumos_ilegiveis arquivo={arquivo}") from erro
    return insumos


def executar_freeze(args: argparse.Namespace, config: RunConfig) -> int:
    """Congela o protocolo a partir do split e das entradas em `<raiz_saidas>/split`.

    O manifesto registra também a identidade do catálogo de regras e das políticas do catálogo e,
    por política, os insumos não populacionais lidos de `<raiz_saidas>/split/insumos`.

    Raises:
        ConfigInvalida: sem catálogos na config, split ou insumos ausentes ou ilegíveis, catálogo
            de regras ou políticas inválido, ou protocolo inválido.
        PortaoRecusado: G0 ausente ou que não libera.
    """
    if not config.catalogos:
        raise ConfigInvalida("freeze_sem_catalogos")
    raiz = Path(config.runtime.raiz_saidas)
    split, dataset, rotulos = _split_e_entradas(raiz)
    regras = _regras_do_catalogo()
    insumos = _insumos_do_split(raiz)
    protocolo = Protocolo(
        config=config,
        split=split,
        features=FEATURES_PADRAO,
        dataset=dataset,
        rotulos=rotulos,
        catalogos={nome: Path(caminho) for nome, caminho in config.catalogos.items()},
        regras=regras,
        politicas=_politicas_do_catalogo(regras),
        insumos=insumos,
    )
    destino = Path(config.runtime.dir_congelamentos)
    manifesto = congelar(protocolo, destino, codigo=versao_codigo(Path.cwd()))
    logger.info("freeze_emitido freeze=%s comando=%s", manifesto.freeze_id, args.comando)
    return int(ExitCode.OK)


def _arquivo_da_execucao(diretorio: Path) -> Path | None:
    existentes = [
        diretorio / nome for nome in _ARQUIVOS_DA_EXECUCAO if (diretorio / nome).is_file()
    ]
    if len(existentes) > 1:
        nomes = ",".join(arquivo.name for arquivo in existentes)
        raise ConfigInvalida(f"execucao_ambigua pasta={diretorio} arquivos={nomes}")
    return existentes[0] if existentes else None


def _execucoes(pasta: Path) -> list[RunResult]:
    """Execuções legíveis de `pasta`; a ilegível é ignorada e registrada, e as conferências
    recusam se faltar uma necessária."""
    execucoes = []
    for diretorio in sorted(pasta.glob("*")):
        caminho = _arquivo_da_execucao(diretorio)
        if caminho is None:
            continue
        try:
            execucoes.append(RunResult.model_validate_json(caminho.read_text(encoding="utf-8")))
        except (OSError, ValueError) as erro:
            motivo = type(erro).__name__
            logger.warning("evaluate_execucao_ilegivel run=%s motivo=%s", diretorio.name, motivo)
    return execucoes


def _do_protocolo(run: RunResult, config: RunConfig, manifesto: FreezeManifest) -> bool:
    """Confirmatório: execução do mesmo congelamento. Exploratório: mesma config e entradas dele."""
    if run.modo is not config.modo:
        return False
    if config.modo is ModoExecucao.CONFIRMATORIO:
        return run.freeze_id == manifesto.freeze_id
    return run.config_hash == config.config_hash and entradas_do_congelamento(manifesto, run)


def _runs(pasta: Path, config: RunConfig, manifesto: FreezeManifest) -> list[RunResult]:
    selecionadas = []
    for run in _execucoes(pasta):
        if _do_protocolo(run, config, manifesto):
            selecionadas.append(run)
        else:
            logger.info("evaluate_execucao_ignorada run=%s modo=%s", run.run_id, run.modo.value)
    if not selecionadas:
        raise ConfigInvalida(f"avaliacao_sem_execucoes pasta={pasta} modo={config.modo.value}")
    return selecionadas


def _estado_atual(
    config: RunConfig, entradas: tuple[SplitManifest, DatasetRef, DatasetRef]
) -> EstadoAtual:
    """O que o avaliador observa agora: a config, o split, o código, o ambiente e o catálogo."""
    split, dataset, rotulos = entradas
    regras = _regras_do_catalogo()
    return EstadoAtual(
        config=config,
        split=split,
        features=FEATURES_PADRAO,
        datasets=[dataset, rotulos],
        codigo=versao_codigo(Path.cwd()),
        ambiente=ambiente(Path.cwd()),
        regras=regras,
        politicas=_politicas_do_catalogo(regras),
    )


def _conferir(manifesto: FreezeManifest, estado: EstadoAtual) -> None:
    try:
        verificar_congelamento_completo(manifesto, estado)
    except PortaoRecusado as erro:
        if estado.config.modo is ModoExecucao.CONFIRMATORIO:
            raise
        logger.warning("evaluate_exploratorio_divergente_do_freeze erro=%s", erro)


def _correcao(args: argparse.Namespace, config: RunConfig) -> tuple[str | None, str | None]:
    corrige = getattr(args, "corrige", None)
    declaracao = getattr(args, "declaracao", None)
    if (corrige is None) != (declaracao is None):
        raise ConfigInvalida("correcao_exige_corrige_e_declaracao")
    if corrige is not None and config.modo is not ModoExecucao.CONFIRMATORIO:
        raise ConfigInvalida("correcao_so_no_confirmatorio")
    return corrige, declaracao


def _exigir_rodada(
    registro: Path, config: RunConfig, freeze: str, correcao: tuple[str | None, str | None]
) -> None:
    corrige, declaracao = correcao
    try:
        exigir_rodada_permitida(
            registro, config.modo, freeze, corrige=corrige, declaracao=declaracao
        )
    except ValueError as erro:
        raise ConfigInvalida(f"correcao_invalida erro={erro}") from erro


def executar_evaluate(args: argparse.Namespace, config: RunConfig) -> int:
    """Avalia as execuções do congelamento e acrescenta o resultado ao registro.

    O confirmatório (já liberado por G2 na CLI) avalia o TESTE e recusa qualquer divergência
    do manifesto contra o estado atual (código, ambiente, catálogos, split por inteiro, ...) e
    contra cada execução (`freeze_conferencia`); o exploratório explícito avalia a CALIBRACAO e só
    registra a divergência. A segunda rodada confirmatória exige `--corrige` e `--declaracao`.
    As execuções vêm de `runs/`: no confirmatório, as do congelamento; no exploratório, só as da
    mesma `config_hash` cujas entradas são do split do congelamento, e as demais são ignoradas
    com `evaluate_execucao_ignorada`; o manifesto ilegível, com `evaluate_execucao_ilegivel`.

    Raises:
        ConfigInvalida: congelamento ou split ausente ou inválido, correção incompleta, inválida
            ou pedida fora do confirmatório, ou nenhuma execução do protocolo em `runs/`.
        PortaoRecusado: confirmatório ou execução incompatível com o congelamento, sem G2 ou
            segunda rodada sem correção declarada.
    """
    correcao = _correcao(args, config)
    diretorio = Path(config.runtime.dir_congelamentos)
    manifesto = carregar_freeze(diretorio, args.freeze)
    raiz = Path(config.runtime.raiz_saidas)
    entradas = _split_e_entradas(raiz)
    estado = _estado_atual(config, entradas)
    _conferir(manifesto, estado)
    split = entradas[0]
    _exigir_rodada(diretorio / REGISTRO, config, args.freeze, correcao)
    confirmatorio = config.modo is ModoExecucao.CONFIRMATORIO
    particao = Particao.TESTE if confirmatorio else Particao.CALIBRACAO
    congelamento = ReferenciaCongelamento(args.freeze)
    if confirmatorio:
        g2 = exigir_portao(DIR_DECISOES, Portao.G2, freeze_id=args.freeze)
        congelamento = ReferenciaCongelamento(
            args.freeze, referencia_decisao(DIR_DECISOES, g2), manifesto=manifesto, estado=estado
        )
    relatorio = evaluate_runs(
        _runs(raiz_execucoes(config), config, manifesto),
        (split.rotulos_por_particao or {})[particao],
        split,
        raiz / "avaliacao" / args.freeze,
        bootstrap=manifesto.bootstrap,
        congelamento=congelamento,
    )
    corrige, declaracao = correcao
    registrar_execucao(diretorio / REGISTRO, relatorio, corrige=corrige, declaracao=declaracao)
    logger.info("evaluate_registrado report=%s freeze=%s", relatorio.report_id, args.freeze)
    return int(ExitCode.OK)
