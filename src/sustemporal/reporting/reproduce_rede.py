"""Guarda de rede da reprodução offline: nenhuma conexão sai do processo (T14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

__all__ = ["sem_rede"]


def sem_rede() -> AbstractContextManager[None]:
    """Recusa `connect`, `connect_ex`, `create_connection` e `getaddrinfo` até sair do bloco."""
    raise NotImplementedError
