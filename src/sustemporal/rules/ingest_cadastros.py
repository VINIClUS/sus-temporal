"""Cadastros do contexto do `validate --ingest`: só entram os que o registro e o corte confirmam.

Os esquemas de `CADASTROS_DO_CONTEXTO` (CNES ST) não são lidos por regra alguma; as precondições das
operações dos contrafactuais os leem. Como na produção, cada artefato deve estar no registro e, por
competência do arquivo, a seleção do T06 até o `corte_observacao` deve trazer exatamente os
artefatos da pasta. Ao contrário dela, só a seleção completa (`SELECIONADA`) vale: a produção aceita
`INCOMPLETA` e a marca na cobertura, mas ausência cadastral não pode vir de arquivo parcial. O
conjunto que não passa sai do contexto, com um log por conjunto; nunca recusa a execução, porque a
avaliação das regras não depende dele.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import EstadoSelecao
from sustemporal.rules.ingest_selecao import selecao_da_competencia

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.temporal import SelecaoVersao
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["CADASTROS_DO_CONTEXTO", "cadastros_aceitos"]

logger = logging.getLogger(__name__)

CADASTROS_DO_CONTEXTO = {"cnes_estabelecimento.v1": FamiliaFonte.CNES_ST}


def _divergencia(competencia: str, selecao: SelecaoVersao, da_pasta: set[str]) -> str | None:
    """Por que a seleção não confirma os artefatos da pasta; `None` se confirma."""
    if selecao.estado is not EstadoSelecao.SELECIONADA:
        return (
            f"selecao_nao_aceita competencia={competencia} estado={selecao.estado} "
            f"detalhe={selecao.motivo}"
        )
    selecionadas = set(selecao.artifact_ids)
    if selecionadas != da_pasta:
        return (
            f"artefatos_diferentes_da_selecao competencia={competencia} "
            f"pasta={sorted(da_pasta)} selecionados={sorted(selecionadas)}"
        )
    return None


def _competencias_divergentes(
    conjuntos: list[DatasetRef], fonte: FamiliaFonte, registro: RegistroTemporal, config: RunConfig
) -> dict[str, str]:
    """Competência do arquivo → divergência entre a seleção do T06 e os artefatos da pasta."""
    por_competencia: dict[str, set[str]] = defaultdict(set)
    for ref in conjuntos:
        for artefato in ref.artifact_ids:
            if artefato in registro.versoes:
                competencia = str(registro.versoes[artefato].chave.competencia_arquivo)
                por_competencia[competencia].add(artefato)
    divergentes: dict[str, str] = {}
    for competencia, da_pasta in sorted(por_competencia.items()):
        selecao = selecao_da_competencia(registro, config, fonte, competencia)
        divergencia = _divergencia(competencia, selecao, da_pasta)
        if divergencia is not None:
            divergentes[competencia] = divergencia
    return divergentes


def _motivo(ref: DatasetRef, divergentes: dict[str, str], registro: RegistroTemporal) -> str | None:
    """Motivo de o conjunto não entrar no contexto; `None` se entra."""
    if not ref.artifact_ids:
        return "sem_artefatos"
    fora = sorted(a for a in ref.artifact_ids if a not in registro.versoes)
    if fora:
        return f"fora_do_registro artefatos={fora}"
    competencias = {str(registro.versoes[a].chave.competencia_arquivo) for a in ref.artifact_ids}
    return next((divergentes[c] for c in sorted(competencias) if c in divergentes), None)


def _confirmados(
    conjuntos: list[DatasetRef], fonte: FamiliaFonte, registro: RegistroTemporal, config: RunConfig
) -> list[DatasetRef]:
    divergentes = _competencias_divergentes(conjuntos, fonte, registro, config)
    aceitos: list[DatasetRef] = []
    for ref in conjuntos:
        motivo = _motivo(ref, divergentes, registro)
        if motivo is None:
            aceitos.append(ref)
        else:
            logger.warning(
                "cadastro_do_contexto_ignorado schema=%s dataset=%s motivo=%s",
                ref.schema_id,
                ref.dataset_id,
                motivo,
            )
    return aceitos


def cadastros_aceitos(
    auxiliares: dict[str, list[DatasetRef]], registro: RegistroTemporal, config: RunConfig
) -> dict[str, list[DatasetRef]]:
    """`auxiliares` sem os conjuntos de cadastro que o registro e o corte não confirmam.

    Só os esquemas de `CADASTROS_DO_CONTEXTO` são conferidos; os auxiliares das regras seguem
    para a seleção por regra do motor. Nada é recusado: o que não passa é registrado em log.
    """
    return {
        schema_id: (
            _confirmados(conjuntos, CADASTROS_DO_CONTEXTO[schema_id], registro, config)
            if schema_id in CADASTROS_DO_CONTEXTO
            else conjuntos
        )
        for schema_id, conjuntos in auxiliares.items()
    }
