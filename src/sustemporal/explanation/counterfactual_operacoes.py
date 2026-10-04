"""Catálogo fechado de operações cadastrais do CNES e seus efeitos simulados (T09).

Cada `op_id` do catálogo tem efeito, gerador de parâmetros e precondições escritos aqui; operação
sem efeito conhecido, precondição desconhecida ou dependência circular invalida o catálogo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.counterfactual import OperationSpec
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sustemporal.explanation.counterfactual_sobreposicao import Sobreposicao

__all__ = [
    "CATALOGO_OPERACOES",
    "CatalogoOperacoesInvalido",
    "Instancia",
    "aplicar",
    "carregar_operacoes",
    "instancias",
    "ordem_de_aplicacao",
    "ordenar_por_dependencia",
    "validar_operacoes",
]

logger = logging.getLogger(__name__)

CATALOGO_OPERACOES = Path(__file__).resolve().parents[3] / "catalog" / "operations.yaml"
PF = "cnes_estab_cbo.v1"
ST = "cnes_estabelecimento.v1"


class CatalogoOperacoesInvalido(ValueError):
    """Catálogo de operações com efeito, precondição ou dependência desconhecidos."""


@dataclass(frozen=True, order=True)
class Instancia:
    """Operação do catálogo com parâmetros concretos para um registro."""

    op_id: str
    parametros: tuple[tuple[str, str], ...]

    @property
    def mapa(self) -> dict[str, str]:
        return dict(self.parametros)


def _pf_contagem(sob: Sobreposicao, cnes: str, cbo: str) -> int:
    return sob.contagem_pf(cnes, cbo)


def _st_presente(sob: Sobreposicao, cnes: str) -> bool | None:
    return sob.estabelecimento_no_st(cnes)


def _pre_estab_presente(sob: Sobreposicao, p: dict[str, str]) -> bool:
    return _st_presente(sob, p["cnes"]) is True


def _pre_estab_ausente(sob: Sobreposicao, p: dict[str, str]) -> bool:
    return _st_presente(sob, p["cnes"]) is False


def _pre_origem_com_vinculo(sob: Sobreposicao, p: dict[str, str]) -> bool:
    return _pf_contagem(sob, p["cnes"], p["cbo_origem"]) > 0


_PRECONDICOES: dict[str, Callable[[Sobreposicao, dict[str, str]], bool]] = {
    "ESTABELECIMENTO_NO_CNES_ST": _pre_estab_presente,
    "ESTABELECIMENTO_AUSENTE_NO_CNES_ST": _pre_estab_ausente,
    "CBO_ORIGEM_COM_VINCULO": _pre_origem_com_vinculo,
}


def _efeito_incluir(sob: Sobreposicao, p: dict[str, str]) -> None:
    sob.somar_pf(p["cnes"], p["cbo"], 1)


def _efeito_reclassificar(sob: Sobreposicao, p: dict[str, str]) -> None:
    sob.somar_pf(p["cnes"], p["cbo_origem"], -1)
    sob.somar_pf(p["cnes"], p["cbo"], 1)


def _efeito_cadastrar(sob: Sobreposicao, p: dict[str, str]) -> None:
    sob.incluir_st(p["cnes"])


def _parametros_par(_sob: Sobreposicao, cnes: str, cbo: str) -> list[dict[str, str]]:
    return [{"cnes": cnes, "cbo": cbo}]


def _parametros_reclassificar(sob: Sobreposicao, cnes: str, cbo: str) -> list[dict[str, str]]:
    origens = [c for c in sob.cbos_com_vinculo(cnes) if c != cbo]
    return [{"cnes": cnes, "cbo": cbo, "cbo_origem": origem} for origem in origens]


def _parametros_estab(_sob: Sobreposicao, cnes: str, _cbo: str) -> list[dict[str, str]]:
    return [{"cnes": cnes}]


@dataclass(frozen=True)
class _Efeito:
    schema_id: str
    parametros: Callable[[Sobreposicao, str, str], list[dict[str, str]]]
    aplicar: Callable[[Sobreposicao, dict[str, str]], None]
    precondicoes: frozenset[str]
    depende_de: frozenset[str] = frozenset()


_CADASTRAR = "CADASTRAR_ESTABELECIMENTO_NO_CNES"
_NO_ST = "ESTABELECIMENTO_NO_CNES_ST"
_EFEITOS = {
    "INCLUIR_CBO_NO_ESTABELECIMENTO": _Efeito(
        PF, _parametros_par, _efeito_incluir, frozenset({_NO_ST}), frozenset({_CADASTRAR})
    ),
    "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO": _Efeito(
        PF,
        _parametros_reclassificar,
        _efeito_reclassificar,
        frozenset({_NO_ST, "CBO_ORIGEM_COM_VINCULO"}),
        frozenset({_CADASTRAR}),
    ),
    _CADASTRAR: _Efeito(
        ST, _parametros_estab, _efeito_cadastrar, frozenset({"ESTABELECIMENTO_AUSENTE_NO_CNES_ST"})
    ),
}


def _validar_operacao(op: OperationSpec) -> None:
    """Efeito conhecido, mesmo alvo e precondições/dependências obrigatórias do `op_id`."""
    efeito = _EFEITOS.get(op.op_id)
    if efeito is None:
        raise CatalogoOperacoesInvalido(f"operacao_sem_efeito op={op.op_id}")
    if efeito.schema_id != op.alvo.schema_id:
        raise CatalogoOperacoesInvalido(f"operacao_alvo_incoerente op={op.op_id}")
    desconhecidas = set(op.precondicoes) - set(_PRECONDICOES)
    if desconhecidas:
        raise CatalogoOperacoesInvalido(
            f"precondicao_desconhecida op={op.op_id} nomes={sorted(desconhecidas)}"
        )
    if set(op.depende_de) - set(_EFEITOS):
        raise CatalogoOperacoesInvalido(f"dependencia_desconhecida op={op.op_id}")
    if not efeito.precondicoes <= set(op.precondicoes):
        faltando = sorted(efeito.precondicoes - set(op.precondicoes))
        raise CatalogoOperacoesInvalido(
            f"precondicao_obrigatoria_ausente op={op.op_id} nomes={faltando}"
        )
    if not efeito.depende_de <= set(op.depende_de):
        faltando = sorted(efeito.depende_de - set(op.depende_de))
        raise CatalogoOperacoesInvalido(
            f"dependencia_obrigatoria_ausente op={op.op_id} ops={faltando}"
        )


def validar_operacoes(operacoes: Sequence[OperationSpec]) -> tuple[OperationSpec, ...]:
    """Confere efeitos, precondições, dependências e ausência de ciclos.

    Raises:
        CatalogoOperacoesInvalido: operação repetida ou fora do catálogo fechado.
    """
    ids = [op.op_id for op in operacoes]
    if len(set(ids)) != len(ids):
        raise CatalogoOperacoesInvalido("operacao_repetida")
    for op in operacoes:
        _validar_operacao(op)
    ordenar_por_dependencia(operacoes)
    return tuple(sorted(operacoes, key=lambda op: op.op_id))


def ordem_de_aplicacao(passos: Sequence[Instancia], nivel: dict[str, int]) -> list[Instancia]:
    """Instâncias na ordem das dependências; empate pela própria instância."""
    return sorted(passos, key=lambda inst: (nivel[inst.op_id], inst))


def ordenar_por_dependencia(operacoes: Sequence[OperationSpec]) -> dict[str, int]:
    """Posição topológica de cada operação (dependências antes de quem depende).

    Raises:
        CatalogoOperacoesInvalido: dependência circular.
    """
    por_id = {op.op_id: op for op in operacoes}
    nivel: dict[str, int] = {}

    def visitar(op_id: str, caminho: frozenset[str]) -> int:
        if op_id in caminho:
            raise CatalogoOperacoesInvalido(f"dependencia_circular op={op_id}")
        if op_id not in nivel:
            dependencias = [d for d in por_id[op_id].depende_de if d in por_id]
            nivel[op_id] = 1 + max(
                (visitar(d, caminho | {op_id}) for d in dependencias), default=-1
            )
        return nivel[op_id]

    for op_id in sorted(por_id):
        visitar(op_id, frozenset())
    return nivel


def carregar_operacoes(caminho: Path = CATALOGO_OPERACOES) -> tuple[OperationSpec, ...]:
    """Operações do catálogo, validadas pelo contrato e pelos efeitos conhecidos.

    Raises:
        CatalogoOperacoesInvalido: catálogo sem versão 1 ou com operação fora do catálogo fechado.
    """
    conteudo = carregar_yaml(caminho)
    if not isinstance(conteudo, dict) or conteudo.get("versao") != "1":
        raise CatalogoOperacoesInvalido(f"catalogo_operacoes_sem_versao caminho={caminho}")
    operacoes = [OperationSpec.model_validate(item) for item in conteudo.get("operacoes") or []]
    validadas = validar_operacoes(operacoes)
    logger.info("catalogo_operacoes_carregado operacoes=%d", len(validadas))
    return validadas


def instancias(
    operacoes: Sequence[OperationSpec], sob: Sobreposicao, cnes: str, cbo: str
) -> list[Instancia]:
    """Instâncias parametrizadas pelo par CNES–CBO do registro e pelo estado inicial."""
    return [
        Instancia(op.op_id, tuple(sorted(parametros.items())))
        for op in operacoes
        for parametros in _EFEITOS[op.op_id].parametros(sob, cnes, cbo)
    ]


def aplicar(op: OperationSpec, instancia: Instancia, sob: Sobreposicao) -> bool:
    """Aplica a instância se todas as precondições valem no estado atual da sobreposição."""
    parametros = instancia.mapa
    if not all(_PRECONDICOES[nome](sob, parametros) for nome in op.precondicoes):
        return False
    _EFEITOS[op.op_id].aplicar(sob, parametros)
    return True
