"""Guarda de rede da reprodução offline: nenhuma conexão sai do processo (T14)."""

from __future__ import annotations

import socket
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from sustemporal.errors import RedeProibida
from sustemporal.reporting.reproduce_rede import sem_rede

if TYPE_CHECKING:
    from collections.abc import Iterator

_METODOS = (
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
    (socket, "create_connection"),
    (socket, "getaddrinfo"),
)


@pytest.fixture
def escuta() -> Iterator[tuple[str, int]]:
    """Servidor TCP em loopback que aceita conexões (o pytest-socket só permite loopback)."""
    with closing(socket.socket()) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(5)
        yield servidor.getsockname()


def test_conexao_e_recusada_mesmo_para_a_maquina_local(escuta: tuple[str, int]) -> None:
    with sem_rede():
        with pytest.raises(RedeProibida, match="rede_proibida"):
            socket.create_connection(escuta, timeout=1)
        with closing(socket.socket()) as cliente, pytest.raises(RedeProibida):
            cliente.connect(escuta)
        with closing(socket.socket()) as cliente, pytest.raises(RedeProibida):
            cliente.connect_ex(escuta)


def test_resolucao_de_nome_e_recusada() -> None:
    with sem_rede(), pytest.raises(RedeProibida):
        socket.getaddrinfo("localhost", 80)


def test_ao_sair_do_bloco_a_rede_volta_ao_que_era(escuta: tuple[str, int]) -> None:
    antes = {chave: getattr(*chave) for chave in _METODOS}
    with sem_rede():
        assert all(getattr(*chave) is not antes[chave] for chave in _METODOS)
    assert {chave: getattr(*chave) for chave in _METODOS} == antes
    with closing(socket.create_connection(escuta, timeout=1)):
        pass


def test_a_rede_volta_ao_que_era_mesmo_com_erro_no_bloco() -> None:
    antes = {chave: getattr(*chave) for chave in _METODOS}
    with pytest.raises(ZeroDivisionError), sem_rede():
        raise ZeroDivisionError
    assert {chave: getattr(*chave) for chave in _METODOS} == antes


def test_blocos_aninhados_restauram_na_ordem_certa() -> None:
    antes = {chave: getattr(*chave) for chave in _METODOS}
    with sem_rede():
        with sem_rede():
            pass
        with pytest.raises(RedeProibida):
            socket.getaddrinfo("localhost", 80)
    assert {chave: getattr(*chave) for chave in _METODOS} == antes
