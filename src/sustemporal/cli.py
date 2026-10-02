"""Interface de linha de comando `sustemporal` com despacho preguiçoso por comando."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.config import load_config
from sustemporal.errors import ConfigInvalida, ErroSustemporal, ExitCode
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


def _configurar_comando(nome: str, sub: argparse.ArgumentParser) -> None:
    obrigatoria = nome in _COM_CONFIG_OBRIGATORIA
    padrao = None if obrigatoria else CONFIG_PADRAO
    sub.add_argument("--config", type=Path, required=obrigatoria, default=padrao)
    if nome == "validate":
        sub.add_argument("--policy", required=True, choices=POLITICAS)
    if nome in {"explain", "counterfactual"}:
        sub.add_argument("--run", required=True)
        sub.add_argument("--row", required=True)
    if nome in {"evaluate", "annotation-export", "reproduce"}:
        sub.add_argument("--freeze", required=True)
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
        if erro.name and nome_modulo.startswith(erro.name):
            return None
        raise


def _resolver(comando: str) -> tuple[ModuleType | None, Manipulador | None]:
    nome_modulo, nome_funcao = MANIPULADORES[comando].split(":")
    modulo = _importar(nome_modulo)
    funcao = getattr(modulo, nome_funcao, None) if modulo is not None else None
    return modulo, funcao if callable(funcao) else None


def _executar(funcao: Manipulador, args: argparse.Namespace, config: RunConfig) -> int:
    try:
        return int(funcao(args, config))
    except NotImplementedError:
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
    if funcao is None:
        logger.error("comando_nao_implementado comando=%s", args.comando)
        return ExitCode.NAO_IMPLEMENTADO
    return _executar(funcao, args, config)


if __name__ == "__main__":
    sys.exit(main())
