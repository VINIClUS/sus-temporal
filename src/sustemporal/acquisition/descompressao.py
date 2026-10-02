"""Descompressão de DBC com teto rígido de bytes gravados, isolada em processo filho.

O filho roda com `RLIMIT_FSIZE`: o núcleo recusa (EFBIG) qualquer escrita além do teto, então um
fluxo DCL que declara pouco e produz muito nunca enche o disco. O Python ignora SIGXFSZ, e a
recusa chega ao descompressor como erro de E/S.
"""

from __future__ import annotations

import enum
import resource
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["DesfechoDescompressao", "ResultadoDescompressao", "descomprimir_limitado"]

PRAZO_PADRAO = 3600.0
_SAIDA_ERRO = 3


class DesfechoDescompressao(enum.Enum):
    OK = "OK"
    TRUNCADO = "TRUNCADO"
    EXCEDEU_LIMITE = "EXCEDEU_LIMITE"
    INVALIDO = "INVALIDO"


@dataclass(frozen=True)
class ResultadoDescompressao:
    desfecho: DesfechoDescompressao
    mensagem: str = ""


def _classificar(retorno: int, mensagem: str, destino: Path, limite: int) -> ResultadoDescompressao:
    if retorno == 0:
        return ResultadoDescompressao(DesfechoDescompressao.OK)
    gravados = destino.stat().st_size if destino.exists() else 0
    if "File too large" in mensagem or gravados >= limite:
        return ResultadoDescompressao(DesfechoDescompressao.EXCEDEU_LIMITE, mensagem)
    if "end of input" in mensagem:
        return ResultadoDescompressao(DesfechoDescompressao.TRUNCADO, mensagem)
    return ResultadoDescompressao(DesfechoDescompressao.INVALIDO, mensagem)


def descomprimir_limitado(
    origem: Path, destino: Path, limite: int, *, prazo: float = PRAZO_PADRAO
) -> ResultadoDescompressao:
    """Descomprime `origem` em `destino` sem nunca gravar mais que `limite` bytes."""

    def _limitar() -> None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (limite, limite))

    comando = [sys.executable, "-m", __name__, str(origem), str(destino)]
    try:
        processo = subprocess.run(  # noqa: S603
            comando,
            preexec_fn=_limitar,
            capture_output=True,
            text=True,
            timeout=prazo,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ResultadoDescompressao(DesfechoDescompressao.INVALIDO, "prazo_excedido")
    mensagem = processo.stderr.strip()[-500:]
    return _classificar(processo.returncode, mensagem, destino, limite)


def _principal(argumentos: list[str]) -> int:
    import datasus_dbc

    origem, destino = argumentos
    try:
        datasus_dbc.decompress(origem, destino)
    except (ValueError, OSError) as erro:
        sys.stderr.write(f"{type(erro).__name__}: {erro}\n")
        return _SAIDA_ERRO
    return 0


if __name__ == "__main__":
    sys.exit(_principal(sys.argv[1:]))
