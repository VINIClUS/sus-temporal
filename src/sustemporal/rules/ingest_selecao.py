"""Versões da produção do `validate --ingest` pelo seletor do T06: conferência e incompletude."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
)
from sustemporal.duck import identificador_seguro
from sustemporal.errors import ConfigInvalida
from sustemporal.rules.conteudo import ConteudoDivergente
from sustemporal.temporal.selector import selecionar_versao, uf_da_execucao

if TYPE_CHECKING:
    from collections.abc import Mapping

    import duckdb

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.temporal import SelecaoVersao
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["exigir_versao_selecionavel", "marcas_de_incompletude", "selecao_da_competencia"]

logger = logging.getLogger(__name__)

_ACEITAS = frozenset({EstadoSelecao.SELECIONADA, EstadoSelecao.INCOMPLETA})


def selecao_da_competencia(
    registro: RegistroTemporal, config: RunConfig, fonte: FamiliaFonte, competencia: str
) -> SelecaoVersao:
    """Seleção do T06 da fonte para a competência do arquivo, até o `corte_observacao`."""
    criterio = CriterioTemporal(fonte=fonte, base=BaseTemporal.PROCESSAMENTO)
    return selecionar_versao(
        registro,
        criterio,
        CompetenciaArquivo(competencia),
        uf=uf_da_execucao(config),
        corte=config.corte_observacao,
    )


def exigir_versao_selecionavel(
    artefatos: list[str], registro: RegistroTemporal, config: RunConfig
) -> dict[str, SelecaoVersao]:
    """Pelo seletor do T06, a pasta traz exatamente as versões selecionadas até o corte.

    Só a seleção completa (`SELECIONADA`) ou `INCOMPLETA` é aceita. Devolve, por competência do
    arquivo, as `INCOMPLETA` (parte esperada ausente, parte não declarada ou completude
    indeterminada); qualquer outro estado (ambíguo, em quarentena, fora do corte, ausente ou não
    resolvido) é recusado, nunca avaliado como produção comum.

    Raises:
        ConteudoDivergente: seleção de uma competência da pasta em estado não aceito.
        ConfigInvalida: versão da pasta não selecionada ou parte selecionada ausente da pasta.
    """
    por_competencia: dict[str, set[str]] = defaultdict(set)
    for artefato in artefatos:
        por_competencia[str(registro.versoes[artefato].chave.competencia_arquivo)].add(artefato)
    incompletas: dict[str, SelecaoVersao] = {}
    for competencia, da_pasta in sorted(por_competencia.items()):
        selecao = selecao_da_competencia(registro, config, FamiliaFonte.SIA_PA, competencia)
        if selecao.estado not in _ACEITAS:
            raise ConteudoDivergente(
                f"producao_com_selecao_nao_aceita competencia={competencia} "
                f"estado={selecao.estado} motivo={selecao.motivo}"
            )
        selecionadas = set(selecao.artifact_ids)
        if da_pasta - selecionadas:
            raise ConfigInvalida(
                f"producao_com_versao_nao_selecionada competencia={competencia} "
                f"artefatos={sorted(da_pasta - selecionadas)}"
            )
        if selecionadas - da_pasta:
            raise ConfigInvalida(
                f"producao_com_partes_ausentes competencia={competencia} "
                f"ausentes={sorted(selecionadas - da_pasta)}"
            )
        if selecao.estado is EstadoSelecao.INCOMPLETA:
            incompletas[competencia] = selecao
    return incompletas


def marcas_de_incompletude(
    con: duckdb.DuckDBPyConnection, tabela: str, incompletas: Mapping[str, SelecaoVersao]
) -> dict[str, str]:
    """Competência → motivo da marca `sia_pa_incompleto` derivada das seleções `INCOMPLETA`.

    Vale a competência do arquivo e, como na ingestão (`propagar_incompletude`), as competências de
    processamento que as linhas dos artefatos selecionados trazem em `tabela` (PA_MVM pode diferir
    do nome do arquivo).
    """
    alvo = identificador_seguro(tabela, {tabela})
    marcas = {
        competencia: f"selecao_incompleta {s.motivo}" for competencia, s in incompletas.items()
    }
    for competencia, selecao in incompletas.items():
        trazidas = con.execute(
            f"SELECT DISTINCT competencia_processamento FROM {alvo} "  # noqa: S608
            "WHERE competencia_processamento IS NOT NULL AND list_contains($a, artifact_id)",
            {"a": list(selecao.artifact_ids)},
        ).fetchall()
        for (valor,) in trazidas:
            via_arquivo = f"incompleto_via_arquivo competencia_arquivo={competencia}"
            marcas.setdefault(str(valor), via_arquivo)
    for competencia, motivo in sorted(marcas.items()):
        logger.info("sia_pa_incompleto_da_selecao competencia=%s motivo=%s", competencia, motivo)
    return marcas
