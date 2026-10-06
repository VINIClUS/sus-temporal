"""Escrita interrompida no manifesto de aquisição, como a queda no meio de `Manifesto.registrar`.

Os dois estados que a queda deixa: meia linha sem quebra final e uma VERSAO completa, encadeada,
sem a OBSERVACAO da mesma transação (e sem a âncora dela). Conteúdo SINTETICO.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.artifacts import (
    LinhaManifesto,
    TipoLinhaManifesto,
    calcular_artifact_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["QUEDAS", "meia_linha", "versao_sem_observacao"]


def meia_linha(manifesto: Path) -> str:
    """Acrescenta meia linha, sem quebra final; devolve o texto acrescentado."""
    texto = '{"sequencia": 99, "tip'
    with manifesto.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto)
    return texto


def versao_sem_observacao(manifesto: Path) -> str:
    """Acrescenta a VERSAO de um conteúdo novo sem a OBSERVACAO; devolve o texto acrescentado."""
    estado = Manifesto(manifesto).ler()
    modelo = next(iter(estado.versoes.values()))
    sha256 = "e" * 64
    versao = modelo.model_copy(
        update={"sha256": sha256, "artifact_id": calcular_artifact_id(modelo.chave, sha256)}
    )
    ultima = estado.linhas[-1]
    linha = LinhaManifesto(
        sequencia=ultima.sequencia + 1,
        tipo=TipoLinhaManifesto.VERSAO,
        versao=versao,
        anterior_sha256=ultima.sha256(),
    )
    texto = linha.model_dump_json() + "\n"
    with manifesto.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto)
    return texto


QUEDAS: dict[str, Callable[[Path], str]] = {
    "meia_linha": meia_linha,
    "versao_sem_observacao": versao_sem_observacao,
}
