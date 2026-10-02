"""Manifesto append-only em JSONL com cadeia de hash."""

from __future__ import annotations

import contextlib
import fcntl
import json
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
    """Manifesto JSONL e sua âncora (`<nome>.ancora`: sequência e hash da última linha gravada).

    A cadeia protege as linhas do meio; a âncora, a remoção ou reescrita das linhas finais. A
    âncora pode ficar atrás do manifesto (queda entre as duas escritas), nunca à frente.
    """

    def __init__(self, caminho: Path) -> None:
        self.caminho = caminho
        self.ancora = caminho.with_name(f"{caminho.name}.ancora")

    def _partes(self) -> tuple[str, str]:
        if not self.caminho.exists():
            return "", ""
        texto = self.caminho.read_text(encoding="utf-8")
        corte = texto.rfind("\n") + 1
        return texto[:corte], texto[corte:]

    def _ler_ancora(self) -> tuple[object, object]:
        try:
            ancora = json.loads(self.ancora.read_text(encoding="utf-8"))
            return ancora["sequencia"], ancora["sha256"]
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise ManifestoCorrompido(f"manifesto_ancora_ilegivel caminho={self.ancora}") from erro

    def _conferir_ancora(self, estado: EstadoManifesto) -> None:
        if not estado.linhas:
            return
        sequencia, sha256 = self._ler_ancora()
        if not isinstance(sequencia, int) or not 1 <= sequencia <= len(estado.linhas):
            raise ManifestoCorrompido(f"manifesto_ancora_alem_do_fim sequencia={sequencia}")
        if estado.linhas[sequencia - 1].sha256() != sha256:
            raise ManifestoCorrompido(f"manifesto_ancora_divergente sequencia={sequencia}")

    def ler(self) -> EstadoManifesto:
        """Lê e confere a cadeia inteira e a âncora.

        Raises:
            ManifestoCorrompido: cadeia, sequência ou referências incoerentes, linha ilegível,
                âncora ausente ou divergente, ou fragmento final de escrita interrompida.
        """
        completas, fragmento = self._partes()
        if fragmento:
            raise ManifestoCorrompido(f"manifesto_sem_quebra_final caminho={self.caminho}")
        estado = _verificar(completas.splitlines())
        self._conferir_ancora(estado)
        return estado

    def _separar_fragmento(self) -> None:
        """Separa o fragmento de uma escrita interrompida, se a âncora cobre o resto inteiro."""
        completas, fragmento = self._partes()
        if not fragmento:
            return
        estado = _verificar(completas.splitlines())
        self._conferir_ancora(estado)
        if estado.linhas and self._ler_ancora()[0] != len(estado.linhas):
            raise ManifestoCorrompido(f"manifesto_fragmento_sem_ancora caminho={self.caminho}")
        destino = self.caminho.with_name(f"{self.caminho.name}.fragmento.{len(estado.linhas)}")
        destino.write_text(fragmento, encoding="utf-8")
        os.truncate(self.caminho, len(completas.encode("utf-8")))
        logger.warning("manifesto_fragmento_separado destino=%s", destino)

    def _gravar_ancora(self, linha: LinhaManifesto) -> None:
        temporario = self.ancora.with_name(f"{self.ancora.name}.tmp")
        conteudo = {"sequencia": linha.sequencia, "sha256": linha.sha256()}
        temporario.write_text(json.dumps(conteudo), encoding="utf-8")
        os.replace(temporario, self.ancora)

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

    def preparar(self) -> EstadoManifesto:
        """Separa fragmento de escrita interrompida (se seguro) e confere o manifesto.

        Raises:
            ManifestoCorrompido: o manifesto existente não passa na verificação.
        """
        with self._travado():
            self._separar_fragmento()
            return self.ler()

    def registrar(
        self, observacao: ArtifactObservation, versao: ArtifactVersion | None = None
    ) -> None:
        """Acrescenta a versão (se nova) e a observação, sob trava exclusiva.

        Raises:
            ManifestoCorrompido: o manifesto existente não passa na verificação.
        """
        with self._travado():
            self._separar_fragmento()
            estado = self.ler()
            novas = self._novas_linhas(estado, observacao, versao)
            with self.caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.writelines(f"{linha.model_dump_json()}\n" for linha in novas)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            self._gravar_ancora(novas[-1])
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
