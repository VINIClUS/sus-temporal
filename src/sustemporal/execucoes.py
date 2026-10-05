"""Lugar único das execuções do `validate`: `<raiz_saidas>/runs/<run_id>/`.

`validate` (`--entrada` e `--ingest`) grava ali por padrão e os consumidores (`explain`,
`counterfactual`) só descobrem execuções ali. `validate --saida` desvia a gravação; uma execução
fora de `runs/` não é encontrada por eles.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig

__all__ = ["DIRETORIO_EXECUCOES", "raiz_execucoes"]

DIRETORIO_EXECUCOES = "runs"


def raiz_execucoes(config: RunConfig) -> Path:
    """Raiz das execuções: `<raiz_saidas>/runs`."""
    return Path(config.runtime.raiz_saidas) / DIRETORIO_EXECUCOES
