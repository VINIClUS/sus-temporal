"""Manifesto append-only em JSONL com cadeia de hash."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.artifacts import (
    ArtifactObservation,
    ArtifactVersion,
    LinhaManifesto,
    TipoLinhaManifesto,
)
from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = ["EstadoManifesto", "Manifesto", "ManifestoCorrompido"]

logger = logging.getLogger(__name__)


class ManifestoCorrompido(FalhaOperacionalErro):
    """Linha reescrita, removida, reordenada ou ilegível."""


@dataclass(frozen=True)
class EstadoManifesto:
    linhas: tuple[LinhaManifesto, ...] = ()

    @cached_property
    def versoes(self) -> dict[str, ArtifactVersion]:
        return {x.versao.artifact_id: x.versao for x in self.linhas if x.versao is not None}

    @cached_property
    def observacoes(self) -> tuple[ArtifactObservation, ...]:
        return tuple(x.observacao for x in self.linhas if x.observacao is not None)

    @property
    def cabeca_sha256(self) -> str | None:
        """Hash da última linha; guardado fora do manifesto, ancora também a última linha."""
        return self.linhas[-1].sha256() if self.linhas else None


def _ler_linha(numero: int, texto: str) -> LinhaManifesto:
    try:
        return LinhaManifesto.model_validate_json(texto)
    except ValidationError as erro:
        raise ManifestoCorrompido(f"manifesto_linha_ilegivel linha={numero}") from erro


def _conferir_encadeamento(anterior: LinhaManifesto | None, linha: LinhaManifesto) -> None:
    sequencia = 1 if anterior is None else anterior.sequencia + 1
    if linha.sequencia != sequencia:
        raise ManifestoCorrompido(
            f"manifesto_cadeia_sequencia esperada={sequencia} obtida={linha.sequencia}"
        )
    esperado = None if anterior is None else anterior.sha256()
    if linha.anterior_sha256 != esperado:
        raise ManifestoCorrompido(f"manifesto_cadeia_hash_divergente sequencia={linha.sequencia}")


def _conferir_referencias(linha: LinhaManifesto, versoes: set[str], observacoes: set[str]) -> None:
    if linha.versao is not None:
        if linha.versao.artifact_id in versoes:
            raise ManifestoCorrompido(f"manifesto_versao_repetida sequencia={linha.sequencia}")
        versoes.add(linha.versao.artifact_id)
    if linha.observacao is not None:
        observacao = linha.observacao
        if observacao.observation_id in observacoes:
            raise ManifestoCorrompido(f"manifesto_observacao_repetida sequencia={linha.sequencia}")
        if observacao.artifact_id is not None and observacao.artifact_id not in versoes:
            raise ManifestoCorrompido(
                f"manifesto_observacao_sem_versao sequencia={linha.sequencia}"
            )
        observacoes.add(observacao.observation_id)


def _verificar(textos: list[str]) -> EstadoManifesto:
    linhas: list[LinhaManifesto] = []
    versoes: set[str] = set()
    observacoes: set[str] = set()
    for numero, texto in enumerate(textos, start=1):
        linha = _ler_linha(numero, texto)
        _conferir_encadeamento(linhas[-1] if linhas else None, linha)
        _conferir_referencias(linha, versoes, observacoes)
        linhas.append(linha)
    return EstadoManifesto(tuple(linhas))


class Manifesto:
    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho

    def ler(self) -> EstadoManifesto:
        """Lê e confere a cadeia inteira.

        Raises:
            ManifestoCorrompido: cadeia, sequência ou referências incoerentes, linha ilegível
                ou arquivo sem quebra de linha final (escrita interrompida).
        """
        if not self.caminho.exists():
            return EstadoManifesto()
        texto = self.caminho.read_text(encoding="utf-8")
        if texto and not texto.endswith("\n"):
            raise ManifestoCorrompido(f"manifesto_sem_quebra_final caminho={self.caminho}")
        return _verificar(texto.splitlines())

    @contextlib.contextmanager
    def _travado(self) -> Iterator[None]:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        trava = self.caminho.with_name(f"{self.caminho.name}.trava")
        with trava.open("a") as arquivo:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)

    def registrar(
        self, observacao: ArtifactObservation, versao: ArtifactVersion | None = None
    ) -> None:
        """Acrescenta a versão (se nova) e a observação, sob trava exclusiva.

        Raises:
            ManifestoCorrompido: o manifesto existente não passa na verificação.
        """
        with self._travado():
            estado = self.ler()
            novas = self._novas_linhas(estado, observacao, versao)
            with self.caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.writelines(f"{linha.model_dump_json()}\n" for linha in novas)
                arquivo.flush()
                os.fsync(arquivo.fileno())
        logger.info(
            "manifesto_registrado observacao=%s resultado=%s artefato=%s",
            observacao.observation_id,
            observacao.resultado,
            observacao.artifact_id,
        )

    @staticmethod
    def _novas_linhas(
        estado: EstadoManifesto,
        observacao: ArtifactObservation,
        versao: ArtifactVersion | None,
    ) -> list[LinhaManifesto]:
        anterior = estado.linhas[-1] if estado.linhas else None
        conteudos: list[tuple[TipoLinhaManifesto, dict[str, object]]] = []
        if versao is not None and versao.artifact_id not in estado.versoes:
            conteudos.append((TipoLinhaManifesto.VERSAO, {"versao": versao}))
        conteudos.append((TipoLinhaManifesto.OBSERVACAO, {"observacao": observacao}))
        versoes = set(estado.versoes)
        observacoes = {o.observation_id for o in estado.observacoes}
        novas: list[LinhaManifesto] = []
        for tipo, conteudo in conteudos:
            linha = LinhaManifesto.model_validate(
                {
                    "sequencia": 1 if anterior is None else anterior.sequencia + 1,
                    "tipo": tipo,
                    "anterior_sha256": None if anterior is None else anterior.sha256(),
                    **conteudo,
                }
            )
            _conferir_referencias(linha, versoes, observacoes)
            novas.append(linha)
            anterior = linha
        return novas
