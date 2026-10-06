"""Arquivo local que a reprodução não consegue ler: erro de entrada, nunca traceback (T14).

A cadeia abre arquivos de muitos módulos (config, catálogos, território, `ingest`, `validate`), e
cada leitor trata o defeito de leitura do jeito dele. O que nenhum trata (diretório no lugar do
arquivo, falta de permissão, bytes que não decodificam, catálogo ausente ou inválido) não escapa
como traceback: `entradas_legiveis` o traduz em erro de entrada (saída 2) ou, se o arquivo é do
destino da própria reprodução, em falha operacional (saída 5). Os originais que a reprodução lê em
módulo próprio (manifesto de aquisição, registro de rodadas, relatório, insumos...) têm resultado
próprio, item inconclusivo, e a tabela de `reproduce_varredura.LEITURAS` diz qual é o de cada um.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.rules.catalog import CatalogoInvalido

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["arquivo_sob", "entradas_legiveis"]

logger = logging.getLogger(__name__)

_FALHAS_DE_LEITURA = (OSError, UnicodeDecodeError, CatalogoInvalido)
_SEM_ARQUIVO = "-"


def _arquivo(erro: BaseException) -> str:
    nome = getattr(erro, "filename", None)
    if isinstance(nome, str | bytes | os.PathLike):
        return os.fsdecode(nome)
    return _SEM_ARQUIVO


def _onde(erro: BaseException) -> str:
    """O módulo e a função do projeto (fora deste módulo) mais perto da falha, ou `-`."""
    onde = _SEM_ARQUIVO
    quadro = erro.__traceback__
    while quadro is not None:
        modulo = str(quadro.tb_frame.f_globals.get("__name__", ""))
        if modulo.startswith("sustemporal.") and modulo != __name__:
            onde = f"{modulo.removeprefix('sustemporal.')}.{quadro.tb_frame.f_code.co_name}"
        quadro = quadro.tb_next
    return onde


def arquivo_sob(erro: BaseException, raiz: Path) -> str | None:
    """O arquivo do erro, relativo a `raiz` (texto POSIX), ou `None` se o erro não é de um dela."""
    nome = _arquivo(erro)
    if nome == _SEM_ARQUIVO:
        return None
    try:
        return Path(os.path.abspath(nome)).relative_to(os.path.abspath(raiz)).as_posix()
    except ValueError:
        return None


@contextmanager
def entradas_legiveis(saida: Path) -> Iterator[None]:
    """Traduz a falha de leitura que a cadeia não tratou: `OSError`, bytes que não decodificam e
    catálogo inválido.

    Raises:
        ConfigInvalida: o arquivo é uma entrada (config, catálogo, território, dados).
        FalhaOperacionalErro: o arquivo é do destino `saida`, gravado pela própria reprodução.
    """
    try:
        yield
    except _FALHAS_DE_LEITURA as erro:
        detalhe = f"arquivo={_arquivo(erro)} erro={type(erro).__name__} onde={_onde(erro)}"
        logger.warning("arquivo_ilegivel %s", detalhe)
        if arquivo_sob(erro, saida) is not None:
            raise FalhaOperacionalErro(f"reproduce_saida_ilegivel {detalhe}") from erro
        raise ConfigInvalida(f"reproduce_entrada_ilegivel {detalhe}") from erro
