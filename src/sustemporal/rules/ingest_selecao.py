"""Versões da produção do `validate --ingest` conferidas pelo seletor do T06."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
)
from sustemporal.errors import ConfigInvalida
from sustemporal.temporal.selector import selecionar_versao, uf_da_execucao

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["exigir_versao_selecionavel"]


def exigir_versao_selecionavel(
    artefatos: list[str], registro: RegistroTemporal, config: RunConfig
) -> None:
    """Pelo seletor do T06, a pasta traz exatamente as versões selecionadas até o corte."""
    criterio = CriterioTemporal(fonte=FamiliaFonte.SIA_PA, base=BaseTemporal.PROCESSAMENTO)
    por_competencia: dict[str, set[str]] = defaultdict(set)
    for artefato in artefatos:
        por_competencia[str(registro.versoes[artefato].chave.competencia_arquivo)].add(artefato)
    for competencia, da_pasta in sorted(por_competencia.items()):
        selecao = selecionar_versao(
            registro,
            criterio,
            CompetenciaArquivo(competencia),
            uf=uf_da_execucao(config),
            corte=config.corte_observacao,
        )
        if selecao.estado is EstadoSelecao.AMBIGUA:
            raise ConfigInvalida(
                f"producao_com_versoes_concorrentes competencia={competencia} "
                f"motivo={selecao.motivo}"
            )
        selecionadas = set(selecao.artifact_ids)
        if selecionadas and da_pasta - selecionadas:
            raise ConfigInvalida(
                f"producao_com_versao_nao_selecionada competencia={competencia} "
                f"artefatos={sorted(da_pasta - selecionadas)}"
            )
        if selecionadas - da_pasta:
            raise ConfigInvalida(
                f"producao_com_partes_ausentes competencia={competencia} "
                f"ausentes={sorted(selecionadas - da_pasta)}"
            )
