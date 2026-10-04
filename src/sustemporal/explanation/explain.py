"""Explicações com evidência rastreável (T08).

O pacote é montado só das saídas imutáveis da execução (`RunResult.saidas`, conferidas pelo hash
lógico) e das entradas que ela declara. Nenhuma explicação atribui causa oficial: uma regra em
VIOLACAO é um alerta do modelo, e resultado vazio não prova inexistência no mundo real.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.base import OrigemDados, hash_canonico
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.experiment import EstadoExecucao, TipoExecucao
from sustemporal.contracts.explanation import ExplanationBundle, Limitacao, TipoEvidencia
from sustemporal.contracts.rules import MotivoInconclusao
from sustemporal.duck import conectar
from sustemporal.explanation.evidence import (
    EvidenciaDivergente,
    exigir_reproducao,
    reexecutar_evidencias,
)
from sustemporal.explanation.explain_leitura import (
    ExplicacaoIndisponivel,
    SaidasRegistro,
    ler_registro,
    ler_saidas,
)
from sustemporal.explanation.explain_texto import (
    Contexto,
    afirmacoes_do_registro,
    exigir_referencias_completas,
    renderizar_texto,
)
from sustemporal.explanation.prov import ElementosProv, exportar, montar_documento
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256, sql_sha256
from sustemporal.rules.engine import montar_consulta

if TYPE_CHECKING:
    from sustemporal.contracts import RuleSpec, RunResult
    from sustemporal.contracts.explanation import Afirmacao
    from sustemporal.contracts.records import ProductionRecord
    from sustemporal.contracts.temporal import SelecaoVersao
    from sustemporal.explanation.evidence import Reexecucao
    from sustemporal.explanation.prov import DocumentoProv

__all__ = ["Explicacao", "ExplicacaoIndisponivel", "explain", "montar_explicacao"]

logger = logging.getLogger(__name__)

_MOTIVOS_DE_AUSENCIA = {MotivoInconclusao.ARQUIVO_AUSENTE, MotivoInconclusao.COBERTURA_INSUFICIENTE}
_EVIDENCIAS_DE_AUSENCIA = {TipoEvidencia.AUSENCIA_NA_FONTE, TipoEvidencia.FONTE_INCOMPLETA}


@dataclass(frozen=True)
class Explicacao:
    """Pacote, PROV-JSON canônico (cujo SHA-256 está no pacote), texto e reexecuções."""

    bundle: ExplanationBundle
    prov_json: str
    texto: str
    reexecucoes: tuple[Reexecucao, ...]
    elementos: ElementosProv


def _regras_da_execucao(
    run: RunResult, saidas: SaidasRegistro, regras: list[RuleSpec] | None
) -> dict[str, RuleSpec]:
    candidatas = regras if regras is not None else carregar_regras()
    avaliadas = {a.rule_id for a in saidas.avaliacoes}
    subconjunto = [r for r in candidatas if r.rule_id in avaliadas]
    if run.catalogo_regras_sha256 not in {
        catalogo_sha256(candidatas),
        catalogo_sha256(subconjunto),
    }:
        raise ExplicacaoIndisponivel(f"catalogo_diverge_da_execucao run={run.run_id}")
    por_id = {regra.rule_id: regra for regra in subconjunto}
    for avaliacao in saidas.avaliacoes:
        regra = por_id.get(avaliacao.rule_id)
        if regra is None or regra.versao != avaliacao.versao:
            raise ExplicacaoIndisponivel(
                f"versao_de_regra_divergente run={run.run_id} regra={avaliacao.rule_id}"
            )
    return por_id


def _exigir_sql_das_regras(saidas: SaidasRegistro, regras: dict[str, RuleSpec]) -> None:
    por_id = {e.evidence_id: e for e in saidas.evidencias}
    for avaliacao in saidas.avaliacoes:
        esperado = sql_sha256(montar_consulta(regras[avaliacao.rule_id]))
        for evidence_id in avaliacao.evidence_ids:
            evidencia = por_id.get(evidence_id)
            if evidencia is None:
                raise ExplicacaoIndisponivel(f"evidencia_citada_ausente evidencia={evidence_id}")
            if evidencia.sql_sha256 != esperado:
                raise EvidenciaDivergente(
                    f"evidencia_divergente evidencia={evidence_id} divergencias=['sql_sha256']"
                )


def _limitacoes(run: RunResult, saidas: SaidasRegistro) -> tuple[Limitacao, ...]:
    limitacoes = {Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL, Limitacao.RETROSPECTIVO}
    if any(a.selecoes for a in saidas.avaliacoes):
        limitacoes.add(Limitacao.RETRATO_MENSAL_NAO_DATA_EXATA)
    ausencia = any(e.tipo in _EVIDENCIAS_DE_AUSENCIA for e in saidas.evidencias)
    if ausencia or any(set(a.motivos) & _MOTIVOS_DE_AUSENCIA for a in saidas.avaliacoes):
        limitacoes.add(Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA)
    if run.origem_dados is OrigemDados.SINTETICO:
        limitacoes.add(Limitacao.DADOS_SINTETICOS)
    return tuple(sorted(limitacoes, key=str))


def _ler(
    run: RunResult, row_id: str, runtime: RuntimeConfig
) -> tuple[SaidasRegistro, ProductionRecord]:
    if run.tipo is not TipoExecucao.VALIDACAO:
        raise ExplicacaoIndisponivel(f"execucao_nao_e_validacao run={run.run_id} tipo={run.tipo}")
    if run.estado is EstadoExecucao.FALHOU:
        raise ExplicacaoIndisponivel(f"execucao_falhou run={run.run_id}")
    con = conectar(runtime)
    try:
        return ler_saidas(con, run, row_id), ler_registro(con, run, row_id)
    finally:
        con.close()


def _contexto(run: RunResult, row_id: str) -> Contexto:
    return Contexto(
        run_id=run.run_id,
        row_id=row_id,
        metodo=str(run.metodo),
        politica_id=run.politica_id or "nao_informada",
        origem=str(run.origem_dados),
    )


def _selecoes(saidas: SaidasRegistro) -> tuple[SelecaoVersao, ...]:
    unicas: list[SelecaoVersao] = []
    for avaliacao in saidas.avaliacoes:
        unicas.extend(s for s in avaliacao.selecoes if s not in unicas)
    return tuple(unicas)


def _bundle(
    run: RunResult,
    row_id: str,
    registro: ProductionRecord,
    saidas: SaidasRegistro,
    *,
    prov: DocumentoProv,
    afirmacoes: tuple[Afirmacao, ...],
) -> ExplanationBundle:
    limitacoes = _limitacoes(run, saidas)
    identidade = {
        "run": run.run_id,
        "row": row_id,
        "prov": prov.sha256,
        "afirmacoes": [a.model_dump(mode="json") for a in afirmacoes],
        "limitacoes": [str(limitacao) for limitacao in limitacoes],
    }
    try:
        return ExplanationBundle(
            bundle_id=f"exp_{hash_canonico(identidade)[:40]}",
            run_id=run.run_id,
            row_id=row_id,
            registro=registro,
            avaliacoes=saidas.avaliacoes,
            selecoes=_selecoes(saidas),
            evidencias=saidas.evidencias,
            prov_n=prov.provn,
            prov_json_sha256=prov.sha256,
            afirmacoes=afirmacoes,
            limitacoes=limitacoes,
        )
    except ValidationError as erro:
        detalhe = erro.errors()[0]["msg"]
        raise ExplicacaoIndisponivel(f"bundle_invalido detalhe={detalhe}") from erro


def montar_explicacao(
    run: RunResult,
    row_id: str,
    *,
    regras: list[RuleSpec] | None = None,
    runtime: RuntimeConfig | None = None,
) -> Explicacao:
    """Pacote, PROV e texto de um registro; reexecuta cada evidência antes de citá-la.

    Raises:
        ExplicacaoIndisponivel: execução, saída, catálogo ou registro incoerentes ou ausentes.
        EvidenciaDivergente: reexecução que não reproduz resultado, hash ou SQL da evidência.
    """
    runtime = runtime or RuntimeConfig()
    saidas, registro = _ler(run, row_id, runtime)
    regras_usadas = _regras_da_execucao(run, saidas, regras)
    _exigir_sql_das_regras(saidas, regras_usadas)
    conjuntos = {dataset.dataset_id: dataset for dataset in run.entradas}
    reexecucoes = reexecutar_evidencias(saidas.evidencias, conjuntos, runtime=runtime)
    exigir_reproducao(reexecucoes)
    contexto = _contexto(run, row_id)
    evidencias = {e.evidence_id: e for e in saidas.evidencias}
    afirmacoes = afirmacoes_do_registro(saidas.agregado, saidas.avaliacoes, evidencias, contexto)
    elementos = ElementosProv(
        run=run,
        registro=registro,
        avaliacoes=saidas.avaliacoes,
        evidencias=saidas.evidencias,
        regras=regras_usadas,
        reexecucoes_sql={r.evidence_id: r.sql_sha256 for r in reexecucoes},
    )
    prov = exportar(montar_documento(elementos))
    bundle = _bundle(run, row_id, registro, saidas, prov=prov, afirmacoes=afirmacoes)
    exigir_referencias_completas(bundle)
    logger.info("explicacao_montada run=%s bundle=%s", run.run_id, bundle.bundle_id)
    return Explicacao(
        bundle=bundle,
        prov_json=prov.json,
        texto=renderizar_texto(bundle, contexto, regras_usadas),
        reexecucoes=reexecucoes,
        elementos=elementos,
    )


def explain(
    run: RunResult,
    row_id: str,
    *,
    regras: list[RuleSpec] | None = None,
    runtime: RuntimeConfig | None = None,
) -> ExplanationBundle:
    """Monta o pacote de explicação de um registro avaliado (ver `montar_explicacao`)."""
    return montar_explicacao(run, row_id, regras=regras, runtime=runtime).bundle
