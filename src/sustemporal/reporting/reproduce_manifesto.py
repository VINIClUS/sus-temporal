"""Manifesto de aquisição como estava no congelamento: o histórico até o `criado_em` (T14).

O `reproduce` ingere e valida contra uma cópia do manifesto só com as observações até o instante do
congelamento e as versões que elas trazem. Coleta, republicação, recoleta ou ausência registradas
depois não entram: o `freeze_id` resolve o histórico que existia, nunca o atual. A cópia reencadeia
as linhas mantidas; sem corte no meio, ela é igual ao prefixo do original.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.artifacts import LinhaManifesto, TipoLinhaManifesto
from sustemporal.errors import ConfigInvalida

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion

__all__ = ["Recorte", "manifesto_do_congelamento", "observacoes_do_recorte"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Recorte:
    """O que o manifesto atual tem depois do congelamento e a cópia deixou de fora."""

    artefatos: int
    observacoes: int


def _acrescentar(
    linhas: list[LinhaManifesto], tipo: TipoLinhaManifesto, conteudo: dict[str, object]
) -> None:
    anterior = linhas[-1] if linhas else None
    linha = {
        "sequencia": 1 if anterior is None else anterior.sequencia + 1,
        "tipo": tipo,
        "anterior_sha256": None if anterior is None else anterior.sha256(),
    }
    linhas.append(LinhaManifesto.model_validate({**linha, **conteudo}))


def _linhas(
    mantidas: Iterable[ArtifactObservation], versoes: Mapping[str, ArtifactVersion]
) -> list[LinhaManifesto]:
    """Observações mantidas em ordem, cada versão antes da primeira que a traz, reencadeadas."""
    linhas: list[LinhaManifesto] = []
    vistas: set[str] = set()
    for observacao in mantidas:
        artefato = observacao.artifact_id
        if artefato is not None and artefato not in vistas:
            vistas.add(artefato)
            _acrescentar(linhas, TipoLinhaManifesto.VERSAO, {"versao": versoes[artefato]})
        _acrescentar(linhas, TipoLinhaManifesto.OBSERVACAO, {"observacao": observacao})
    return linhas


def _gravar(raiz: Path, linhas: list[LinhaManifesto]) -> None:
    raiz.mkdir(parents=True, exist_ok=True)
    caminho = raiz / NOME_MANIFESTO_AQUISICAO
    texto = "".join(f"{linha.model_dump_json()}\n" for linha in linhas)
    caminho.write_text(texto, encoding="utf-8")
    ancora = {"sequencia": len(linhas), "sha256": linhas[-1].sha256() if linhas else None}
    caminho.with_name(f"{caminho.name}.ancora").write_text(json.dumps(ancora), encoding="utf-8")


def manifesto_do_congelamento(raiz_origem: Path, raiz_destino: Path, instante: datetime) -> Recorte:
    """Grava em `raiz_destino` o manifesto de `raiz_origem` só com o observado até `instante`.

    A observação no próprio instante entra. Um artefato só vale se alguma observação dele entrou.

    Raises:
        ConfigInvalida: `raiz_destino` é a própria `raiz_origem`: o manifesto é append-only e nunca
            é regravado.
        ManifestoCorrompido: o manifesto de origem não passa na verificação (cadeia e âncora).
    """
    if raiz_origem.resolve() == raiz_destino.resolve():
        raise ConfigInvalida(f"manifesto_do_congelamento_sobre_a_origem raiz={raiz_origem}")
    estado = Manifesto(raiz_origem / NOME_MANIFESTO_AQUISICAO).ler()
    mantidas = [o for o in estado.observacoes if o.observado_em <= instante]
    linhas = _linhas(mantidas, estado.versoes)
    _gravar(raiz_destino, linhas)
    artefatos = sum(1 for linha in linhas if linha.versao is not None)
    recorte = Recorte(len(estado.versoes) - artefatos, len(estado.observacoes) - len(mantidas))
    logger.info(
        "manifesto_do_congelamento destino=%s artefatos_ignorados=%d observacoes_ignoradas=%d",
        raiz_destino,
        recorte.artefatos,
        recorte.observacoes,
    )
    return recorte


def observacoes_do_recorte(recorte: Recorte) -> list[str]:
    """Linhas de `observacoes` do `reproducao.json` para o que ficou de fora (não é divergência)."""
    itens = []
    if recorte.artefatos:
        itens.append(f"artefatos_fora_do_congelamento_ignorados n={recorte.artefatos}")
    if recorte.observacoes:
        itens.append(f"observacoes_posteriores_ao_congelamento_ignoradas n={recorte.observacoes}")
    return itens
