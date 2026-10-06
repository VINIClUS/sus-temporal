"""Casos manuais SINTETICOS de NAO_APLICAVEL: instrumento fora da lista e vigência fora dela."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.base import DocRef
from sustemporal.contracts.temporal import TipoTempo, VigenciaDocumentada
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, regras_so_de_c, tabela
from tests.fixtures.regras_exemplos import cenario_base, registro

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "CASOS_NAO_APLICAVEL",
    "CasoNaoAplicavel",
    "avaliar_caso",
    "regras_com_vigencia",
    "vigencia_sintetica",
]

_DOCUMENTO = DocRef(
    doc_id="vigencia_sintetica", titulo="SINTETICO", estado="PENDENTE", proveniencia="INFERIDA"
)


def vigencia_sintetica(inicio: str | None, fim: str | None) -> VigenciaDocumentada:
    """Vigência SINTETICA pela competência de atendimento (limites inclusivos, nulo aberto)."""
    return VigenciaDocumentada(
        inicio=inicio, fim=fim, referente_a=TipoTempo.ATENDIMENTO, documento=_DOCUMENTO
    )


def regras_com_vigencia(inicio: str | None, fim: str | None) -> list[RuleSpec]:
    vigencia = vigencia_sintetica(inicio, fim)
    return [regra.model_copy(update={"vigencia": vigencia}) for regra in carregar_regras()]


@dataclass(frozen=True)
class CasoNaoAplicavel:
    """Registro e regras do caso; consulta e parâmetros da evidência APLICABILIDADE esperada."""

    linha: dict[str, str | None]
    regras: Callable[[], list[RuleSpec]]
    query_id: str
    parametros: dict[str, str]


CASOS_NAO_APLICAVEL = {
    "instrumento_fora_da_lista": CasoNaoAplicavel(
        registro(instrumento="I"),
        regras_so_de_c,
        "aplicabilidade.instrumento",
        {"instrumento": "I"},
    ),
    "antes_do_inicio_da_vigencia": CasoNaoAplicavel(
        registro(),
        partial(regras_com_vigencia, "202002", None),
        "aplicabilidade.vigencia",
        {"competencia": "202001"},
    ),
    "depois_do_fim_da_vigencia": CasoNaoAplicavel(
        registro(),
        partial(regras_com_vigencia, None, "201912"),
        "aplicabilidade.vigencia",
        {"competencia": "202001"},
    ),
}


def avaliar_caso(
    tmp_path: Path, nome: str, rule_id: str
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Avaliação de `rule_id` no caso, a evidência que ela cita e o dataset_id do SIA-PA."""
    caso = CASOS_NAO_APLICAVEL[nome]
    resultado = executar(tmp_path, cenario_base(caso.linha), regras=caso.regras())
    avaliacao = avaliacoes_por_chave(resultado)[(str(caso.linha["row_id"]), rule_id)]
    evidencias = {e["evidence_id"]: e for e in tabela(resultado, "evidencias.v1")}
    sia = next(d.dataset_id for d in resultado.entradas if d.schema_id == "sia_pa.v1")
    return avaliacao, evidencias[avaliacao["evidence_ids"]], sia
