"""Reprodução offline de um congelamento a partir dos originais locais (T14).

`sustemporal reproduce --freeze FREEZE_ID --offline` resolve o manifesto exato do congelamento e
refaz, em um diretório novo, o fluxo pequeno: ingestão dos originais do manifesto de aquisição,
união e rótulos do SIA-PA, partições do split, as três políticas sobre a partição avaliada e sobre
o TESTE e a avaliação. Depois compara com o congelado e com a rodada registrada por hash lógico,
contagens e métricas (`reproduce_comparacao`). Nada é lido da rede e nada do original é alterado.

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

from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.contracts.experiment import ModoExecucao, Particao
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro, RedeProibida
from sustemporal.evaluation.cli import REGISTRO
from sustemporal.evaluation.freeze import carregar_freeze, hash_protocolo
from sustemporal.evaluation.freeze_registro import ler_registro
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs
from sustemporal.execucoes import ExecucaoNaoResolvida, ler_execucao, raiz_execucoes
from sustemporal.ingest import cli as ingest_cli
from sustemporal.reporting.reproduce_comparacao import (
    Comparacao,
    Situacao,
    comparar_insumos,
    comparar_metricas,
    comparar_notas,
    comparar_originais,
    comparar_referencia,
    comparar_saida,
    comparar_split,
    exigir_conferido,
    observacoes_do_ambiente,
    resultado_geral,
    rodada_registrada,
)
from sustemporal.reporting.reproduce_etapas import (
    Derivado,
    competencias_da_particao,
    derivar_protocolo,
    estados_do_ingest,
    janela_do_ingest,
    validar_janela,
)
from sustemporal.reporting.reproduce_rede import sem_rede
from sustemporal.rules.entrada import ARQUIVO_ENTRADA, EntradaValidacao
from sustemporal.runtime_info import ambiente, versao_codigo

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts import FreezeManifest, RunConfig
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.temporal import MetodoId

__all__ = ["configurar_parser", "executar_reproduce", "reproduce"]

logger = logging.getLogger(__name__)

DIRETORIO_REPRODUCAO = "reproducao"
RELATORIO = "reproducao.json"


@dataclass(frozen=True)
class Original:
    """Rodada registrada do congelamento: o relatório e as execuções, se ainda existem."""

    relatorio: EvaluationReport | None
    execucoes: Mapping[MetodoId, RunResult]


@dataclass(frozen=True)
class Refeito:
    derivado: Derivado
    avaliadas: Mapping[MetodoId, RunResult]
    teste: Mapping[MetodoId, RunResult]
    relatorio: EvaluationReport


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
    runtime = config.runtime.model_copy(update={"raiz_saidas": str(out)})
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
    config: RunConfig, pasta: Path, derivado: Derivado, particao: Particao
) -> Mapping[MetodoId, RunResult]:
    refs = derivado.split.particoes or {}
    competencias = competencias_da_particao(refs[particao])
    da_janela = _da_janela(config, competencias)
    destino = Path(config.runtime.raiz_saidas) / "janelas" / particao.value.lower()
    janela = janela_do_ingest(da_janela, pasta, destino, competencias)
    return validar_janela(da_janela, janela)


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


def _refazer(config: RunConfig, manifesto: FreezeManifest, pasta: Path) -> Refeito:
    destino = Path(config.runtime.raiz_saidas) / "split"
    derivado = derivar_protocolo(config, pasta, destino, spec=manifesto.split.spec)
    avaliadas = _validar_particao(config, pasta, derivado, Particao.CALIBRACAO)
    teste = _validar_particao(config, pasta, derivado, Particao.TESTE)
    relatorio = _avaliar(config, manifesto, derivado, avaliadas)
    return Refeito(derivado, avaliadas, teste, relatorio)


def _original(config: RunConfig, freeze_id: str) -> Original:
    registro = ler_registro(Path(config.runtime.dir_congelamentos) / REGISTRO)
    ultima = rodada_registrada(registro, freeze_id, config.modo.value)
    if ultima is None:
        return Original(None, {})
    caminho = (
        Path(config.runtime.raiz_saidas) / "avaliacao" / freeze_id / f"{ultima['report_id']}.json"
    )
    relatorio = _ler_relatorio(caminho)
    execucoes = {}
    for run_id in ultima["runs"]:
        try:
            run = ler_execucao(raiz_execucoes(config), run_id)
        except ExecucaoNaoResolvida:
            continue
        if run.metodo is not None:
            execucoes[run.metodo] = run
    return Original(relatorio, execucoes)


def _ler_relatorio(caminho: Path) -> EvaluationReport | None:
    if not caminho.is_file():
        return None
    return EvaluationReport.model_validate_json(caminho.read_text(encoding="utf-8"))


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


def _comparar_execucoes(
    original: Original, avaliadas: Mapping[MetodoId, RunResult]
) -> list[Comparacao]:
    itens = []
    for metodo, run in avaliadas.items():
        antiga = original.execucoes.get(metodo)
        antigas = {s.schema_id: s for s in antiga.saidas} if antiga is not None else {}
        for saida in run.saidas:
            item = f"saida:{metodo.value}:{saida.schema_id}"
            itens.append(comparar_saida(item, antigas.get(saida.schema_id), saida))
    return itens


def _observacoes(config: RunConfig, manifesto: FreezeManifest) -> list[str]:
    return observacoes_do_ambiente(
        config_igual=hash_protocolo(config) == manifesto.config_hash,
        codigo=versao_codigo(Path.cwd()),
        congelado=manifesto.codigo,
        pacotes=ambiente(Path.cwd()).pacotes,
        congelados=manifesto.ambiente.pacotes,
    )


def _comparar(
    config: RunConfig, manifesto: FreezeManifest, original: Original, refeito: Refeito
) -> list[Comparacao]:
    antigo = original.relatorio
    return [
        *_comparar_conjuntos(manifesto, refeito.derivado),
        *comparar_split(manifesto.split, refeito.derivado.split),
        *_comparar_insumos(config, manifesto, refeito.teste),
        *_comparar_execucoes(original, refeito.avaliadas),
        comparar_metricas(
            "metricas", antigo.metricas if antigo else None, refeito.relatorio.metricas
        ),
        comparar_notas("notas", antigo.notas if antigo else None, refeito.relatorio.notas),
    ]


def _registrar(
    config: RunConfig,
    out: Path,
    manifesto: FreezeManifest,
    relatorio: EvaluationReport | None,
    itens: list[Comparacao],
) -> None:
    origem = config.origem_dados
    conteudo = {
        "freeze_id": manifesto.freeze_id,
        "modo": config.modo.value,
        "origem_dados": origem.value if origem else None,
        "resultado": resultado_geral(itens).value,
        "relatorio_refeito": relatorio.report_id if relatorio else None,
        "observacoes": _observacoes(config, manifesto),
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
        FalhaOperacionalErro: conteúdo refeito diferente do congelado ou do original, ou item
            sem original para comparar (inclusive artefato do SIA-PA que o ingest não normalizou);
            o `reproducao.json` já está gravado em `out`.
    """
    freeze_id = _exigir_reprodutivel(config)
    manifesto = carregar_freeze(Path(config.runtime.dir_congelamentos), freeze_id)
    _exigir_destino_novo(out)
    em_out = _config_em(config, out)
    with sem_rede():
        original = _original(config, freeze_id)
        pasta = _ingerir(em_out)
        indisponiveis = comparar_originais(manifesto.datasets, estados_do_ingest(pasta))
        if indisponiveis:
            _registrar(config, out, manifesto, None, indisponiveis)
            exigir_conferido(indisponiveis)
        refeito = _refazer(em_out, manifesto, pasta)
        itens = _comparar(em_out, manifesto, original, refeito)
        _registrar(config, out, manifesto, refeito.relatorio, itens)
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
