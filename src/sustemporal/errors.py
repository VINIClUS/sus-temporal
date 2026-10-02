"""Exceções da aplicação com código de saída da CLI."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    ERRO_GENERICO = 1
    CONFIG_INVALIDA = 2
    NAO_IMPLEMENTADO = 3
    PORTAO_RECUSADO = 4
    FALHA_OPERACIONAL = 5
    REDE_PROIBIDA = 6


class ErroSustemporal(Exception):
    codigo_saida = ExitCode.ERRO_GENERICO


class ConfigInvalida(ErroSustemporal):
    codigo_saida = ExitCode.CONFIG_INVALIDA


class PortaoRecusado(ErroSustemporal):
    codigo_saida = ExitCode.PORTAO_RECUSADO


class FalhaOperacionalErro(ErroSustemporal):
    codigo_saida = ExitCode.FALHA_OPERACIONAL


class RedeProibida(ErroSustemporal):
    codigo_saida = ExitCode.REDE_PROIBIDA
