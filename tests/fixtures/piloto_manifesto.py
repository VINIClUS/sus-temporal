"""Manifesto de aquisição sintético (SINTETICO): registra versões já gravadas no armazenamento."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import ArtifactObservation, ChaveArtefato, ResultadoTentativa

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts import ArtifactVersion

__all__ = ["registrar_falha", "registrar_versoes"]

_INSTANTE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def registrar_versoes(
    manifesto: Path, versoes: Iterable[ArtifactVersion], *, observado_em: datetime = _INSTANTE
) -> None:
    """Uma observação OBTIDO por versão, com relógio fixo."""
    destino = Manifesto(manifesto)
    for versao in versoes:
        semente = f"{versao.artifact_id}|{versao.localizador}".encode()
        observacao = ArtifactObservation(
            observation_id=f"obs_{hashlib.sha256(semente).hexdigest()[:32]}",
            chave=versao.chave,
            request_sha256=hashlib.sha256(versao.localizador.encode()).hexdigest(),
            observado_em=observado_em,
            resultado=ResultadoTentativa.OBTIDO,
            artifact_id=versao.artifact_id,
            sha256_obtido=versao.sha256,
            bytes_recebidos=versao.tamanho_bytes,
            ferramenta="sintetico",
            localizador=versao.localizador,
            integridade=versao.integridade,
            formato=versao.formato,
        )
        destino.registrar(observacao, versao)


def registrar_falha(
    manifesto: Path, chave: ChaveArtefato, resultado: ResultadoTentativa, localizador: str
) -> None:
    """Uma tentativa sem versão de conteúdo (ex.: NAO_ENCONTRADO), com relógio fixo."""
    semente = f"{chave.nome_original}|{resultado}|{localizador}".encode()
    observacao = ArtifactObservation(
        observation_id=f"obs_{hashlib.sha256(semente).hexdigest()[:32]}",
        chave=chave,
        request_sha256=hashlib.sha256(localizador.encode()).hexdigest(),
        observado_em=_INSTANTE,
        resultado=resultado,
        ferramenta="sintetico",
        localizador=localizador,
    )
    Manifesto(manifesto).registrar(observacao)
