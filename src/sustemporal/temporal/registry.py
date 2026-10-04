"""Registro temporal: versões de conteúdo e histórico completo de observações (T06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.artifacts import ResultadoTentativa

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.base import FamiliaFonte
    from sustemporal.contracts.temporal import CompetenciaArquivo

__all__ = ["ORIGEM_INTERVALO", "IntervaloObservado", "RegistroTemporal", "registro_de"]

ORIGEM_INTERVALO = "OBSERVACAO_DA_PESQUISA"


@dataclass(frozen=True)
class IntervaloObservado:
    """Sequência contígua de observações do mesmo conteúdo, segundo a coleta da pesquisa.

    Não é histórico oficial de publicação: só diz quando a pesquisa viu o conteúdo.
    """

    artifact_id: str
    primeira_observacao: datetime
    ultima_observacao: datetime
    observation_ids: tuple[str, ...]
    origem: str = ORIGEM_INTERVALO


@dataclass(frozen=True)
class RegistroTemporal:
    """Histórico append-only como lido do manifesto; nada é resumido a first/last seen."""

    observacoes: tuple[ArtifactObservation, ...]
    versoes: Mapping[str, ArtifactVersion]
    partes_esperadas: Mapping[tuple[FamiliaFonte, str], frozenset[str]] = field(
        default_factory=dict
    )

    @classmethod
    def de_manifesto(
        cls,
        caminho: Path,
        *,
        partes_esperadas: Mapping[tuple[FamiliaFonte, str], frozenset[str]] | None = None,
    ) -> RegistroTemporal:
        """Lê o manifesto conferido (cadeia e âncora).

        Raises:
            ManifestoCorrompido: o manifesto não passa na verificação.
        """
        estado = Manifesto(caminho).ler()
        return cls(estado.observacoes, dict(estado.versoes), dict(partes_esperadas or {}))

    def observacoes_de(
        self, fonte: FamiliaFonte, uf: str | None, competencia: CompetenciaArquivo
    ) -> tuple[ArtifactObservation, ...]:
        """Observações de arquivos publicados (não listagens) da competência exata, por instante.

        Arquivo com UF só vale para a mesma UF; sem UF pedida, só fontes nacionais (sem UF).
        """
        escolhidas = [
            o
            for o in self.observacoes
            if o.chave.tipo_conteudo is None
            and o.chave.fonte is fonte
            and o.chave.competencia_arquivo == competencia
            and (o.chave.uf is None or o.chave.uf == uf)
        ]
        return tuple(sorted(escolhidas, key=lambda o: (o.observado_em, o.observation_id)))

    def intervalos(
        self,
        fonte: FamiliaFonte,
        uf: str | None,
        competencia: CompetenciaArquivo,
        *,
        parte: str | None = None,
    ) -> list[IntervaloObservado]:
        """Intervalos de seleção derivados da coleta: A, B, A dá três intervalos.

        Uma observação NAO_ENCONTRADO da mesma parte encerra o intervalo corrente.
        """
        intervalos: list[IntervaloObservado] = []
        aberto = False
        for obs in self.observacoes_de(fonte, uf, competencia):
            if obs.chave.parte != parte:
                continue
            if obs.resultado is ResultadoTentativa.NAO_ENCONTRADO:
                aberto = False
            if obs.artifact_id is None:
                continue
            ultimo = intervalos[-1] if intervalos and aberto else None
            aberto = True
            if ultimo is not None and ultimo.artifact_id == obs.artifact_id:
                intervalos[-1] = IntervaloObservado(
                    obs.artifact_id,
                    ultimo.primeira_observacao,
                    obs.observado_em,
                    (*ultimo.observation_ids, obs.observation_id),
                )
            else:
                intervalos.append(
                    IntervaloObservado(
                        obs.artifact_id, obs.observado_em, obs.observado_em, (obs.observation_id,)
                    )
                )
        return intervalos


def registro_de(
    observacoes: Iterable[ArtifactObservation], versoes: Iterable[ArtifactVersion]
) -> RegistroTemporal:
    return RegistroTemporal(tuple(observacoes), {v.artifact_id: v for v in versoes})
