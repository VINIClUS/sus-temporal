"""Armazenamento endereçado por conteúdo com promoção sem sobrescrita."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from pathlib import Path

_BLOCO = 1024 * 1024


def caminho_conteudo(raiz: Path, sha256: str, extensao: str) -> Path:
    return raiz / "sha256" / sha256[:2] / f"{sha256}.{extensao.lower().lstrip('.')}"


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(_BLOCO), b""):
            digest.update(bloco)
    return digest.hexdigest()


def promover_sem_sobrescrever(temporario: Path, destino: Path) -> bool:
    """Move o temporário para o destino sem nunca sobrescrever um original.

    Returns:
        True se o conteúdo foi gravado; False se o destino já tinha o mesmo conteúdo.
    Raises:
        FalhaOperacionalErro: o destino existe com conteúdo diferente.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(temporario, destino)
    except FileExistsError:
        if _sha256(destino) != _sha256(temporario):
            raise FalhaOperacionalErro(
                f"destino_com_conteudo_divergente destino={destino}"
            ) from None
        temporario.unlink()
        return False
    temporario.unlink()
    return True
