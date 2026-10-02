"""Estratégias Hypothesis de cenários SINTETICOS pequenos para o diferencial e os metamórficos."""

from __future__ import annotations

from typing import TYPE_CHECKING

from hypothesis import strategies as st

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import DocRef
from sustemporal.contracts.temporal import MetodoId, TipoTempo, VigenciaDocumentada
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.regras_cenario import (
    COLUNAS_AUXILIARES,
    ESQUEMA_DA_FONTE,
    CenarioRegras,
    artefato,
    politica,
)
from tests.fixtures.regras_exemplos import FAMILIA_DA_REGRA

if TYPE_CHECKING:
    from sustemporal.contracts.rules import RuleSpec

__all__ = ["ARTEFATOS", "cenarios", "regras_variadas"]

ARTEFATOS = (artefato(1), artefato(2), artefato(3))
_ARTEFATO_SIA = artefato(9)
_INSTRUMENTOS = ("C", "C", "I", "Z", None)
_PROCEDIMENTOS = ("0301010072", "0202020202", None)
_CBOS = ("225125", "223505", None, "22512")
_CNES = ("1234567", "7654321", None)
_COMPETENCIAS = ("202001", "202002", None)
_ESTADOS_SELECAO = (
    *("SELECIONADA",) * 8,
    "AUSENTE",
    "AMBIGUA",
    "INCOMPLETA",
    "EM_QUARENTENA",
    "FORA_DO_CORTE",
    "NAO_RESOLVIDA",
    "SEM_LINHA",
)
_CONJUNTOS_SELECIONADOS = (
    *((ARTEFATOS[0],),) * 3,
    (ARTEFATOS[1],),
    (ARTEFATOS[0], ARTEFATOS[1]),
    (ARTEFATOS[2],),
)
_VALORES = {
    "artifact_id": ARTEFATOS[:2],
    "dt_competencia": ("202001",),
    "competencia_arquivo": ("202001",),
    "co_procedimento": (*_PROCEDIMENTOS[:2], *_PROCEDIMENTOS[:2], None),
    "co_ocupacao": (*_CBOS[:2], *_CBOS[:2], None),
    "cnes": (*_CNES[:2], *_CNES[:2], None),
    "cbo": (*_CBOS[:2], *_CBOS[:2], None),
    "n_vinculos": (0, 1, 2, None),
    "co_registro": ("01", "02", "01", "02", None),
}


@st.composite
def _registros(draw: st.DrawFn) -> tuple[dict[str, str | None], ...]:
    quantidade = draw(st.integers(min_value=1, max_value=5))
    return tuple(
        {
            "row_id": f"{_ARTEFATO_SIA}#{indice}",
            "artifact_id": _ARTEFATO_SIA,
            "instrumento": draw(st.sampled_from(_INSTRUMENTOS)),
            "procedimento": draw(st.sampled_from(_PROCEDIMENTOS)),
            "cbo": draw(st.sampled_from(_CBOS)),
            "cnes": draw(st.sampled_from(_CNES)),
            "competencia_atendimento": draw(st.sampled_from(_COMPETENCIAS)),
            "competencia_processamento": draw(st.sampled_from(_COMPETENCIAS)),
        }
        for indice in range(quantidade)
    )


def _linha_auxiliar(schema_id: str) -> st.SearchStrategy[dict[str, object]]:
    return st.fixed_dictionaries(
        {coluna: st.sampled_from(_VALORES[coluna]) for coluna in COLUNAS_AUXILIARES[schema_id]}
    )


def _auxiliares() -> st.SearchStrategy[dict[str, tuple[dict[str, object], ...]]]:
    return st.fixed_dictionaries(
        {
            schema_id: st.lists(_linha_auxiliar(schema_id), max_size=8).map(tuple)
            for schema_id in sorted(COLUNAS_AUXILIARES)
        }
    )


@st.composite
def _selecao(draw: st.DrawFn, row_id: str, rule_id: str) -> dict[str, str | None] | None:
    estado = draw(st.sampled_from(_ESTADOS_SELECAO))
    if estado == "SEM_LINHA":
        return None
    vazia = estado in {"AUSENTE", "NAO_RESOLVIDA"}
    minimo = 2 if estado == "AMBIGUA" else 1
    if vazia:
        artefatos: tuple[str, ...] = ()
    elif minimo == 1:
        artefatos = draw(st.sampled_from(_CONJUNTOS_SELECIONADOS))
    else:
        artefatos = tuple(draw(st.sets(st.sampled_from(ARTEFATOS), min_size=minimo)))
    resolvida = estado != "NAO_RESOLVIDA"
    return {
        "row_id": row_id,
        "rule_id": rule_id,
        "fonte": ESQUEMA_DA_FONTE[rule_id][0],
        "base": draw(st.sampled_from(("ATENDIMENTO", "PROCESSAMENTO"))) if resolvida else None,
        "competencia_requerida": "202001" if resolvida else None,
        "estado": estado,
        "artifact_ids": ";".join(sorted(artefatos)),
        "observation_ids": "",
        "motivo": "selecao_sintetica",
    }


def _cobertura() -> st.SearchStrategy[tuple[dict[str, str | None], ...] | None]:
    chaves = [
        (familia, instrumento, competencia, base)
        for familia in sorted(FAMILIA_DA_REGRA.values())
        for instrumento in ("C", "I")
        for competencia in ("202001", "202002")
        for base in ("ATENDIMENTO", "PROCESSAMENTO")
    ]
    estados = st.sampled_from(("DISPONIVEL", "DISPONIVEL", "INSUFICIENTE", "AUSENTE", None))
    linhas = st.tuples(*[estados for _ in chaves]).map(
        lambda valores: tuple(
            {
                "familia_regra": f,
                "instrumento": i,
                "competencia": c,
                "base_temporal": b,
                "estado": e,
                "motivo": None,
            }
            for (f, i, c, b), e in zip(chaves, valores, strict=True)
            if e is not None
        )
    )
    return st.integers(min_value=0, max_value=4).flatmap(
        lambda sorteio: st.none() if sorteio == 0 else linhas
    )


def _integridade() -> st.SearchStrategy[dict[str, EstadoIntegridade]]:
    estados = st.sampled_from(
        (*(EstadoIntegridade.OK,) * 4, EstadoIntegridade.QUARENTENA_TRUNCADO, None)
    )
    versoes = (*ARTEFATOS, _ARTEFATO_SIA)
    return st.tuples(*[estados for _ in versoes]).map(
        lambda valores: {a: e for a, e in zip(versoes, valores, strict=True) if e is not None}
    )


def _artefatos_registrados() -> st.SearchStrategy[dict[str, tuple[str, ...]]]:
    """Às vezes o conjunto declara versões sem nenhuma linha (escopo vazio)."""
    return st.sets(st.sampled_from(sorted(COLUNAS_AUXILIARES))).map(
        lambda nomes: dict.fromkeys(sorted(nomes), ARTEFATOS)
    )


@st.composite
def cenarios(draw: st.DrawFn) -> CenarioRegras:
    """Cenário pequeno com estados de seleção, cobertura, integridade e lacunas variados."""
    registros = draw(_registros())
    selecoes = []
    for linha in registros:
        for rule_id in sorted(ESQUEMA_DA_FONTE):
            entrada = draw(_selecao(str(linha["row_id"]), rule_id))
            if entrada is not None:
                selecoes.append(entrada)
    ausentes = draw(st.sets(st.sampled_from(("cbo", "cnes", "competencia_atendimento"))))
    omitidos = draw(st.sets(st.sampled_from(sorted(COLUNAS_AUXILIARES)), max_size=1))
    lacunas = draw(st.integers(min_value=0, max_value=3)) == 0
    return CenarioRegras(
        registros=registros,
        auxiliares=draw(_auxiliares()),
        selecoes=tuple(selecoes),
        cobertura=draw(_cobertura()),
        integridade=draw(_integridade()),
        politica=politica(draw(st.sampled_from((MetodoId.B_ATEND, MetodoId.M_TEMP)))),
        colunas_ausentes_registro=frozenset(ausentes) if lacunas else frozenset(),
        auxiliares_omitidos=frozenset(omitidos) if lacunas else frozenset(),
        artefatos_auxiliar=draw(_artefatos_registrados()),
    )


_DOCUMENTO = DocRef(
    doc_id="vigencia_sintetica", titulo="SINTETICO", estado="PENDENTE", proveniencia="INFERIDA"
)


@st.composite
def regras_variadas(draw: st.DrawFn) -> list[RuleSpec]:
    """Regras do catálogo com lista de instrumentos e vigência variadas (só SINTETICO)."""
    regras = []
    for regra in carregar_regras():
        instrumentos = draw(st.sampled_from((regra.instrumentos, ("C",), ("I", "Z"))))
        vigencia = draw(
            st.sampled_from(
                (
                    None,
                    VigenciaDocumentada(
                        inicio="202001",
                        fim="202001",
                        referente_a=TipoTempo.ATENDIMENTO,
                        documento=_DOCUMENTO,
                    ),
                    VigenciaDocumentada(
                        inicio="202002", referente_a=TipoTempo.PROCESSAMENTO, documento=_DOCUMENTO
                    ),
                )
            )
        )
        regras.append(regra.model_copy(update={"instrumentos": instrumentos, "vigencia": vigencia}))
    return regras
