"""Busca de contrafactuais com limites explícitos (T09, plano §6).

Busca de custo uniforme sobre combinações de instâncias do catálogo fechado de operações, até
`max_operacoes` operações e `max_candidatos` candidatos simulados. Cada candidato é aplicado numa
sobreposição isolada e todas as regras afetadas são reavaliadas pelo motor em todos os registros;
só é solução o candidato que deixa as regras-alvo `CONFORME` sem criar violação nova. O resultado
é uma hipótese: não assegura aprovação nem afirma que uma competência encerrada pode mudar.
"""

from __future__ import annotations

import heapq
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.counterfactual import (
    Candidato,
    CounterfactualSearchResult,
    Minimalidade,
    MotivoParada,
    OperacaoAplicada,
    Orcamento,
)
from sustemporal.contracts.rules import EstadoAvaliacao
from sustemporal.contracts.temporal import CompetenciaArquivo, EstadoSelecao
from sustemporal.explanation.counterfactual_executabilidade import (
    aberta_coerente,
    classificar,
    competencia_do_relogio,
    competencia_fechada,
    condicoes,
)
from sustemporal.explanation.counterfactual_operacoes import (
    Instancia,
    aplicar,
    carregar_operacoes,
    instancias,
    ordem_de_aplicacao,
    ordenar_por_dependencia,
    validar_operacoes,
)
from sustemporal.explanation.counterfactual_sobreposicao import Sobreposicao

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sustemporal.contracts import (
        ExplanationBundle,
        OperationSpec,
        RuleSpec,
        RunConfig,
    )
    from sustemporal.explanation.counterfactual_contexto import ContextoContrafactual

__all__ = ["pioras", "search_counterfactuals"]

logger = logging.getLogger(__name__)

_FONTE_DO_ESQUEMA = {
    "cnes_estab_cbo.v1": FamiliaFonte.CNES_PF,
    "cnes_estabelecimento.v1": FamiliaFonte.CNES_ST,
}
_VIOLACAO = EstadoAvaliacao.VIOLACAO.value
_CONFORME = EstadoAvaliacao.CONFORME.value


@dataclass
class _Busca:
    """Estado da busca de um registro: espaço de instâncias, fronteira e soluções."""

    bundle: ExplanationBundle
    alvos: tuple[str, ...]
    regras: list[RuleSpec]
    operacoes: dict[str, OperationSpec]
    nivel: dict[str, int]
    sob: Sobreposicao
    fechada: bool | None
    base: dict[tuple[str, str], str]
    orcamento: Orcamento
    avisos: tuple[str, ...] = ()
    espaco: list[Instancia] = field(default_factory=list)
    fronteira: list[tuple[int, int, tuple[int, ...]]] = field(default_factory=list)
    solucoes: list[Candidato] = field(default_factory=list)
    avaliados: int = 0
    ultimo_custo: int = 0

    def custo(self, indice: int) -> int:
        return int(self.operacoes[self.espaco[indice].op_id].custo)

    def empilhar(self, indices: tuple[int, ...], custo: int) -> None:
        heapq.heappush(self.fronteira, (custo, len(indices), indices))

    def expandir(self, indices: tuple[int, ...], custo: int) -> None:
        if len(indices) >= self.orcamento.max_operacoes:
            return
        for proximo in range(indices[-1] + 1, len(self.espaco)):
            self.empilhar((*indices, proximo), custo + self.custo(proximo))


def _alvos(bundle: ExplanationBundle) -> tuple[str, ...]:
    alvos = sorted({a.rule_id for a in bundle.avaliacoes if a.estado is EstadoAvaliacao.VIOLACAO})
    if not alvos:
        raise ValueError(f"contrafactual_sem_violacao bundle={bundle.bundle_id}")
    return tuple(alvos)


def _regras_afetadas(
    contexto: ContextoContrafactual, alvos: tuple[str, ...], operacoes: Sequence[OperationSpec]
) -> list[RuleSpec]:
    """Regras-alvo e toda regra que lê algum conjunto que uma operação do catálogo altera."""
    alterados = {op.alvo.schema_id for op in operacoes}
    afetadas = [
        r
        for r in contexto.regras
        if r.rule_id in alvos or any(req.schema_id in alterados for req in r.requisitos_fonte)
    ]
    faltando = set(alvos) - {r.rule_id for r in afetadas}
    if faltando:
        raise ValueError(f"contrafactual_regra_alvo_fora_do_contexto regras={sorted(faltando)}")
    return sorted(afetadas, key=lambda r: r.rule_id)


def _selecoes_alvo(bundle: ExplanationBundle, alvos: tuple[str, ...]) -> dict[str, set[str]]:
    """Competências e versões selecionadas pelas regras-alvo, por fonte cadastral."""
    por_fonte: dict[str, set[str]] = {}
    for avaliacao in bundle.avaliacoes:
        if avaliacao.rule_id not in alvos:
            continue
        for selecao in avaliacao.selecoes:
            if selecao.estado is EstadoSelecao.SELECIONADA and selecao.competencia_requerida:
                por_fonte.setdefault("competencia", set()).add(str(selecao.competencia_requerida))
                por_fonte.setdefault(selecao.fonte.value, set()).update(selecao.artifact_ids)
    return por_fonte


def _competencia_e_artefatos(
    bundle: ExplanationBundle, alvos: tuple[str, ...]
) -> tuple[str | None, dict[str, tuple[str, ...]]]:
    selecoes = _selecoes_alvo(bundle, alvos)
    competencias = selecoes.get("competencia", set())
    competencia = next(iter(competencias)) if len(competencias) == 1 else None
    artefatos = {
        schema_id: tuple(sorted(selecoes.get(fonte.value, set())))
        for schema_id, fonte in _FONTE_DO_ESQUEMA.items()
    }
    return competencia, artefatos


def _admissiveis(
    operacoes: Sequence[OperationSpec], busca_fechada: bool | None, sob: Sobreposicao
) -> list[OperationSpec]:
    """Operações cujo alvo está na sobreposição e cuja competência permitida inclui a da busca."""
    return [
        op
        for op in operacoes
        if sob.editavel(op.alvo.schema_id)
        and (op.competencias_permitidas == "QUALQUER_HIPOTETICA" or busca_fechada is False)
    ]


def _ordem(busca: _Busca, indices: tuple[int, ...]) -> list[Instancia]:
    return ordem_de_aplicacao([busca.espaco[i] for i in indices], busca.nivel)


def _simular(busca: _Busca, passos: list[Instancia]) -> dict[tuple[str, str], str] | None:
    """Estados reavaliados, ou `None` se alguma precondição não vale (candidato inadmissível)."""
    busca.sob.reiniciar()
    for passo in passos:
        if not aplicar(busca.operacoes[passo.op_id], passo, busca.sob):
            return None
    return busca.sob.avaliar(busca.regras)


def pioras(
    base: dict[tuple[str, str], str], estados: dict[tuple[str, str], str]
) -> tuple[str, ...]:
    """Pares que eram `CONFORME` e deixam de ser sem virar violação (declarados)."""
    return tuple(
        f"inconclusao_nova row={row} regra={regra} estado={estado}"
        for (row, regra), estado in sorted(estados.items())
        if base.get((row, regra)) == _CONFORME and estado not in {_CONFORME, _VIOLACAO}
    )


def _candidato(
    busca: _Busca, passos: list[Instancia], custo: int, estados: dict[tuple[str, str], str]
) -> Candidato:
    row_id = busca.bundle.row_id
    resolve = all(estados.get((row_id, alvo)) == _CONFORME for alvo in busca.alvos)
    novas = sorted(
        f"row={row} regra={regra}"
        for (row, regra), estado in estados.items()
        if estado == _VIOLACAO and busca.base.get((row, regra)) != _VIOLACAO
    )
    specs = [busca.operacoes[p.op_id] for p in passos]
    competencia = str(busca.sob.competencia)
    executabilidade = classificar(specs, busca.fechada)
    return Candidato(
        operacoes=tuple(
            OperacaoAplicada(
                op_id=p.op_id, parametros=p.mapa, competencia=CompetenciaArquivo(competencia)
            )
            for p in passos
        ),
        custo=custo,
        resolve_alvo=resolve,
        novas_violacoes=tuple(novas),
        condicoes_pendentes=(
            *condicoes(specs, executabilidade, competencia),
            *pioras(busca.base, estados),
            *busca.avisos,
        ),
        executabilidade=executabilidade,
        regras_revalidadas=tuple(r.rule_id for r in busca.regras),
    )


def _explorar(busca: _Busca) -> MotivoParada:
    """Custo uniforme; para no fim do nível de menor custo com solução ou no orçamento."""
    for indice in range(len(busca.espaco)):
        busca.empilhar((indice,), busca.custo(indice))
    custo_solucao: int | None = None
    while busca.fronteira:
        custo = busca.fronteira[0][0]
        if custo_solucao is not None and custo > custo_solucao:
            return MotivoParada.MINIMO_ENCONTRADO
        if busca.avaliados >= busca.orcamento.max_candidatos:
            return MotivoParada.ORCAMENTO_ESGOTADO
        _, _, indices = heapq.heappop(busca.fronteira)
        busca.ultimo_custo = custo
        busca.expandir(indices, custo)
        passos = _ordem(busca, indices)
        estados = _simular(busca, passos)
        if estados is None:
            continue
        busca.avaliados += 1
        candidato = _candidato(busca, passos, custo, estados)
        if candidato.resolve_alvo and not candidato.novas_violacoes:
            busca.solucoes.append(candidato)
            custo_solucao = custo
    if custo_solucao is not None:
        return MotivoParada.MINIMO_ENCONTRADO
    if busca.avaliados == 0:
        return MotivoParada.SEM_OPERACAO_ADMISSIVEL
    return MotivoParada.ESPACO_ESGOTADO


def _minimalidade(busca: _Busca, motivo: MotivoParada) -> tuple[Minimalidade, int]:
    """Mínimo só com o nível da solução completo e sem combinação mais longa mais barata."""
    if not busca.solucoes:
        completo = busca.ultimo_custo
        if motivo is MotivoParada.ORCAMENTO_ESGOTADO:
            completo = busca.fronteira[0][0] - 1
        return Minimalidade.BUSCA_INCONCLUSIVA, max(completo, 0)
    menor = min(s.custo for s in busca.solucoes)
    if motivo is MotivoParada.ORCAMENTO_ESGOTADO:
        return Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE, busca.fronteira[0][0] - 1
    if len(busca.espaco) <= busca.orcamento.max_operacoes:
        return Minimalidade.MINIMO_NO_CATALOGO, menor
    menor_passo = min(busca.custo(i) for i in range(len(busca.espaco)))
    if menor < (busca.orcamento.max_operacoes + 1) * menor_passo:
        return Minimalidade.MINIMO_NO_CATALOGO, menor
    return Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE, menor


def _avisos(contexto: ContextoContrafactual, agora: datetime) -> tuple[str, ...]:
    """Limites que valem para todo candidato: revalidação restrita e evidência atual."""
    avisos = [f"revalidacao_restrita dataset={contexto.dataset.dataset_id}"]
    aberta = contexto.competencia_aberta_cnes
    if aberta is not None and not aberta_coerente(aberta, agora):
        avisos.append(
            f"competencia_aberta_inconsistente aberta={aberta} "
            f"relogio={competencia_do_relogio(agora)}"
        )
    return tuple(avisos)


def _preparar(
    bundle: ExplanationBundle,
    contexto: ContextoContrafactual,
    config: RunConfig,
    operacoes: Sequence[OperationSpec],
    sob: Sobreposicao,
) -> _Busca:
    alvos = _alvos(bundle)
    regras = _regras_afetadas(contexto, alvos, operacoes)
    sob.reiniciar()
    base = sob.avaliar(regras)
    if any(base.get((bundle.row_id, alvo)) != _VIOLACAO for alvo in alvos):
        raise ValueError(f"contrafactual_baseline_incoerente bundle={bundle.bundle_id}")
    competencia = sob.competencia
    agora = contexto.relogio()
    aberta = contexto.competencia_aberta_cnes
    fechada = competencia_fechada(competencia, aberta, agora) if competencia is not None else None
    admissiveis = _admissiveis(operacoes, fechada, sob)
    busca = _Busca(
        bundle=bundle,
        alvos=alvos,
        regras=regras,
        operacoes={op.op_id: op for op in operacoes},
        nivel=ordenar_por_dependencia(operacoes),
        sob=sob,
        fechada=fechada,
        base=base,
        orcamento=Orcamento(**config.contrafactual.model_dump()),
        avisos=_avisos(contexto, agora),
    )
    registro = bundle.registro
    if competencia is not None and registro.cnes and registro.cbo:
        busca.espaco = sorted(instancias(admissiveis, sob, registro.cnes, registro.cbo))
    return busca


def search_counterfactuals(
    bundle: ExplanationBundle,
    config: RunConfig,
    *,
    contexto: ContextoContrafactual | None = None,
    operacoes: Sequence[OperationSpec] | None = None,
) -> CounterfactualSearchResult:
    """Busca operações cadastrais de menor custo e revalida o conjunto afetado.

    `contexto` traz os insumos com que o motor avaliou o registro; `operacoes` substitui o
    catálogo `catalog/operations.yaml` (mesmos `op_id`, outros custos ou governança).

    Raises:
        ValueError: sem contexto, sem violação no bundle, baseline divergente do bundle ou
            catálogo de operações inválido.
        RevalidacaoFalhou: o motor falhou ao avaliar a sobreposição.
    """
    if contexto is None:
        raise ValueError(f"contrafactual_sem_contexto bundle={bundle.bundle_id}")
    catalogo = validar_operacoes(operacoes) if operacoes is not None else carregar_operacoes()
    alvos = _alvos(bundle)
    competencia, artefatos = _competencia_e_artefatos(bundle, alvos)
    with tempfile.TemporaryDirectory(prefix="sustemporal_contrafactual_") as temporario:
        raiz = Path(temporario)
        with Sobreposicao(
            contexto, config, raiz, competencia=competencia, artefatos=artefatos
        ) as sob:
            busca = _preparar(bundle, contexto, config, catalogo, sob)
            motivo = _explorar(busca)
    minimalidade, completo = _minimalidade(busca, motivo)
    logger.info(
        "contrafactual_buscado bundle=%s candidatos=%d solucoes=%d minimalidade=%s motivo=%s",
        bundle.bundle_id,
        busca.avaliados,
        len(busca.solucoes),
        minimalidade,
        motivo,
    )
    return CounterfactualSearchResult(
        bundle_id=bundle.bundle_id,
        regras_alvo=alvos,
        solucoes=tuple(busca.solucoes),
        minimalidade=minimalidade,
        orcamento=busca.orcamento,
        candidatos_avaliados=busca.avaliados,
        custo_max_explorado_completo=completo,
        motivo_parada=motivo,
    )
