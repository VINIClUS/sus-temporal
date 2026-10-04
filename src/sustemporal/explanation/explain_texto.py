"""Afirmações e texto legível por templates fixos (sem LLM).

Cada template declara as referências que exige; afirmação sem referência resolvível é erro.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from string import Template
from typing import TYPE_CHECKING

from sustemporal.contracts.base import json_canonico
from sustemporal.contracts.explanation import Afirmacao, TipoEvidencia
from sustemporal.contracts.rules import EstadoAvaliacao, ResultadoRegistro
from sustemporal.contracts.temporal import EstadoSelecao
from sustemporal.yamlio import carregar_texto_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts.explanation import Evidence, ExplanationBundle, Limitacao
    from sustemporal.contracts.rules import AgregadoRegistro, RuleEvaluation, RuleSpec
    from sustemporal.contracts.temporal import SelecaoVersao

__all__ = [
    "Contexto",
    "ModeloAfirmacao",
    "TemplateInvalido",
    "afirmacoes_do_registro",
    "afirmar",
    "carregar_templates",
    "exigir_referencias_completas",
    "renderizar_texto",
]

_TIPOS_REFERENCIA = {"regra", "regras", "evidencias", "artefatos"}
_TEMPLATE_DO_ESTADO = {
    EstadoAvaliacao.VIOLACAO: "regra.violacao",
    EstadoAvaliacao.CONFORME: "regra.conforme",
    EstadoAvaliacao.NAO_APLICAVEL: "regra.nao_aplicavel",
    EstadoAvaliacao.INCONCLUSIVO: "regra.inconclusiva",
}
_EVIDENCIA_DO_TEMPLATE = {
    "regra.violacao": TipoEvidencia.AUSENCIA_NA_FONTE,
    "regra.conforme": TipoEvidencia.VINCULO_ENCONTRADO,
    "regra.nao_aplicavel": TipoEvidencia.APLICABILIDADE,
}
_TEMPLATE_DO_RESULTADO = {
    ResultadoRegistro.ALERTA: "registro.alerta",
    ResultadoRegistro.SEM_VIOLACAO_VERIFICADA: "registro.sem_violacao",
    ResultadoRegistro.ABSTENCAO: "registro.abstencao",
}


class TemplateInvalido(ValueError):
    """Template desconhecido, mal formado ou sem referência resolvível no bundle."""


@dataclass(frozen=True)
class ModeloAfirmacao:
    template_id: str
    texto: Template
    referencias: tuple[str, ...]


@dataclass(frozen=True)
class Contexto:
    """Dados da execução que os templates citam."""

    run_id: str
    row_id: str
    metodo: str
    politica_id: str
    origem: str


def _texto_templates() -> str:
    raiz = resources.files("sustemporal.explanation")
    return raiz.joinpath("templates", "afirmacoes.yaml").read_text(encoding="utf-8")


@cache
def _documento() -> dict[str, object]:
    documento = carregar_texto_yaml(_texto_templates())
    if not isinstance(documento, dict) or documento.get("versao") != "1":
        raise TemplateInvalido("templates_versao_invalida")
    return documento


def carregar_templates() -> dict[str, ModeloAfirmacao]:
    """Templates de afirmação por `template_id`.

    Raises:
        TemplateInvalido: tipo de referência fora da allowlist ou template sem referência.
    """
    brutos = _documento()["templates"]
    if not isinstance(brutos, dict):
        raise TemplateInvalido("templates_mal_formados")
    modelos = {}
    for template_id, bruto in brutos.items():
        referencias = tuple(bruto["referencias"])
        if not referencias or not set(referencias) <= _TIPOS_REFERENCIA:
            raise TemplateInvalido(f"template_referencias_invalidas template={template_id}")
        modelos[template_id] = ModeloAfirmacao(template_id, Template(bruto["texto"]), referencias)
    return modelos


def _limitacoes() -> dict[str, str]:
    brutas = _documento()["limitacoes"]
    if not isinstance(brutas, dict):
        raise TemplateInvalido("limitacoes_mal_formadas")
    return {str(chave): str(valor) for chave, valor in brutas.items()}


def _modelo(template_id: str) -> ModeloAfirmacao:
    modelo = carregar_templates().get(template_id)
    if modelo is None:
        raise TemplateInvalido(f"template_desconhecido template={template_id}")
    return modelo


def _preencher(modelo: ModeloAfirmacao, valores: Mapping[str, object]) -> str:
    try:
        return modelo.texto.substitute({chave: str(valor) for chave, valor in valores.items()})
    except (KeyError, ValueError) as erro:
        raise TemplateInvalido(
            f"template_com_campo_sem_valor template={modelo.template_id} campo={erro}"
        ) from erro


def _resolver(
    modelo: ModeloAfirmacao, candidatos: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    referencias: list[str] = []
    for tipo in modelo.referencias:
        resolvidas = candidatos.get(tipo, ())
        if not resolvidas:
            raise TemplateInvalido(
                f"template_sem_referencia template={modelo.template_id} tipo={tipo}"
            )
        referencias.extend(r for r in resolvidas if r not in referencias)
    return tuple(referencias)


def _valores_evidencia(evidencia: Evidence) -> dict[str, object]:
    return {
        "query_id": evidencia.query_id,
        "sql_sha256": evidencia.sql_sha256,
        "parametros": json_canonico(dict(evidencia.parametros)),
        "dataset_id": evidencia.dataset_id,
        "hash_logico": evidencia.hash_logico,
        "artefatos": ";".join(evidencia.artifact_ids) or "nenhuma",
        "cobertura": evidencia.cobertura,
        "integridade": evidencia.integridade,
        "n_resultados": evidencia.n_resultados,
        "chaves": json_canonico(list(evidencia.chaves_amostra)),
    }


def afirmar(
    template_id: str,
    avaliacao: RuleEvaluation,
    *,
    evidencias: Mapping[str, Evidence],
    contexto: Contexto | None = None,
) -> Afirmacao:
    """Afirmação de uma avaliação; templates com `evidencias` exigem evidência citada e presente.

    Raises:
        TemplateInvalido: template desconhecido ou referência não resolvível.
    """
    modelo = _modelo(template_id)
    citadas = [evidencias[i] for i in avaliacao.evidence_ids if i in evidencias]
    if len(citadas) != len(avaliacao.evidence_ids):
        raise TemplateInvalido(f"template_sem_referencia template={template_id} tipo=evidencias")
    referencias = _resolver(
        modelo,
        {"regra": (avaliacao.rule_id,), "evidencias": tuple(e.evidence_id for e in citadas)},
    )
    valores: dict[str, object] = {
        "rule_id": avaliacao.rule_id,
        "versao": avaliacao.versao,
        "motivos": ";".join(avaliacao.motivos) or "nenhum",
        "aplicabilidade": avaliacao.aplicabilidade,
        "politica_id": contexto.politica_id if contexto else avaliacao.politica_id,
    }
    tipo = _EVIDENCIA_DO_TEMPLATE.get(template_id)
    if tipo is not None:
        principal = next((e for e in citadas if e.tipo is tipo), None)
        if principal is None:
            raise TemplateInvalido(
                f"template_sem_referencia template={template_id} tipo_evidencia={tipo}"
            )
        valores |= _valores_evidencia(principal)
    return Afirmacao(
        texto=_preencher(modelo, valores), template_id=template_id, referencias=referencias
    )


def _afirmar_selecao(avaliacao: RuleEvaluation, selecao: SelecaoVersao) -> Afirmacao:
    escolhida = selecao.estado is EstadoSelecao.SELECIONADA
    modelo = _modelo("selecao.escolhida" if escolhida else "selecao.nao_escolhida")
    referencias = _resolver(
        modelo, {"regra": (avaliacao.rule_id,), "artefatos": tuple(selecao.artifact_ids)}
    )
    valores = {
        "rule_id": avaliacao.rule_id,
        "fonte": selecao.fonte,
        "politica_id": avaliacao.politica_id,
        "artefatos": ";".join(selecao.artifact_ids) or "nenhuma",
        "base": selecao.base or "nao_resolvida",
        "competencia": selecao.competencia_requerida or "nao_resolvida",
        "estado": selecao.estado,
        "motivo": selecao.motivo,
    }
    return Afirmacao(
        texto=_preencher(modelo, valores), template_id=modelo.template_id, referencias=referencias
    )


def _afirmar_resultado(
    agregado: AgregadoRegistro, avaliacoes: tuple[RuleEvaluation, ...], contexto: Contexto
) -> Afirmacao:
    modelo = _modelo(_TEMPLATE_DO_RESULTADO[agregado.resultado])
    referencias = _resolver(modelo, {"regras": tuple(a.rule_id for a in avaliacoes)})
    valores = {
        "row_id": contexto.row_id,
        "politica_id": contexto.politica_id,
        "violacoes": ";".join(agregado.violacoes) or "nenhuma",
        "conformes": ";".join(agregado.conformes) or "nenhuma",
        "inconclusivas": ";".join(agregado.inconclusivas) or "nenhuma",
    }
    return Afirmacao(
        texto=_preencher(modelo, valores), template_id=modelo.template_id, referencias=referencias
    )


def afirmacoes_do_registro(
    agregado: AgregadoRegistro,
    avaliacoes: tuple[RuleEvaluation, ...],
    evidencias: Mapping[str, Evidence],
    contexto: Contexto,
) -> tuple[Afirmacao, ...]:
    """Resultado do registro, depois, por regra, o estado e as seleções temporais."""
    afirmacoes = [_afirmar_resultado(agregado, avaliacoes, contexto)]
    for avaliacao in avaliacoes:
        template_id = _TEMPLATE_DO_ESTADO[avaliacao.estado]
        afirmacoes.append(afirmar(template_id, avaliacao, evidencias=evidencias, contexto=contexto))
        afirmacoes.extend(_afirmar_selecao(avaliacao, s) for s in avaliacao.selecoes)
    return tuple(afirmacoes)


def exigir_referencias_completas(bundle: ExplanationBundle) -> None:
    """Afirmação de regra cita as evidências da avaliação; seleção escolhida, suas versões."""
    raise NotImplementedError


def renderizar_texto(
    bundle: ExplanationBundle, contexto: Contexto, regras: Mapping[str, RuleSpec]
) -> str:
    """Relatório legível: cabeçalho, afirmações com referências, regras e limitações."""
    cabecalho = Template(str(_documento()["cabecalho"])).substitute(
        origem=contexto.origem,
        run_id=contexto.run_id,
        row_id=contexto.row_id,
        metodo=contexto.metodo,
        politica_id=contexto.politica_id,
    )
    linhas = [cabecalho, "", "Afirmações:"]
    linhas += [f"- {a.texto} [ref: {', '.join(a.referencias)}]" for a in bundle.afirmacoes]
    linhas += ["", "Regras e referências:"]
    for avaliacao in bundle.avaliacoes:
        regra = regras[avaliacao.rule_id]
        linhas.append(
            f"- {regra.rule_id} {regra.versao} ({regra.estado}): referência "
            f"{regra.referencia.doc_id} ({regra.referencia.proveniencia}, "
            f"{regra.referencia.confirmacao})"
        )
    linhas += ["", "Limitações:"]
    textos = _limitacoes()
    linhas += [f"- {limitacao}: {textos[limitacao]}" for limitacao in _ordenadas(bundle)]
    return "\n".join(linhas) + "\n"


def _ordenadas(bundle: ExplanationBundle) -> list[Limitacao]:
    return sorted(bundle.limitacoes, key=str)
