"""Interface de linha de comando `sustemporal` com despacho preguiçoso por comando."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from sustemporal.config import load_config
from sustemporal.contracts.base import Identificador, OrigemDados
from sustemporal.contracts.experiment import FreezeId, ModoExecucao, Portao
from sustemporal.errors import ConfigInvalida, ErroSustemporal, ExitCode, PortaoRecusado
from sustemporal.gates import DIR_DECISOES, exigir_confirmatorio_valido, exigir_portao
from sustemporal.log import configurar_log

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

    from sustemporal.contracts.config import RunConfig

    Manipulador = Callable[[argparse.Namespace, RunConfig], int]

__all__ = ["CONFIG_PADRAO", "MANIPULADORES", "construir_parser", "load_config", "main"]

logger = logging.getLogger(__name__)

CONFIG_PADRAO = Path("config/runtime.yaml")

MANIPULADORES: dict[str, str] = {
    "acquire": "sustemporal.acquisition.cli:executar_acquire",
    "watch": "sustemporal.acquisition.cli:executar_watch",
    "ingest": "sustemporal.ingest.cli:executar_ingest",
    "pilot-report": "sustemporal.reporting.cli:executar_pilot_report",
    "validate": "sustemporal.rules.cli:executar_validate",
    "explain": "sustemporal.explanation.cli:executar_explain",
    "counterfactual": "sustemporal.explanation.counterfactual_cli:executar_counterfactual",
    "freeze": "sustemporal.evaluation.cli:executar_freeze",
    "evaluate": "sustemporal.evaluation.cli:executar_evaluate",
    "annotation-export": "sustemporal.evaluation.annotation_cli:executar_annotation_export",
    "reproduce": "sustemporal.reporting.reproduce:executar_reproduce",
}

POLITICAS = ("documented", "atendimento", "processamento")
_COM_CONFIG_OBRIGATORIA = ("acquire", "watch", "ingest", "pilot-report", "validate", "freeze")
_IDENTIFICADOR: TypeAdapter[str] = TypeAdapter(Identificador)
_FREEZE_ID: TypeAdapter[str] = TypeAdapter(FreezeId)


def _validador(adaptador: TypeAdapter[str], nome: str) -> Callable[[str], str]:
    def validar(valor: str) -> str:
        try:
            return adaptador.validate_python(valor)
        except ValidationError as erro:
            raise argparse.ArgumentTypeError(f"{nome}_invalido valor={valor!r}") from erro

    return validar


def _configurar_comando(nome: str, sub: argparse.ArgumentParser) -> None:
    obrigatoria = nome in _COM_CONFIG_OBRIGATORIA
    padrao = None if obrigatoria else CONFIG_PADRAO
    sub.add_argument("--config", type=Path, required=obrigatoria, default=padrao)
    if nome == "validate":
        sub.add_argument("--policy", required=True, choices=POLITICAS)
    if nome in {"explain", "counterfactual"}:
        sub.add_argument("--run", required=True, type=_validador(_IDENTIFICADOR, "run"))
        sub.add_argument("--row", required=True)
    if nome in {"evaluate", "annotation-export", "reproduce"}:
        sub.add_argument("--freeze", required=True, type=_validador(_FREEZE_ID, "freeze_id"))
    if nome == "evaluate":
        sub.add_argument("--exploratory", action="store_true")
    if nome == "reproduce":
        sub.add_argument("--offline", action="store_true")


def construir_parser() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="sustemporal",
        description="Validação temporal e explicável de dados administrativos do SUS.",
    )
    parser.add_argument("--nivel-log", default="INFO", choices=("DEBUG", "INFO", "WARNING"))
    subparsers = parser.add_subparsers(dest="comando", required=True)
    comandos: dict[str, argparse.ArgumentParser] = {}
    for nome in MANIPULADORES:
        comandos[nome] = subparsers.add_parser(nome)
        _configurar_comando(nome, comandos[nome])
    return parser, comandos


def _importar(nome_modulo: str) -> ModuleType | None:
    try:
        return importlib.import_module(nome_modulo)
    except ModuleNotFoundError as erro:
        ausente = erro.name
        if ausente and (nome_modulo == ausente or nome_modulo.startswith(f"{ausente}.")):
            return None
        raise


def _resolver(comando: str) -> tuple[ModuleType | None, Manipulador | None]:
    nome_modulo, nome_funcao = MANIPULADORES[comando].split(":")
    modulo = _importar(nome_modulo)
    funcao = getattr(modulo, nome_funcao, None) if modulo is not None else None
    return modulo, funcao if callable(funcao) else None


def _exigir_portoes(args: argparse.Namespace, config: RunConfig) -> None:
    if args.comando == "freeze":
        exigir_portao(DIR_DECISOES, Portao.G0)
    if args.comando == "evaluate":
        _exigir_portao_da_avaliacao(args, config)


def _exigir_portao_da_avaliacao(args: argparse.Namespace, config: RunConfig) -> None:
    confirmatoria = config.modo is ModoExecucao.CONFIRMATORIO
    if args.exploratory:
        if confirmatoria:
            raise PortaoRecusado("evaluate_exploratory_com_config_confirmatoria")
        return
    if not confirmatoria:
        raise PortaoRecusado("evaluate_sem_exploratory_exige_config_confirmatoria")
    if args.freeze != config.freeze_id:
        raise PortaoRecusado(
            f"evaluate_freeze_diverge_da_config freeze={args.freeze} config={config.freeze_id}"
        )
    exigir_confirmatorio_valido(config, config.origem_dados or OrigemDados.SINTETICO)


def _levantado_pelo_projeto(erro: NotImplementedError, modulo_manipulador: str) -> bool:
    """Stub só se a exceção nasceu no mesmo pacote raiz do manipulador, não numa biblioteca."""
    quadro = erro.__traceback__
    while quadro is not None and quadro.tb_next is not None:
        quadro = quadro.tb_next
    if quadro is None:
        return False
    raiz = modulo_manipulador.partition(".")[0]
    origem = str(quadro.tb_frame.f_globals.get("__name__", ""))
    return origem == raiz or origem.startswith(f"{raiz}.")


def _executar(funcao: Manipulador, args: argparse.Namespace, config: RunConfig) -> int:
    try:
        return int(funcao(args, config))
    except NotImplementedError as erro:
        if not _levantado_pelo_projeto(erro, funcao.__module__):
            raise
        logger.error("comando_nao_implementado comando=%s", args.comando)
        return ExitCode.NAO_IMPLEMENTADO
    except ErroSustemporal as erro:
        logger.error("comando_falhou comando=%s erro=%s", args.comando, erro)
        return int(erro.codigo_saida)


def main(argv: Sequence[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    parser, comandos = construir_parser()
    preliminar, _ = parser.parse_known_args(argumentos)
    modulo, funcao = _resolver(preliminar.comando)
    configurar = getattr(modulo, "configurar_parser", None)
    if callable(configurar):
        configurar(comandos[preliminar.comando])
    args = parser.parse_args(argumentos)
    configurar_log(args.nivel_log)
    try:
        config = load_config(args.config)
    except ConfigInvalida as erro:
        logger.error("config_invalida comando=%s erro=%s", args.comando, erro)
        return ExitCode.CONFIG_INVALIDA
    try:
        _exigir_portoes(args, config)
    except PortaoRecusado as erro:
        logger.error("portao_recusado comando=%s erro=%s", args.comando, erro)
        return ExitCode.PORTAO_RECUSADO
    if funcao is None:
        logger.error("comando_nao_implementado comando=%s", args.comando)
        return ExitCode.NAO_IMPLEMENTADO
    return _executar(funcao, args, config)


if __name__ == "__main__":
    sys.exit(main())
