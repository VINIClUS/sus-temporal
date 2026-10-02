"""Manifesto append-only em JSONL com cadeia de hash."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
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


def _conferir_transacao(anterior: LinhaManifesto | None, linha: LinhaManifesto | None) -> None:
    """Toda VERSAO é seguida pela OBSERVACAO que a obteve (mesma transação)."""
    if anterior is None or anterior.versao is None:
        return
    observacao = None if linha is None else linha.observacao
    if observacao is None or observacao.artifact_id != anterior.versao.artifact_id:
        raise ManifestoCorrompido(f"manifesto_transacao_incompleta sequencia={anterior.sequencia}")


def _verificar(textos: list[str]) -> EstadoManifesto:
    linhas: list[LinhaManifesto] = []
    versoes: set[str] = set()
    observacoes: set[str] = set()
    for numero, texto in enumerate(textos, start=1):
        linha = _ler_linha(numero, texto)
        anterior = linhas[-1] if linhas else None
        _conferir_encadeamento(anterior, linha)
        _conferir_transacao(anterior, linha)
        _conferir_referencias(linha, versoes, observacoes)
        linhas.append(linha)
    _conferir_transacao(linhas[-1] if linhas else None, None)
    return EstadoManifesto(tuple(linhas))


def _termina_em_versao(textos: list[str]) -> bool:
    if not textos:
        return False
    try:
        return LinhaManifesto.model_validate_json(textos[-1]).tipo is TipoLinhaManifesto.VERSAO
    except ValidationError:
        return False


def _sincronizar_diretorio(pasta: Path) -> None:
    descritor = os.open(pasta, os.O_RDONLY)
    try:
        os.fsync(descritor)
    finally:
        os.close(descritor)


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
        """Âncora 0 marca manifesto criado sem linha confirmada; nunca à frente do arquivo."""
        sequencia = self._sequencia_ancorada(len(estado.linhas))
        if not self.ancora.exists():
            return
        _, sha256 = self._ler_ancora()
        esperado = estado.linhas[sequencia - 1].sha256() if sequencia else None
        if esperado != sha256:
            raise ManifestoCorrompido(f"manifesto_ancora_divergente sequencia={sequencia}")

    def ler(self) -> EstadoManifesto:
        """Lê e confere a cadeia inteira e a âncora num retrato único, sob trava compartilhada.

        Raises:
            ManifestoCorrompido: cadeia, sequência ou referências incoerentes, linha ilegível,
                âncora ausente ou divergente, ou fragmento final de escrita interrompida.
        """
        if not self.caminho.parent.is_dir():
            return EstadoManifesto()
        with self._travado(fcntl.LOCK_SH):
            return self._ler_sem_trava()

    def _ler_sem_trava(self) -> EstadoManifesto:
        completas, fragmento = self._partes()
        if fragmento:
            raise ManifestoCorrompido(f"manifesto_sem_quebra_final caminho={self.caminho}")
        estado = _verificar(completas.splitlines())
        self._conferir_ancora(estado)
        return estado

    def _sequencia_ancorada(self, total: int) -> int:
        if not self.ancora.exists():
            if total:
                raise ManifestoCorrompido(f"manifesto_sem_ancora caminho={self.ancora}")
            return 0
        sequencia, _ = self._ler_ancora()
        if not isinstance(sequencia, int) or not 0 <= sequencia <= total:
            raise ManifestoCorrompido(f"manifesto_ancora_alem_do_fim sequencia={sequencia}")
        return sequencia

    def _separar_fragmento(self) -> None:
        """Separa a transação interrompida: linhas após a âncora mais o fragmento final.

        Age quando há fragmento ou quando o arquivo termina numa VERSAO sem sua OBSERVACAO;
        as linhas até a âncora precisam passar na verificação.
        """
        completas, fragmento = self._partes()
        textos = completas.splitlines()
        if not fragmento and not _termina_em_versao(textos):
            return
        sequencia = self._sequencia_ancorada(len(textos))
        confirmadas = textos[:sequencia]
        self._conferir_ancora(_verificar(confirmadas))
        sufixo = "".join(f"{texto}\n" for texto in textos[sequencia:]) + fragmento
        destino = self._guardar_fragmento(sequencia, sufixo)
        _sincronizar_diretorio(self.caminho.parent)
        tamanho = sum(len(f"{texto}\n".encode()) for texto in confirmadas)
        with self.caminho.open("r+b") as arquivo:
            os.ftruncate(arquivo.fileno(), tamanho)
            os.fsync(arquivo.fileno())
        _sincronizar_diretorio(self.caminho.parent)
        logger.warning("manifesto_fragmento_separado destino=%s", destino)

    def _guardar_fragmento(self, sequencia: int, sufixo: str) -> Path:
        """Grava sem sobrescrever: o nome leva a sequência ancorada e o hash do conteúdo."""
        resumo = hashlib.sha256(sufixo.encode("utf-8")).hexdigest()[:16]
        destino = self.caminho.with_name(f"{self.caminho.name}.fragmento.{sequencia}.{resumo}")
        try:
            with destino.open("x", encoding="utf-8") as arquivo:
                arquivo.write(sufixo)
                arquivo.flush()
                os.fsync(arquivo.fileno())
        except FileExistsError as existente:
            if destino.read_text(encoding="utf-8") != sufixo:
                raise ManifestoCorrompido(
                    f"manifesto_fragmento_divergente destino={destino}"
                ) from existente
        return destino

    def _gravar_ancora(self, sequencia: int, sha256: str | None) -> None:
        """Âncora durável: fsync do temporário, `os.replace` e fsync do diretório pai."""
        temporario = self.ancora.with_name(f"{self.ancora.name}.tmp")
        with temporario.open("w", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps({"sequencia": sequencia, "sha256": sha256}))
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, self.ancora)
        _sincronizar_diretorio(self.ancora.parent)

    @contextlib.contextmanager
    def _travado(self, modo: int = fcntl.LOCK_EX) -> Iterator[None]:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        trava = self.caminho.with_name(f"{self.caminho.name}.trava")
        with trava.open("a") as arquivo:
            fcntl.flock(arquivo.fileno(), modo)
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
            return self._ler_sem_trava()

    def registrar(
        self, observacao: ArtifactObservation, versao: ArtifactVersion | None = None
    ) -> None:
        """Acrescenta a versão (se nova) e a observação, sob trava exclusiva.

        Raises:
            ManifestoCorrompido: o manifesto existente não passa na verificação.
        """
        with self._travado():
            self._separar_fragmento()
            estado = self._ler_sem_trava()
            if not estado.linhas and not self.ancora.exists():
                self._gravar_ancora(0, None)
            novas = self._novas_linhas(estado, observacao, versao)
            with self.caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.writelines(f"{linha.model_dump_json()}\n" for linha in novas)
                arquivo.flush()
                os.fsync(arquivo.fileno())
            self._gravar_ancora(novas[-1].sequencia, novas[-1].sha256())
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
