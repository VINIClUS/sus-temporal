"""Manifesto de aquisição como o `ingest` original o leu: a posição dele, não um instante (T14).

O `ingest` grava em `manifesto_lido.json` quantas linhas do manifesto leu e o hash da última. A
reprodução acha, em `<raiz_saidas>/ingest`, a execução que produziu o SIA-PA do congelamento (a
mesma união de artefatos) e copia o manifesto atual só até essa posição: coleta, republicação,
recoleta ou ausência registradas depois dela ficam de fora, qualquer que seja o instante da
observação (a coleta semanal registra o tempo todo). Sem a execução, com posições diferentes entre
as candidatas ou com uma posição que o manifesto atual não tem, a posição não se sabe e a
reprodução é inconclusiva: nunca se volta a um corte por instante.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import EstadoManifesto, Manifesto, ManifestoCorrompido
from sustemporal.errors import ConfigInvalida
from sustemporal.evaluation.split import SCHEMA_ENTRADA
from sustemporal.ingest.cli import NOME_POSICAO_MANIFESTO
from sustemporal.rules.ingest import ler_datasets

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts.artifacts import LinhaManifesto
    from sustemporal.contracts.records import DatasetRef

__all__ = [
    "Recorte",
    "Resolucao",
    "gravar_manifesto",
    "observacoes_do_manifesto",
    "resolver_manifesto",
]

logger = logging.getLogger(__name__)

PADRAO_DA_EXECUCAO = "execucao_*"


@dataclass(frozen=True)
class Recorte:
    """O que o manifesto atual tem depois da posição do `ingest` e a cópia deixou de fora."""

    artefatos: int
    observacoes: int


@dataclass(frozen=True)
class Resolucao:
    """O que o `ingest` original leu do manifesto de aquisição, ou por que isso não se sabe.

    `motivo` vazio: `linhas` é o manifesto até a posição lida (vazio, se ele leu um manifesto
    vazio) e `execucao` a pasta do `ingest` que a deu. `motivo` preenchido: nada foi resolvido.
    """

    execucao: str = ""
    linhas: tuple[LinhaManifesto, ...] = ()
    recorte: Recorte = Recorte(0, 0)
    motivo: str = ""


@dataclass(frozen=True)
class _Posicao:
    linhas: int
    cabeca_sha256: str | None


def _sia_pa(conjuntos: Iterable[DatasetRef]) -> frozenset[str]:
    return frozenset(a for c in conjuntos if c.schema_id == SCHEMA_ENTRADA for a in c.artifact_ids)


def _sia_pa_da_execucao(pasta: Path) -> frozenset[str] | None:
    try:
        return _sia_pa(ler_datasets(pasta))
    except ConfigInvalida:
        logger.warning("ingest_original_datasets_ilegivel execucao=%s", pasta.name)
        return None


def _candidatas(raiz_ingest: Path, congelado: frozenset[str]) -> tuple[list[Path], int]:
    """As execuções do `ingest` com o SIA-PA do congelamento (em ordem) e quantas existem."""
    execucoes = sorted(p for p in raiz_ingest.glob(PADRAO_DA_EXECUCAO) if p.is_dir())
    if not congelado:
        return [], len(execucoes)
    return [p for p in execucoes if _sia_pa_da_execucao(p) == congelado], len(execucoes)


def _ler_posicao(pasta: Path) -> _Posicao | None:
    try:
        bruto = json.loads((pasta / NOME_POSICAO_MANIFESTO).read_text(encoding="utf-8"))
        linhas, cabeca = bruto["linhas"], bruto["cabeca_sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if type(linhas) is not int or linhas < 0 or not isinstance(cabeca, str | None):
        return None
    return _Posicao(linhas, cabeca)


def _posicao_unica(candidatas: list[Path]) -> tuple[_Posicao | None, str]:
    """A posição que todas as candidatas leram, ou o motivo de não haver uma só."""
    lidas = [(pasta, _ler_posicao(pasta)) for pasta in candidatas]
    sem_posicao = [pasta.name for pasta, posicao in lidas if posicao is None]
    if sem_posicao:
        return None, f"ingest_original_sem_posicao execucao={','.join(sem_posicao)}"
    distintas = {posicao for _, posicao in lidas if posicao is not None}
    if len(distintas) > 1:
        detalhe = f"candidatas={len(candidatas)} posicoes={len(distintas)}"
        return None, f"ingest_original_ambiguo {detalhe}"
    return distintas.pop(), ""


def _ate_a_posicao(atual: EstadoManifesto, posicao: _Posicao) -> tuple[LinhaManifesto, ...] | str:
    """As linhas do manifesto atual até a posição lida, ou o motivo de ele não as ter."""
    if posicao.linhas > len(atual.linhas):
        lido, no_manifesto = posicao.linhas, len(atual.linhas)
        return f"manifesto_menor_que_o_lido_pelo_ingest linhas={lido} atual={no_manifesto}"
    prefixo = EstadoManifesto(atual.linhas[: posicao.linhas])
    if prefixo.cabeca_sha256 != posicao.cabeca_sha256:
        return f"manifesto_diferente_do_lido_pelo_ingest linhas={posicao.linhas}"
    if prefixo.linhas and prefixo.linhas[-1].observacao is None:
        return f"posicao_do_ingest_no_meio_de_uma_transacao linhas={posicao.linhas}"
    return prefixo.linhas


def _recorte(atual: EstadoManifesto, mantidas: tuple[LinhaManifesto, ...]) -> Recorte:
    prefixo = EstadoManifesto(mantidas)
    return Recorte(
        len(atual.versoes) - len(prefixo.versoes),
        len(atual.observacoes) - len(prefixo.observacoes),
    )


def resolver_manifesto(
    raiz_ingest: Path, raiz_origem: Path, congelados: Iterable[DatasetRef]
) -> Resolucao:
    """O manifesto de `raiz_origem` até onde o `ingest` que produziu o SIA-PA congelado o leu.

    A execução é a de `raiz_ingest` cujo SIA-PA (a união dos `artifact_ids` dos conjuntos
    `sia_pa.v1`) é o dos `congelados`; candidatas com a mesma posição não são ambiguidade. Nada é
    gravado. Sem execução, com candidata sem posição legível, com posições diferentes ou com uma
    posição que o manifesto atual não tem (linhas a mais, hash da última diferente ou fim no meio
    de uma transação), `motivo` diz por quê.
    """
    candidatas, execucoes = _candidatas(raiz_ingest, _sia_pa(congelados))
    if not candidatas:
        return Resolucao(motivo=f"ingest_original_ausente execucoes={execucoes}")
    posicao, motivo = _posicao_unica(candidatas)
    if posicao is None:
        return Resolucao(motivo=motivo)
    try:
        atual = Manifesto(raiz_origem / NOME_MANIFESTO_AQUISICAO).ler()
    except ManifestoCorrompido:
        return Resolucao(motivo="manifesto_corrompido")
    mantidas = _ate_a_posicao(atual, posicao)
    if isinstance(mantidas, str):
        return Resolucao(motivo=mantidas)
    execucao = candidatas[-1].name
    logger.info(
        "manifesto_do_ingest execucao=%s linhas=%d de=%d",
        execucao,
        len(mantidas),
        len(atual.linhas),
    )
    return Resolucao(execucao, mantidas, _recorte(atual, mantidas))


def _gravar(raiz: Path, linhas: tuple[LinhaManifesto, ...]) -> None:
    raiz.mkdir(parents=True, exist_ok=True)
    caminho = raiz / NOME_MANIFESTO_AQUISICAO
    texto = "".join(f"{linha.model_dump_json()}\n" for linha in linhas)
    caminho.write_text(texto, encoding="utf-8")
    ancora = {"sequencia": len(linhas), "sha256": linhas[-1].sha256() if linhas else None}
    caminho.with_name(f"{caminho.name}.ancora").write_text(json.dumps(ancora), encoding="utf-8")


def gravar_manifesto(raiz_origem: Path, raiz_destino: Path, resolucao: Resolucao) -> None:
    """Grava em `raiz_destino` o manifesto até a posição resolvida, com a âncora.

    A cópia é o prefixo do original: mesma cadeia, e um manifesto válido.

    Raises:
        ConfigInvalida: resolução sem posição (a lista vazia de uma posição que não se sabe não é
            um manifesto vazio) ou `raiz_destino` igual a `raiz_origem` (o manifesto é
            append-only e nunca é regravado).
    """
    if resolucao.motivo:
        raise ConfigInvalida(f"manifesto_do_ingest_sem_posicao motivo={resolucao.motivo}")
    if raiz_origem.resolve() == raiz_destino.resolve():
        raise ConfigInvalida(f"manifesto_do_ingest_sobre_a_origem raiz={raiz_origem}")
    _gravar(raiz_destino, resolucao.linhas)
    logger.info("manifesto_gravado destino=%s linhas=%d", raiz_destino, len(resolucao.linhas))


def observacoes_do_manifesto(resolucao: Resolucao) -> list[str]:
    """Linhas de `observacoes` do `reproducao.json`: a posição usada e o que ficou de fora."""
    if resolucao.motivo:
        return []
    itens = [f"manifesto_do_ingest execucao={resolucao.execucao} linhas={len(resolucao.linhas)}"]
    if resolucao.recorte.artefatos:
        itens.append(f"artefatos_depois_do_ingest_ignorados n={resolucao.recorte.artefatos}")
    if resolucao.recorte.observacoes:
        itens.append(f"observacoes_depois_do_ingest_ignoradas n={resolucao.recorte.observacoes}")
    return itens
