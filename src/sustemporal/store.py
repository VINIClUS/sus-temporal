"""Armazenamento endereçado por conteúdo com promoção sem sobrescrita."""

from __future__ import annotations

import hashlib
import os
import re
from typing import TYPE_CHECKING

from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from pathlib import Path

_BLOCO = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXTENSAO = re.compile(r"[a-z0-9]{1,8}")
_NOME_CONTEUDO = re.compile(r"([0-9a-f]{64})\.([a-z0-9]{1,8})")


def caminho_conteudo(raiz: Path, sha256: str, extensao: str) -> Path:
    """Caminho `raiz/sha256/<2 primeiros>/<sha256>.<extensão>` do conteúdo.

    Raises:
        ValueError: sha256 fora de `[0-9a-f]{64}` ou extensão fora de `[a-z0-9]{1,8}`.
    """
    sufixo = extensao.lower().lstrip(".")
    if not _SHA256.fullmatch(sha256):
        raise ValueError(f"sha256_invalido sha256={sha256!r}")
    if not _EXTENSAO.fullmatch(sufixo):
        raise ValueError(f"extensao_invalida extensao={extensao!r}")
    return raiz / "sha256" / sha256[:2] / f"{sha256}.{sufixo}"


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(_BLOCO), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _exigir_caminho_de_conteudo(destino: Path, sha256: str) -> None:
    nome = _NOME_CONTEUDO.fullmatch(destino.name)
    raiz = destino.parent.parent.parent
    if nome is None or destino != caminho_conteudo(raiz, sha256, nome.group(2)):
        raise FalhaOperacionalErro(
            f"destino_nao_corresponde_ao_conteudo destino={destino} sha256={sha256}"
        )


def _sincronizar(destino: Path) -> None:
    with destino.open("rb") as arquivo:
        os.fsync(arquivo.fileno())
    diretorio = os.open(destino.parent, os.O_RDONLY)
    try:
        os.fsync(diretorio)
    finally:
        os.close(diretorio)


def _conferir_existente(temporario: Path, destino: Path, sha256: str) -> bool:
    if destino.is_symlink():
        raise FalhaOperacionalErro(f"destino_e_link_simbolico destino={destino}")
    if temporario.samefile(destino):
        raise FalhaOperacionalErro(f"temporario_e_destino_sao_o_mesmo_arquivo destino={destino}")
    if _sha256(destino) != sha256:
        raise FalhaOperacionalErro(f"destino_com_conteudo_divergente destino={destino}")
    temporario.unlink()
    return False


def _promover(temporario: Path, destino: Path) -> bool:
    sha256 = _sha256(temporario)
    _exigir_caminho_de_conteudo(destino, sha256)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(temporario, destino)
    except FileExistsError:
        return _conferir_existente(temporario, destino, sha256)
    temporario.unlink()
    _sincronizar(destino)
    return True


def promover_sem_sobrescrever(temporario: Path, destino: Path) -> bool:
    """Liga o temporário ao caminho do seu conteúdo sem nunca sobrescrever um original.

    Returns:
        True se o conteúdo foi gravado; False se o destino já tinha o mesmo conteúdo.
    Raises:
        FalhaOperacionalErro: destino fora do caminho do conteúdo, link simbólico, mesmo arquivo
            que o temporário, conteúdo divergente ou erro do sistema de arquivos.
    """
    try:
        return _promover(temporario, destino)
    except OSError as erro:
        raise FalhaOperacionalErro(f"promocao_falhou destino={destino} erro={erro}") from erro
