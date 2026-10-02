"""Manipuladores de CLI falsos para testar o despacho."""

from __future__ import annotations

import io
import zipfile
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


def executar_chama_stub_interno(args: argparse.Namespace, config: RunConfig) -> int:
    return _etapa_ainda_stub()


def _etapa_ainda_stub() -> int:
    raise NotImplementedError


def executar_falha_de_biblioteca(args: argparse.Namespace, config: RunConfig) -> int:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("membro.txt", b"1")
    dados = bytearray(buffer.getvalue())
    dados[dados.index(b"PK\x01\x02") + 6] = 0xFF
    zipfile.ZipFile(io.BytesIO(bytes(dados)))
    return 0


def executar_portao(args: argparse.Namespace, config: RunConfig) -> int:
    raise PortaoRecusado("portao_ausente portao=G2")


def executar_rede(args: argparse.Namespace, config: RunConfig) -> int:
    raise RedeProibida("rede_nao_permitida")
