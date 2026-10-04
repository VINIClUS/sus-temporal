"""Domínios de código e passo 8 (leiaute e escopo) do avaliador de referência.

Independente do motor SQL: depende só da biblioteca padrão e dos contratos
(docs/method/model.md §3, §3.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.rules import MotivoInconclusao, RequisitoFonte

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DOMINIO_DO_CAMPO", "ConjuntoAuxiliar", "escopo"]

_M = MotivoInconclusao

_COMPETENCIA = re.compile(r"[0-9]{4}(0[1-9]|1[0-2])")
_PROCEDIMENTO = re.compile(r"[0-9]{10}")
_CBO = re.compile(r"[0-9A-Z]{6}")
_CNES = re.compile(r"[0-9]{7}")

DOMINIO_DO_CAMPO: dict[str, re.Pattern[str]] = {
    "procedimento": _PROCEDIMENTO,
    "cbo": _CBO,
    "cnes": _CNES,
    "instrumento": re.compile(r"[CIPSAB]"),
    "competencia_atendimento": _COMPETENCIA,
    "competencia_processamento": _COMPETENCIA,
}

_DOMINIO_AUXILIAR: dict[str, re.Pattern[str]] = {
    "co_procedimento": _PROCEDIMENTO,
    "co_ocupacao": _CBO,
    "cbo": _CBO,
    "cnes": _CNES,
    "co_registro": re.compile(r"[0-9]{2}"),
    "dt_competencia": _COMPETENCIA,
    "competencia_arquivo": _COMPETENCIA,
}

_COLUNAS_DE_COMPETENCIA = ("dt_competencia", "competencia_arquivo")


@dataclass(frozen=True)
class ConjuntoAuxiliar:
    """Conjunto canônico auxiliar (DatasetRef) já carregado."""

    schema_id: str
    colunas: frozenset[str]
    artifact_ids: frozenset[str]
    linhas: tuple[Mapping[str, object], ...]


def _fora_do_dominio(valor: object, dominio: re.Pattern[str]) -> bool:
    if valor is None:
        return False
    return not (isinstance(valor, str) and dominio.fullmatch(valor))


def _leiaute_incompativel(conjunto: ConjuntoAuxiliar, requisito: RequisitoFonte) -> bool:
    """Coluna exigida ausente ou valor de chave/competência fora do domínio em qualquer linha."""
    if not {*requisito.campos, "artifact_id"} <= conjunto.colunas:
        return True
    dominios = [(c, d) for c, d in _DOMINIO_AUXILIAR.items() if c in conjunto.colunas]
    return any(
        _fora_do_dominio(linha.get(coluna), dominio)
        for linha in conjunto.linhas
        for coluna, dominio in dominios
    )


def _competencia_divergente(
    conjunto: ConjuntoAuxiliar, linhas: tuple[Mapping[str, object], ...], requerida: object
) -> bool:
    """Alguma linha do escopo com competência do conteúdo nula ou diferente da requerida."""
    colunas = [c for c in _COLUNAS_DE_COMPETENCIA if c in conjunto.colunas]
    if not colunas:
        return False
    coluna = colunas[0]
    return any(not isinstance(requerida, str) or linha.get(coluna) != requerida for linha in linhas)


def _falha_de_arquivo(
    conjunto: ConjuntoAuxiliar | None,
    requisito: RequisitoFonte,
    versoes: frozenset[str],
    integridade: Mapping[str, str],
) -> MotivoInconclusao | None:
    """Conjunto ausente, leiaute, versão fora do conjunto e quarentena, nessa ordem."""
    if conjunto is None:
        return _M.ARQUIVO_AUSENTE
    if _leiaute_incompativel(conjunto, requisito):
        return _M.LEIAUTE_INCOMPATIVEL
    if not versoes <= conjunto.artifact_ids:
        return _M.ARQUIVO_AUSENTE
    if any(integridade.get(v, "").startswith("QUARENTENA_") for v in versoes):
        return _M.ARQUIVO_EM_QUARENTENA
    return None


def escopo(
    conjunto: ConjuntoAuxiliar | None,
    requisito: RequisitoFonte,
    selecao: Mapping[str, object],
    versoes: frozenset[str],
    integridade: Mapping[str, str],
) -> tuple[MotivoInconclusao | None, tuple[Mapping[str, object], ...]]:
    """Passo 8 para uma fonte com seleção SELECIONADA; a primeira falha vale."""
    falha = _falha_de_arquivo(conjunto, requisito, versoes, integridade)
    if falha is not None or conjunto is None:
        return falha, ()
    linhas = tuple(linha for linha in conjunto.linhas if linha.get("artifact_id") in versoes)
    if _competencia_divergente(conjunto, linhas, selecao.get("competencia_requerida")):
        return _M.VIGENCIA_NAO_RESOLVIDA, ()
    if not linhas:
        return _M.COBERTURA_INSUFICIENTE, ()
    return None, linhas
