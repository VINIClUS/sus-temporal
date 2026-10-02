import socket

import pytest
from pytest_socket import SocketConnectBlockedError

pytestmark = pytest.mark.filterwarnings("ignore:A test tried to use socket")


def test_conexao_fora_do_loopback_e_bloqueada() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexao:
        conexao.settimeout(1)
        with pytest.raises(SocketConnectBlockedError):
            conexao.connect(("10.255.255.1", 80))


def test_conexao_de_nome_externo_e_bloqueada() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conexao:
        conexao.settimeout(1)
        with pytest.raises(SocketConnectBlockedError):
            conexao.connect(("ftp.datasus.gov.br", 21))
