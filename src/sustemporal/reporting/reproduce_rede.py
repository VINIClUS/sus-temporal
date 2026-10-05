"""Guarda de rede da reprodução offline: nenhuma conexão sai do processo enquanto ela roda (T14).

A reprodução refaz o fluxo dos originais locais e nunca precisa de rede. A guarda recusa toda
conexão e toda resolução de nome (`RedeProibida`, saída 6), inclusive para a máquina local, e
restaura os métodos do `socket` ao sair. Vale para o processo inteiro, então a reprodução não
convive com outro trabalho de rede no mesmo processo.
"""

from __future__ import annotations

import logging
import socket
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NoReturn

from sustemporal.errors import RedeProibida

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["sem_rede"]

logger = logging.getLogger(__name__)


def _recusar(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise RedeProibida("rede_proibida contexto=reproduce_offline")


@contextmanager
def sem_rede() -> Iterator[None]:
    """Recusa `connect`, `connect_ex`, `create_connection` e `getaddrinfo` até sair do bloco."""
    originais = {
        (socket.socket, "connect"): socket.socket.connect,
        (socket.socket, "connect_ex"): socket.socket.connect_ex,
        (socket, "create_connection"): socket.create_connection,
        (socket, "getaddrinfo"): socket.getaddrinfo,
    }
    for dono, nome in originais:
        setattr(dono, nome, _recusar)
    logger.info("rede_bloqueada contexto=reproduce_offline")
    try:
        yield
    finally:
        for (dono, nome), original in originais.items():
            setattr(dono, nome, original)
