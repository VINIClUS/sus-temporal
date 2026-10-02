"""Manipuladores de CLI falsos para testar o despacho."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.errors import PortaoRecusado, RedeProibida

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig

CHAMADAS: list[str] = []


def configurar_parser(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--extra-falso", default="padrao")


def executar_ok(args: argparse.Namespace, config: RunConfig) -> int:
    CHAMADAS.append(f"{args.comando}:{config.versao}:{getattr(args, 'extra_falso', '')}")
    return 0


def executar_nao_implementado(args: argparse.Namespace, config: RunConfig) -> int:
    raise NotImplementedError


def executar_portao(args: argparse.Namespace, config: RunConfig) -> int:
    raise PortaoRecusado("portao_ausente portao=G2")


def executar_rede(args: argparse.Namespace, config: RunConfig) -> int:
    raise RedeProibida("rede_nao_permitida")
