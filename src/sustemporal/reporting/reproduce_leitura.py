"""Arquivo local que a reprodução não consegue ler: erro de entrada, nunca traceback (T14)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

__all__ = ["arquivo_sob", "entradas_legiveis"]


def arquivo_sob(erro: BaseException, raiz: Path) -> str | None:
    """O arquivo do erro, relativo a `raiz` (texto POSIX), ou `None` se o erro não é de um dela."""
    raise NotImplementedError


def entradas_legiveis(saida: Path) -> AbstractContextManager[None]:
    """Traduz a falha de leitura que a cadeia não tratou em erro de entrada ou do destino."""
    raise NotImplementedError
