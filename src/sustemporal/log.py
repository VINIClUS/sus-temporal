"""Configuração de logging estruturado `chave=valor`."""

from __future__ import annotations

import logging

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configurar_log(nivel: str = "INFO") -> None:
    logging.basicConfig(level=nivel, format=FORMATO, force=True)
