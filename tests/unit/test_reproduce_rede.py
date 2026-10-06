"""Guarda de rede da reprodução offline: nenhum socket de rede abre nem envia (T14).

A guarda vale para o módulo `socket` do Python no processo: recusa criar socket que não seja
`AF_UNIX`, recusa conectar e enviar (inclusive datagrama sem conexão) em socket de rede criado antes
dela e recusa a resolução de nome. Os testes usam só o loopback e provam que nada saiu: o receptor
UDP e o servidor TCP ficam fora da guarda e nada chega a eles.
"""

from __future__ import annotations

import gc
import os
import socket
from contextlib import closing, suppress
from typing import TYPE_CHECKING

import pytest

from sustemporal.errors import RedeProibida
from sustemporal.reporting.reproduce_rede import sem_rede

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_DO_SOCKET = (
    "__init__",
    "connect",
    "connect_ex",
    "sendto",
    "sendmsg",
    "send",
    "sendall",
    "sendfile",
)
_DO_MODULO = (
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
)
_METODOS = (
    *((socket.socket, nome) for nome in _DO_SOCKET),
    *((socket, nome) for nome in _DO_MODULO),
)


@pytest.fixture
def escuta() -> Iterator[socket.socket]:
    """Servidor TCP em loopback que aceita conexões (o pytest-socket só permite loopback)."""
    with closing(socket.socket()) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(5)
        servidor.settimeout(1)
        yield servidor


@pytest.fixture
def receptor() -> Iterator[socket.socket]:
    """Socket UDP em loopback: o `recvfrom` expira se nenhum datagrama chegou."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as soquete:
        soquete.bind(("127.0.0.1", 0))
        soquete.settimeout(0.3)
        yield soquete


def _nada_chegou(receptor: socket.socket) -> None:
    with pytest.raises(TimeoutError):
        receptor.recvfrom(64)


def _estado() -> tuple[dict[tuple[object, str], object], set[str]]:
    """O que a guarda troca e as chaves que a classe `socket.socket` tem em si."""
    return {chave: getattr(*chave) for chave in _METODOS}, set(vars(socket.socket))


def test_conexao_e_recusada_mesmo_para_a_maquina_local(escuta: socket.socket) -> None:
    destino = escuta.getsockname()
    with closing(socket.socket()) as uma, closing(socket.socket()) as outra, sem_rede():
        with pytest.raises(RedeProibida, match="rede_proibida"):
            socket.create_connection(destino, timeout=1)
        with pytest.raises(RedeProibida, match="operacao=connect"):
            uma.connect(destino)
        with pytest.raises(RedeProibida, match="operacao=connect_ex"):
            outra.connect_ex(destino)


def test_sendto_em_socket_udp_criado_antes_da_guarda_e_recusado_e_nada_chega(
    receptor: socket.socket,
) -> None:
    emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with closing(emissor), sem_rede(), pytest.raises(RedeProibida, match="operacao=sendto"):
        emissor.sendto(b"datagrama", receptor.getsockname())
    _nada_chegou(receptor)


def test_sendmsg_com_destino_em_socket_criado_antes_da_guarda_e_recusado_e_nada_chega(
    receptor: socket.socket,
) -> None:
    emissor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with closing(emissor), sem_rede(), pytest.raises(RedeProibida, match="operacao=sendmsg"):
        emissor.sendmsg([b"datagrama"], [], 0, receptor.getsockname())
    _nada_chegou(receptor)


def test_send_e_sendall_em_socket_udp_conectado_antes_da_guarda_sao_recusados(
    receptor: socket.socket,
) -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as emissor:
        emissor.connect(receptor.getsockname())
        with sem_rede():
            with pytest.raises(RedeProibida, match="operacao=send"):
                emissor.send(b"datagrama")
            with pytest.raises(RedeProibida, match="operacao=sendall"):
                emissor.sendall(b"datagrama")
    _nada_chegou(receptor)


def test_envio_numa_conexao_tcp_aberta_antes_da_guarda_e_recusado_e_nada_chega(
    escuta: socket.socket, tmp_path: Path
) -> None:
    arquivo = tmp_path / "dados.bin"
    arquivo.write_bytes(b"dados")
    with closing(socket.create_connection(escuta.getsockname(), timeout=1)) as cliente:
        conexao, _ = escuta.accept()
        with closing(conexao), arquivo.open("rb") as origem:
            conexao.settimeout(0.3)
            with sem_rede():
                with pytest.raises(RedeProibida, match="operacao=sendall"):
                    cliente.sendall(b"dados")
                with pytest.raises(RedeProibida, match="operacao=sendfile"):
                    cliente.sendfile(origem)
            with pytest.raises(TimeoutError):
                conexao.recv(16)


@pytest.mark.parametrize(
    ("familia", "tipo"),
    [
        pytest.param(socket.AF_INET, socket.SOCK_STREAM, id="inet_tcp"),
        pytest.param(socket.AF_INET, socket.SOCK_DGRAM, id="inet_udp"),
        pytest.param(socket.AF_INET6, socket.SOCK_STREAM, id="inet6_tcp"),
        pytest.param(socket.AF_INET6, socket.SOCK_DGRAM, id="inet6_udp"),
    ],
)
def test_socket_de_rede_nao_abre_dentro_da_guarda(familia: int, tipo: int) -> None:
    with sem_rede(), pytest.raises(RedeProibida, match="operacao=socket"):
        socket.socket(familia, tipo)


def test_socket_sem_argumentos_e_inet_e_a_familia_vale_por_numero_ou_palavra_chave() -> None:
    with sem_rede():
        with pytest.raises(RedeProibida):
            socket.socket()
        with pytest.raises(RedeProibida):
            socket.socket(family=socket.AF_INET)
        with pytest.raises(RedeProibida):
            socket.socket(int(socket.AF_INET6), int(socket.SOCK_DGRAM))


@pytest.mark.skipif(not hasattr(socket, "AF_NETLINK"), reason="AF_NETLINK só existe no Linux")
def test_familia_que_nao_e_inet_nem_unix_tambem_e_recusada() -> None:
    with sem_rede(), pytest.raises(RedeProibida, match="operacao=socket"):
        socket.socket(socket.AF_NETLINK, socket.SOCK_RAW)


@pytest.mark.skipif(
    not os.path.isdir("/proc/self/fd"), reason="contagem de descritores só no Linux"
)
def test_socket_de_rede_recusado_nao_deixa_descritor_aberto() -> None:
    antes = len(os.listdir("/proc/self/fd"))
    with sem_rede():
        for _ in range(3):
            with pytest.raises(RedeProibida):
                socket.socket()
            with pytest.raises(RedeProibida):
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    gc.collect()
    assert len(os.listdir("/proc/self/fd")) == antes


def test_servidor_de_rede_tambem_nao_abre() -> None:
    with sem_rede(), pytest.raises(RedeProibida):
        socket.create_server(("127.0.0.1", 0))


def test_socket_de_rede_a_partir_de_descritor_e_recusado_e_o_descritor_fica_com_o_dono() -> None:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as original:
        descritor = os.dup(original.fileno())
    try:
        with sem_rede():
            with pytest.raises(RedeProibida) as recusa:
                socket.socket(fileno=descritor)
            del recusa
            gc.collect()
            os.fstat(descritor)
            with pytest.raises(RedeProibida):
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM, fileno=descritor)
        os.fstat(descritor)
    finally:
        with suppress(OSError):
            os.close(descritor)


def test_af_unix_e_permitido_dentro_da_guarda() -> None:
    with sem_rede():
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)):
            pass
        with closing(socket.socket(family=socket.AF_UNIX, type=socket.SOCK_DGRAM)):
            pass
        esquerdo, direito = socket.socketpair()
        with closing(esquerdo), closing(direito):
            esquerdo.send(b"a")
            assert direito.recv(1) == b"a"
            esquerdo.sendall(b"b")
            assert direito.recv(1) == b"b"
            esquerdo.sendmsg([b"c"])
            assert direito.recv(1) == b"c"


@pytest.mark.parametrize(
    "chamada",
    [
        pytest.param(lambda: socket.getaddrinfo("localhost", 80), id="getaddrinfo"),
        pytest.param(lambda: socket.gethostbyname("localhost"), id="gethostbyname"),
        pytest.param(lambda: socket.gethostbyname_ex("localhost"), id="gethostbyname_ex"),
        pytest.param(lambda: socket.gethostbyaddr("127.0.0.1"), id="gethostbyaddr"),
        pytest.param(lambda: socket.getnameinfo(("127.0.0.1", 80), 0), id="getnameinfo"),
        pytest.param(lambda: socket.getfqdn("localhost"), id="getfqdn"),
    ],
)
def test_resolucao_de_nome_e_recusada(chamada: Callable[[], object]) -> None:
    with sem_rede(), pytest.raises(RedeProibida):
        chamada()


def test_ao_sair_do_bloco_a_rede_volta_ao_que_era(
    escuta: socket.socket, receptor: socket.socket
) -> None:
    antes = _estado()
    with sem_rede():
        assert all(getattr(*chave) is not antes[0][chave] for chave in _METODOS)
    assert _estado() == antes
    with closing(socket.create_connection(escuta.getsockname(), timeout=1)):
        pass
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as emissor:
        emissor.sendto(b"voltou", receptor.getsockname())
    assert receptor.recvfrom(16)[0] == b"voltou"


def test_a_guarda_registra_uma_linha_de_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="sustemporal.reporting.reproduce_rede"), sem_rede():
        pass
    assert caplog.messages == ["rede_bloqueada contexto=reproduce_offline"]


def test_a_rede_volta_ao_que_era_mesmo_com_erro_no_bloco() -> None:
    antes = _estado()
    with pytest.raises(ZeroDivisionError), sem_rede():
        raise ZeroDivisionError
    assert _estado() == antes


def test_a_rede_volta_ao_que_era_depois_de_uma_recusa_dentro_do_bloco() -> None:
    antes = _estado()
    with pytest.raises(RedeProibida), sem_rede():
        socket.socket(socket.AF_INET6)
    assert _estado() == antes


def test_blocos_aninhados_restauram_na_ordem_certa(receptor: socket.socket) -> None:
    antes = _estado()
    with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as emissor, sem_rede():
        with sem_rede():
            pass
        with pytest.raises(RedeProibida):
            socket.getaddrinfo("localhost", 80)
        with pytest.raises(RedeProibida):
            emissor.sendto(b"x", receptor.getsockname())
    assert _estado() == antes
    _nada_chegou(receptor)
