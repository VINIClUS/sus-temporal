"""Guarda de rede da reprodução offline: nenhum socket de rede abre nem envia enquanto roda (T14).

A reprodução refaz o fluxo dos originais locais e nunca precisa de rede. A guarda vale para o módulo
`socket` do Python e age no nível do socket, não API por API: recusa criar socket que não seja
`AF_UNIX` (o construtor de `socket.socket`, para qualquer referência à classe) e, em socket de rede
criado antes dela, `connect`, `connect_ex`, `sendto`, `sendmsg`, `send`, `sendall` e `sendfile`;
recusa também `create_connection` e a resolução de nome (`getaddrinfo`, `gethostbyname`,
`gethostbyname_ex`, `gethostbyaddr` e `getnameinfo`). `AF_UNIX` (comunicação local, como o
`socketpair`) segue permitido. Tudo falha com `RedeProibida` (saída 6), inclusive para a máquina
local, e é restaurado ao sair, com ou sem exceção. Vale para o processo inteiro, então a reprodução
não convive com outro trabalho de rede no mesmo processo.

Fica fora o que não passa pelo módulo `socket`: extensão em C que abra socket nativo (o DuckDB não
instala nem carrega extensões sozinho: `sustemporal.duck.conectar`), o `_socket` usado direto, o
descritor de um socket aberto usado por `os.write` ou `os.sendfile`, o socket TLS (`ssl.SSLSocket`)
aberto antes da guarda, cujos `send`, `sendall`, `sendfile` e `write` escrevem pelo OpenSSL sem
passar pelos métodos de `socket.socket`, e subprocesso (T14-16). A CLI não abre esse socket.
"""

from __future__ import annotations

import logging
import socket
from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING, Any, NoReturn

from sustemporal.errors import RedeProibida

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

__all__ = ["sem_rede"]

logger = logging.getLogger(__name__)

_AF_UNIX = getattr(socket, "AF_UNIX", None)
_AUSENTE = object()
_METODOS_DE_ENVIO = ("connect", "connect_ex", "sendto", "sendmsg", "send", "sendall", "sendfile")
_FUNCOES_DO_MODULO = (
    "create_connection",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
)


def _recusar(operacao: str) -> NoReturn:
    raise RedeProibida(f"rede_proibida contexto=reproduce_offline operacao={operacao}")


def _funcao_recusada(operacao: str) -> Callable[..., NoReturn]:
    def recusada(*_args: Any, **_kwargs: Any) -> NoReturn:
        _recusar(operacao)

    return recusada


def _metodo_guardado(operacao: str, original: Callable[..., Any]) -> Callable[..., Any]:
    """O método que recusa em socket que não é `AF_UNIX` e delega ao original no que é."""

    def guardado(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        if self.family != _AF_UNIX:
            _recusar(operacao)
        return original(self, *args, **kwargs)

    return guardado


def _argumento(
    args: tuple[Any, ...], kwargs: Mapping[str, Any], posicao: int, nome: str, padrao: Any
) -> Any:
    if nome in kwargs:
        return kwargs[nome]
    return args[posicao] if len(args) > posicao else padrao


def _criacao_guardada(original: Callable[..., None]) -> Callable[..., None]:
    """O construtor que só abre `AF_UNIX`; a família padrão (`-1`) é `AF_INET`.

    Com `fileno` e sem família o socket é lido do descritor, e o de rede é devolvido ao dono
    (`detach`) antes da recusa, sem fechar o descritor que não é da guarda.
    """

    def guardada(self: socket.socket, *args: Any, **kwargs: Any) -> None:
        familia = _argumento(args, kwargs, 0, "family", -1)
        fileno = _argumento(args, kwargs, 3, "fileno", None)
        if familia != _AF_UNIX and (familia != -1 or fileno is None):
            _recusar("socket")
        original(self, *args, **kwargs)
        if self.family != _AF_UNIX:
            self.detach()
            _recusar("socket")

    return guardada


def _substituir(dono: Any, nome: str, novo: Any) -> Callable[[], None]:
    """Troca o atributo e devolve o que o deixa como estava, inclusive se era só herdado."""
    antigo = vars(dono).get(nome, _AUSENTE)
    setattr(dono, nome, novo)

    def restaurar() -> None:
        if antigo is _AUSENTE:
            delattr(dono, nome)
        else:
            setattr(dono, nome, antigo)

    return restaurar


def _substituicoes() -> Iterator[tuple[Any, str, Any]]:
    classe = socket.socket
    yield classe, "__init__", _criacao_guardada(classe.__init__)
    for nome in _METODOS_DE_ENVIO:
        yield classe, nome, _metodo_guardado(nome, getattr(classe, nome))
    for nome in _FUNCOES_DO_MODULO:
        yield socket, nome, _funcao_recusada(nome)


@contextmanager
def sem_rede() -> Iterator[None]:
    """Recusa abrir socket de rede, conectar, enviar e resolver nome até sair do bloco."""
    with ExitStack() as restauracoes:
        for dono, nome, novo in _substituicoes():
            restauracoes.callback(_substituir(dono, nome, novo))
        logger.info("rede_bloqueada contexto=reproduce_offline")
        yield
