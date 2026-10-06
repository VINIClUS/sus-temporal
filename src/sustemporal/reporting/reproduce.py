"""Reprodução offline de um congelamento a partir dos originais locais (T14).

`sustemporal reproduce --freeze FREEZE_ID --offline` resolve o manifesto exato do congelamento e
refaz, em um diretório novo, o fluxo pequeno: ingestão dos originais do manifesto de aquisição até
onde o `ingest` original o leu (`reproduce_manifesto`), união e rótulos do SIA-PA, partições do
split, as três políticas sobre a partição avaliada e sobre o TESTE e a avaliação. Depois compara
com o congelado e com a rodada registrada por hash lógico, contagens e métricas
(`reproduce_comparacao`). Nada é lido da rede e nada do original é alterado. O que não se
consegue conferir (o `ingest` original, a posição que ele leu, a entrada original de cada
política, um original ausente) sai INCONCLUSIVO e a reprodução para antes de refazer.

Só a rodada exploratória é reproduzida: o confirmatório exige dados reais e o G2 humano, e a
conferência do manifesto compara a config inteira, inclusive os caminhos de `runtime` (pendência
T14-9). O que a reprodução relata fica em `<saida>/reproducao.json`; a saída é 0 só quando todo
item saiu igual (ou com bytes diferentes e hash lógico igual), e 5 quando algum diverge ou ficou
sem original para comparar.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import ModoExecucao, Particao
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro, RedeProibida
from sustemporal.evaluation.freeze import carregar_freeze, hash_protocolo
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs
from sustemporal.execucoes import raiz_execucoes
from sustemporal.ingest import cli as ingest_cli
from sustemporal.ingest.cli import configuracao_do_ingest
from sustemporal.reporting.reproduce_catalogos import item_da_origem, observacoes_dos_catalogos
from sustemporal.reporting.reproduce_comparacao import (
    Comparacao,
    Situacao,
    comparar_auxiliares,
    comparar_entradas_originais,
    comparar_execucoes,
    comparar_insumos,
    comparar_metricas,
    comparar_notas,
    comparar_originais,
    comparar_referencia,
    comparar_split,
    exigir_conferido,
    observacoes_do_ambiente,
    observacoes_do_ingest,
    resultado_geral,
)
from sustemporal.reporting.reproduce_etapas import (
    Derivado,
    competencias_da_janela,
    conferir_entradas,
    derivar_protocolo,
    estados_do_ingest,
    janela_dos_artefatos,
    validar_janela,
)
from sustemporal.reporting.reproduce_manifesto import (
    Resolucao,
    gravar_manifesto,
    observacoes_do_manifesto,
    resolver_manifesto,
)
from sustemporal.reporting.reproduce_original import Original, ler_original
from sustemporal.reporting.reproduce_politicas import politicas_congeladas
from sustemporal.reporting.reproduce_rede import sem_rede
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.entrada import ARQUIVO_ENTRADA, EntradaValidacao
from sustemporal.runtime_info import ambiente, versao_codigo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sustemporal.contracts import FreezeManifest, RunConfig
    from sustemporal.contracts.evaluation import EvaluationReport
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import MetodoId

__all__ = ["configurar_parser", "executar_reproduce", "reproduce"]

logger = logging.getLogger(__name__)

DIRETORIO_REPRODUCAO = "reproducao"
DIRETORIO_MANIFESTOS = "manifestos"
RELATORIO = "reproducao.json"
ITEM_MANIFESTO = "manifesto:aquisicao"
PARTICOES_REFEITAS = (Particao.CALIBRACAO, Particao.TESTE)


@dataclass(frozen=True)
class Refeito:
    derivado: Derivado
    avaliadas: Mapping[MetodoId, RunResult]
    teste: Mapping[MetodoId, RunResult]
    relatorio: EvaluationReport


@dataclass(frozen=True)
class Insumos:
    """Entradas originais conferidas, a política que refaz cada método e o que não se confere.

    `problemas` junta, por política congelada, a entrada original que falta, não abre ou foi
    alterada e a política que não se resolve ou não se confere.
    """

    conferidas: Mapping[str, EntradaValidacao]
    problemas: Mapping[str, str]
    politicas: Mapping[MetodoId, str | None]


@dataclass(frozen=True)
class Preparado:
    """O ingest refeito, as observações até aqui e a política que refaz cada método."""

    pasta: Path
    observacoes: list[str]
    politicas: Mapping[MetodoId, str | None]


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--saida", type=Path, default=None)


def _exigir_reprodutivel(config: RunConfig) -> str:
    if config.freeze_id is None:
        raise ConfigInvalida("reproduce_exige_freeze_id")
    if config.runtime.rede_permitida:
        raise RedeProibida("reproduce_com_rede_permitida")
    if config.modo is ModoExecucao.CONFIRMATORIO:
        raise ConfigInvalida(f"reproduce_confirmatorio_nao_suportado freeze={config.freeze_id}")
    return str(config.freeze_id)


def _exigir_destino_novo(out: Path) -> None:
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ConfigInvalida(f"reproduce_destino_nao_vazio caminho={out}")
    out.mkdir(parents=True, exist_ok=True)


def _config_em(config: RunConfig, out: Path) -> RunConfig:
    """A config com as saídas e o manifesto de aquisição (a cópia do congelamento) em `out`."""
    destinos = {"raiz_saidas": str(out), "raiz_manifestos": str(out / DIRETORIO_MANIFESTOS)}
    runtime = config.runtime.model_copy(update=destinos)
    return config.model_copy(update={"runtime": runtime})


def _da_janela(config: RunConfig, competencias: tuple[str, ...]) -> RunConfig:
    if config.piloto is None:
        raise ConfigInvalida("reproduce_exige_piloto")
    piloto = config.piloto.model_copy(update={"competencias_processamento": competencias})
    return config.model_copy(update={"piloto": piloto})


def _ingerir(config: RunConfig) -> Path:
    ingest_cli.executar_ingest(argparse.Namespace(comando="reproduce"), config)
    pastas = sorted(
        p for p in (Path(config.runtime.raiz_saidas) / "ingest").iterdir() if p.is_dir()
    )
    if not pastas:
        raise FalhaOperacionalErro("reproduce_ingest_sem_saida")
    return pastas[-1]


def _validar_particao(
    config: RunConfig,
    preparado: Preparado,
    derivado: Derivado,
    particao: Particao,
) -> Mapping[MetodoId, RunResult]:
    ref = (derivado.split.particoes or {})[particao]
    da_janela = _da_janela(config, competencias_da_janela(config, ref))
    destino = Path(config.runtime.raiz_saidas) / "janelas" / particao.value.lower()
    janela = janela_dos_artefatos(preparado.pasta, destino, ref.artifact_ids)
    return validar_janela(da_janela, janela, preparado.politicas)


def _avaliar(
    config: RunConfig,
    manifesto: FreezeManifest,
    derivado: Derivado,
    execucoes: Mapping[MetodoId, RunResult],
) -> EvaluationReport:
    split = derivado.split
    rotulos = (split.rotulos_por_particao or {})[Particao.CALIBRACAO]
    destino = Path(config.runtime.raiz_saidas) / "avaliacao" / manifesto.freeze_id
    return evaluate_runs(
        list(execucoes.values()),
        rotulos,
        split,
        destino,
        bootstrap=manifesto.bootstrap,
        congelamento=ReferenciaCongelamento(manifesto.freeze_id),
    )


def _derivar(config: RunConfig, manifesto: FreezeManifest, pasta: Path) -> Derivado:
    destino = Path(config.runtime.raiz_saidas) / "split"
    split = manifesto.split
    return derivar_protocolo(
        config, pasta, destino, spec=split.spec, inspecionados=split.artefatos_inspecionados
    )


def _particoes_vazias(derivado: Derivado) -> list[Particao]:
    refs = derivado.split.particoes or {}
    return [particao for particao in PARTICOES_REFEITAS if not refs[particao].artifact_ids]


def _itens_sem_particao(
    manifesto: FreezeManifest, derivado: Derivado, vazias: list[Particao]
) -> list[Comparacao]:
    """Conjuntos e split refeitos e, por partição sem artefatos, o item inconclusivo dela."""
    sem_artefatos = [
        Comparacao(f"particao:{p.value}", Situacao.INCONCLUSIVO, None, None, "particao_vazia")
        for p in vazias
    ]
    return [
        *_comparar_conjuntos(manifesto, derivado),
        *comparar_split(manifesto.split, derivado.split),
        *sem_artefatos,
    ]


def _refazer(
    config: RunConfig, manifesto: FreezeManifest, preparado: Preparado, derivado: Derivado
) -> Refeito:
    avaliadas = _validar_particao(config, preparado, derivado, Particao.CALIBRACAO)
    teste = _validar_particao(config, preparado, derivado, Particao.TESTE)
    relatorio = _avaliar(config, manifesto, derivado, avaliadas)
    return Refeito(derivado, avaliadas, teste, relatorio)


def _comparar_conjuntos(manifesto: FreezeManifest, derivado: Derivado) -> list[Comparacao]:
    refeitos = {"sia_pa.v1": derivado.uniao, "sia_pa_rotulos.v1": derivado.rotulos}
    itens = []
    for esperada in manifesto.datasets:
        obtida = refeitos.get(esperada.schema_id)
        item = f"conjunto:{esperada.schema_id}"
        if obtida is None:
            itens.append(Comparacao(item, Situacao.INCONCLUSIVO, None, None, "sem_etapa"))
        else:
            itens.append(comparar_referencia(item, esperada, obtida))
    return itens


def _comparar_insumos(
    config: RunConfig, manifesto: FreezeManifest, teste: Mapping[MetodoId, RunResult]
) -> list[Comparacao]:
    itens = []
    for run in teste.values():
        caminho = raiz_execucoes(config) / run.run_id / ARQUIVO_ENTRADA
        entrada = EntradaValidacao.model_validate_json(caminho.read_text(encoding="utf-8"))
        congeladas = (manifesto.entradas_validacao or {}).get(run.politica_id or "")
        itens.append(comparar_insumos(f"insumos:{run.politica_id}", congeladas, entrada))
    return itens


def _saidas_por_metodo(
    execucoes: Mapping[MetodoId, RunResult],
) -> dict[str, dict[str, DatasetRef]]:
    return {
        metodo.value: {saida.schema_id: saida for saida in run.saidas}
        for metodo, run in execucoes.items()
    }


def _observacoes(
    config: RunConfig, manifesto: FreezeManifest, regras: Sequence[RuleSpec]
) -> list[str]:
    do_ambiente = observacoes_do_ambiente(
        config_igual=hash_protocolo(config) == manifesto.config_hash,
        codigo=versao_codigo(Path.cwd()),
        congelado=manifesto.codigo,
        pacotes=ambiente(Path.cwd()).pacotes,
        congelados=manifesto.ambiente.pacotes,
    )
    catalogos = observacoes_dos_catalogos(
        manifesto.catalogos_sha256, config.catalogos, manifesto.catalogo_regras_sha256, regras
    )
    return [*do_ambiente, *catalogos]


def _regras() -> list[RuleSpec]:
    try:
        return carregar_regras()
    except CatalogoInvalido as erro:
        raise ConfigInvalida(str(erro)) from erro


def _insumos_originais(
    config: RunConfig, manifesto: FreezeManifest, original: Original, regras: Sequence[RuleSpec]
) -> Insumos:
    """A entrada original de cada política congelada e a política com que refazer cada método."""
    pasta = Path(config.runtime.raiz_saidas) / "split" / "insumos"
    congeladas = manifesto.entradas_validacao or {}
    entradas = conferir_entradas(pasta, congeladas)
    registradas = {metodo: run.politica_id for metodo, run in original.execucoes.items()}
    politicas = politicas_congeladas(entradas.conferidas, congeladas, registradas, regras)
    problemas = {**entradas.problemas, **politicas.problemas}
    return Insumos(entradas.conferidas, problemas, politicas.por_metodo)


def _indisponiveis(
    manifesto: FreezeManifest, insumos: Insumos, estados: Mapping[str, str]
) -> list[Comparacao]:
    """Itens inconclusivos: original que o ingest refeito não trouxe e insumo que não confere."""
    return [
        *comparar_originais(manifesto.datasets, estados),
        *comparar_entradas_originais(insumos.problemas),
        *comparar_auxiliares(insumos.conferidas, estados),
    ]


def _item_do_manifesto(resolucao: Resolucao) -> list[Comparacao]:
    """O item da posição do manifesto de aquisição que não se sabe (vazio se se sabe)."""
    if not resolucao.motivo:
        return []
    return [Comparacao(ITEM_MANIFESTO, Situacao.INCONCLUSIVO, None, None, resolucao.motivo)]


def _parar_se_inconclusivo(
    config: RunConfig, out: Path, itens: list[Comparacao], observacoes: list[str]
) -> None:
    """Grava o `reproducao.json` e falha, antes de refazer, se há item sem conferência."""
    if itens:
        _registrar(config, out, None, itens, observacoes)
        exigir_conferido(itens)


def _ingerir_o_original(
    config: RunConfig,
    em_out: RunConfig,
    out: Path,
    manifesto: FreezeManifest,
    original: Original,
) -> Preparado:
    """O ingest refeito sobre o manifesto que o original leu e as observações até aqui.

    Para (`_parar_se_inconclusivo`) sem a posição do manifesto, sem original, ou com insumo
    original (entrada ou política) que não se confere.
    """
    regras = _regras()
    insumos = _insumos_originais(config, manifesto, original, regras)
    resolucao = resolver_manifesto(
        Path(config.runtime.raiz_saidas) / "ingest",
        Path(config.runtime.raiz_manifestos),
        manifesto.datasets,
        configuracao_do_ingest(config),
    )
    do_ambiente = [*original.observacoes, *_observacoes(config, manifesto, regras)]
    origem = item_da_origem(config.origem_dados, manifesto.datasets)
    antes = [*_item_do_manifesto(resolucao), *origem]
    if antes:
        itens = [*antes, *comparar_entradas_originais(insumos.problemas)]
        _parar_se_inconclusivo(config, out, itens, do_ambiente)
    gravar_manifesto(
        Path(config.runtime.raiz_manifestos), Path(em_out.runtime.raiz_manifestos), resolucao
    )
    pasta = _ingerir(em_out)
    estados = estados_do_ingest(pasta)
    observacoes = [
        *observacoes_do_manifesto(resolucao),
        *observacoes_do_ingest(estados),
        *do_ambiente,
    ]
    _parar_se_inconclusivo(config, out, _indisponiveis(manifesto, insumos, estados), observacoes)
    return Preparado(pasta, observacoes, insumos.politicas)


def _parar_se_particao_vazia(
    config: RunConfig,
    out: Path,
    manifesto: FreezeManifest,
    derivado: Derivado,
    observacoes: list[str],
) -> None:
    if vazias := _particoes_vazias(derivado):
        itens = _itens_sem_particao(manifesto, derivado, vazias)
        avisos = [f"particao_sem_artefatos particao={p.value}" for p in vazias]
        _parar_se_inconclusivo(config, out, itens, [*observacoes, *avisos])


def _comparar(
    config: RunConfig, manifesto: FreezeManifest, original: Original, refeito: Refeito
) -> list[Comparacao]:
    antigo = original.relatorio
    return [
        *_comparar_conjuntos(manifesto, refeito.derivado),
        *comparar_split(manifesto.split, refeito.derivado.split),
        *_comparar_insumos(config, manifesto, refeito.teste),
        *comparar_execucoes(
            _saidas_por_metodo(original.execucoes), _saidas_por_metodo(refeito.avaliadas)
        ),
        comparar_metricas(
            "metricas", antigo.metricas if antigo else None, refeito.relatorio.metricas
        ),
        comparar_notas("notas", antigo.notas if antigo else None, refeito.relatorio.notas),
    ]


def _registrar(
    config: RunConfig,
    out: Path,
    relatorio: EvaluationReport | None,
    itens: list[Comparacao],
    observacoes: list[str],
) -> None:
    origem = config.origem_dados
    conteudo = {
        "freeze_id": config.freeze_id,
        "modo": config.modo.value,
        "origem_dados": origem.value if origem else None,
        "resultado": resultado_geral(itens).value,
        "relatorio_refeito": relatorio.report_id if relatorio else None,
        "observacoes": observacoes,
        "comparacoes": [item.como_dict() for item in itens],
    }
    (out / RELATORIO).write_text(
        json.dumps(conteudo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def reproduce(config: RunConfig, out: Path) -> EvaluationReport:
    """Refaz o fluxo do congelamento em `out` e o compara com o congelado e o registrado.

    Raises:
        ConfigInvalida: config sem `freeze_id`, confirmatória, `out` já usado ou entradas locais
            ausentes ou inválidas.
        RedeProibida: config com `rede_permitida` ou qualquer tentativa de conexão.
        FalhaOperacionalErro: conteúdo refeito diferente do congelado ou do original, saída que
            só uma das execuções emitiu, ou item sem original para comparar (artefato do SIA-PA ou
            dos auxiliares congelados, CNES e SIGTAP, que o ingest não normalizou, ou entrada
            original da política, em `split/insumos`, ausente, ilegível ou alterada); o
            `reproducao.json` já está gravado em `out`.
    """
    freeze_id = _exigir_reprodutivel(config)
    manifesto = carregar_freeze(Path(config.runtime.dir_congelamentos), freeze_id)
    _exigir_destino_novo(out)
    em_out = _config_em(config, out)
    with sem_rede():
        original = ler_original(config, freeze_id)
        preparado = _ingerir_o_original(config, em_out, out, manifesto, original)
        derivado = _derivar(em_out, manifesto, preparado.pasta)
        _parar_se_particao_vazia(config, out, manifesto, derivado, preparado.observacoes)
        refeito = _refazer(em_out, manifesto, preparado, derivado)
        itens = _comparar(em_out, manifesto, original, refeito)
        _registrar(config, out, refeito.relatorio, itens, preparado.observacoes)
    exigir_conferido(itens)
    logger.info(
        "reproducao_concluida freeze=%s resultado=%s", freeze_id, resultado_geral(itens).value
    )
    return refeito.relatorio


def executar_reproduce(args: argparse.Namespace, config: RunConfig) -> int:
    """`sustemporal reproduce --freeze ID --offline [--saida DIR]`.

    Raises:
        ConfigInvalida: sem `--offline`, freeze diferente do da config ou destino já usado.
    """
    if not args.offline:
        raise ConfigInvalida("reproduce_exige_offline")
    freeze_id = str(args.freeze)
    if config.freeze_id not in (None, freeze_id):
        raise ConfigInvalida(
            f"reproduce_freeze_diverge_da_config freeze={freeze_id} config={config.freeze_id}"
        )
    padrao = Path(config.runtime.raiz_saidas) / DIRETORIO_REPRODUCAO / freeze_id
    reproduce(config.model_copy(update={"freeze_id": freeze_id}), Path(args.saida or padrao))
    return int(ExitCode.OK)
