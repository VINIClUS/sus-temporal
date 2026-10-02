"""Estratégia enviesada (revisão I4): muitas VIOLACAO e CONFORME para o diferencial SINTETICO."""

from __future__ import annotations

from hypothesis import strategies as st

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.temporal import MetodoId
from tests.fixtures.regras_cenario import (
    COLUNAS_AUXILIARES,
    ESQUEMA_DA_FONTE,
    CenarioRegras,
    artefato,
    coerente,
    politica,
)
from tests.fixtures.regras_exemplos import FAMILIA_DA_REGRA

__all__ = ["cenarios_enviesados"]

_A1, _A2, _SIA = artefato(1), artefato(2), artefato(9)
_PROCEDIMENTOS = ("0301010072", "0202020202")
_CBOS = ("225125", "223505")
_CNES = ("1234567", "7654321")
_COMPETENCIAS = ("202001", "202002")
_COMPETENCIAS_PESADAS = ("202001", "202001", "202001", "202002")
_VALORES: dict[str, tuple[object, ...]] = {
    "artifact_id": (_A1, _A2),
    "dt_competencia": ("202001",),
    "competencia_arquivo": ("202001",),
    "co_procedimento": _PROCEDIMENTOS,
    "co_ocupacao": _CBOS,
    "cnes": _CNES,
    "cbo": _CBOS,
    "n_vinculos": (1, 2),
    "co_registro": ("01", "02"),
}


def _com_nulo(valores: tuple[str, ...]) -> st.SearchStrategy[str | None]:
    """Nulo com peso 1/5 (domínio de 2 valores, cada um com peso 2)."""
    return st.sampled_from((*valores, *valores, None))


@st.composite
def _registro(draw: st.DrawFn, indice: int) -> dict[str, str | None]:
    return {
        "row_id": f"{_SIA}#{indice}",
        "artifact_id": _SIA,
        "instrumento": draw(st.sampled_from(("C", "C", "I", "I", None))),
        "procedimento": draw(_com_nulo(_PROCEDIMENTOS)),
        "cbo": draw(_com_nulo(_CBOS)),
        "cnes": draw(_com_nulo(_CNES)),
        "competencia_atendimento": draw(st.sampled_from(_COMPETENCIAS_PESADAS)),
        "competencia_processamento": draw(st.sampled_from(_COMPETENCIAS_PESADAS)),
    }


_SEM_NULO = frozenset({"artifact_id", "dt_competencia", "competencia_arquivo", "n_vinculos"})


def _valor_auxiliar(coluna: str) -> st.SearchStrategy[object]:
    valores = _VALORES[coluna]
    if coluna in _SEM_NULO:
        return st.sampled_from(valores)
    return st.sampled_from((*valores, *valores, None))


def _linha_auxiliar(schema_id: str) -> st.SearchStrategy[dict[str, object]]:
    return st.fixed_dictionaries(
        {coluna: _valor_auxiliar(coluna) for coluna in COLUNAS_AUXILIARES[schema_id]}
    )


@st.composite
def _selecao(draw: st.DrawFn, row_id: str, rule_id: str) -> dict[str, str | None]:
    estado = draw(st.sampled_from((*("SELECIONADA",) * 9, "AUSENTE", "EM_QUARENTENA")))
    artefatos = (
        "" if estado == "AUSENTE" else draw(st.sampled_from((_A1, _A1, _A1, f"{_A1};{_A2}", _A2)))
    )
    return {
        "row_id": row_id,
        "rule_id": rule_id,
        "fonte": ESQUEMA_DA_FONTE[rule_id][0],
        "base": "ATENDIMENTO",
        "competencia_requerida": "202001",
        "estado": estado,
        "artifact_ids": artefatos,
        "observation_ids": "",
        "motivo": "selecao_sintetica",
    }


def _cobertura() -> st.SearchStrategy[tuple[dict[str, str | None], ...]]:
    chaves = [
        (familia, instrumento, competencia, base)
        for familia in sorted(FAMILIA_DA_REGRA.values())
        for instrumento in ("C", "I")
        for competencia in _COMPETENCIAS
        for base in ("ATENDIMENTO", "PROCESSAMENTO")
    ]
    estados = st.sampled_from((*("DISPONIVEL",) * 8, "INSUFICIENTE", "AUSENTE"))
    return st.tuples(*[estados for _ in chaves]).map(
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
        )
    )


def _integridade() -> st.SearchStrategy[dict[str, EstadoIntegridade]]:
    estados = st.sampled_from(
        (
            *(EstadoIntegridade.OK,) * 6,
            EstadoIntegridade.NAO_VERIFICADO,
            EstadoIntegridade.QUARENTENA_CHECKSUM,
            None,
        )
    )
    versoes = (_A1, _A2, _SIA)
    return st.tuples(*[estados for _ in versoes]).map(
        lambda valores: {a: e for a, e in zip(versoes, valores, strict=True) if e is not None}
    )


@st.composite
def cenarios_enviesados(draw: st.DrawFn) -> CenarioRegras:
    """Domínios de 2 valores, seleção 9:1:1, cobertura 8:1:1, integridade OK com peso 6."""
    quantidade = draw(st.integers(min_value=1, max_value=5))
    registros = tuple(draw(_registro(indice)) for indice in range(quantidade))
    selecoes = tuple(
        draw(_selecao(str(linha["row_id"]), rule_id))
        for linha in registros
        for rule_id in sorted(ESQUEMA_DA_FONTE)
    )
    auxiliares = {
        nome: tuple(draw(st.lists(_linha_auxiliar(nome), min_size=2, max_size=8)))
        for nome in sorted(COLUNAS_AUXILIARES)
    }
    return coerente(
        CenarioRegras(
            registros=registros,
            auxiliares=auxiliares,
            selecoes=selecoes,
            cobertura=draw(_cobertura()),
            integridade=draw(_integridade()),
            politica=politica(MetodoId.B_ATEND),
        )
    )
