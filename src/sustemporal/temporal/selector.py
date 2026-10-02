"""Seleção explícita de versões por regra e fonte (T06).

A decisão para uma chave (fonte, competência exata, corte) é `selecionar_versao`; a seleção por
registro e a em lote (`temporal.lote`) usam a mesma decisão. Nunca há mês vizinho.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    EstadoSelecao,
    SelecaoVersao,
    SnapshotSet,
    TipoPolitica,
)
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica
from sustemporal.temporal.registry import RegistroTemporal

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from sustemporal.contracts import ProductionRecord, RuleSpec, RunConfig
    from sustemporal.contracts.artifacts import ArtifactObservation
    from sustemporal.contracts.temporal import CriterioTemporal, PoliticaTemporal

__all__ = [
    "criterio_ou_motivo",
    "fontes_auxiliares",
    "nao_resolvida",
    "selecionar_versao",
    "select_snapshots",
]

_INTEGRAS = {EstadoIntegridade.OK, EstadoIntegridade.NAO_VERIFICADO}


@dataclass(frozen=True)
class _Parte:
    estado: EstadoSelecao
    artefatos: frozenset[str]
    observacoes: tuple[str, ...]


def nao_resolvida(fonte: FamiliaFonte, motivo: str) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=fonte,
        base=None,
        competencia_requerida=None,
        estado=EstadoSelecao.NAO_RESOLVIDA,
        motivo=motivo,
    )


def _integridade(registro: RegistroTemporal, obs: ArtifactObservation) -> EstadoIntegridade | None:
    if obs.integridade is not None:
        return obs.integridade
    versao = registro.versoes.get(obs.artifact_id or "")
    return None if versao is None else versao.integridade


def _avaliar_parte(
    registro: RegistroTemporal, observacoes: Sequence[ArtifactObservation]
) -> _Parte:
    """Por parte: um conteúdo íntegro obtido seleciona; dois ou mais divergentes são ambíguos."""
    integras = [
        o
        for o in observacoes
        if o.resultado is ResultadoTentativa.OBTIDO
        and o.artifact_id is not None
        and _integridade(registro, o) in _INTEGRAS
    ]
    distintos = frozenset(o.artifact_id for o in integras if o.artifact_id is not None)
    if distintos:
        estado = EstadoSelecao.AMBIGUA if len(distintos) > 1 else EstadoSelecao.SELECIONADA
        return _Parte(estado, distintos, tuple(o.observation_id for o in integras))
    invalidas = [o for o in observacoes if o.sha256_obtido is not None]
    if invalidas:
        artefatos = frozenset(o.artifact_id for o in invalidas if o.artifact_id is not None)
        ids = tuple(o.observation_id for o in invalidas)
        return _Parte(EstadoSelecao.EM_QUARENTENA, artefatos, ids)
    return _Parte(EstadoSelecao.AUSENTE, frozenset(), tuple(o.observation_id for o in observacoes))


def _estado_multipartes(
    partes: dict[str | None, _Parte], esperadas: frozenset[str] | None
) -> tuple[EstadoSelecao, str]:
    integras = {p for p, v in partes.items() if v.estado is EstadoSelecao.SELECIONADA}
    listadas = ",".join(sorted(p or "" for p in partes))
    if esperadas is None:
        return (
            EstadoSelecao.INCOMPLETA,
            f"partes_sem_declaracao completude=INDETERMINADA partes={listadas}",
        )
    faltantes = esperadas - {p for p in integras if p is not None}
    if faltantes:
        return EstadoSelecao.INCOMPLETA, f"partes_ausentes ausentes={','.join(sorted(faltantes))}"
    return EstadoSelecao.SELECIONADA, f"partes_completas partes={listadas}"


def _estado_combinado(
    partes: dict[str | None, _Parte], esperadas: frozenset[str] | None
) -> tuple[EstadoSelecao, str]:
    estados = {p.estado for p in partes.values()}
    if EstadoSelecao.AMBIGUA in estados:
        return EstadoSelecao.AMBIGUA, "republicacao_com_conteudo_divergente"
    if EstadoSelecao.EM_QUARENTENA in estados:
        return EstadoSelecao.EM_QUARENTENA, "conteudo_em_quarentena"
    if any(parte is not None for parte in partes):
        return _estado_multipartes(partes, esperadas)
    if EstadoSelecao.SELECIONADA in estados:
        return EstadoSelecao.SELECIONADA, "versao_unica_integra"
    return EstadoSelecao.AUSENTE, "sem_conteudo_obtido"


def _selecao(
    criterio: CriterioTemporal,
    competencia: CompetenciaArquivo,
    estado: EstadoSelecao,
    motivo: str,
    *,
    artefatos: tuple[str, ...] = (),
    observacoes: tuple[str, ...] = (),
) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=criterio.fonte,
        base=criterio.base,
        competencia_requerida=competencia,
        estado=estado,
        artifact_ids=artefatos,
        observation_ids=observacoes,
        motivo=motivo,
    )


def _no_corte(
    observacoes: Sequence[ArtifactObservation], corte: datetime | None
) -> list[ArtifactObservation]:
    return [o for o in observacoes if corte is None or o.observado_em <= corte]


def selecionar_versao(
    registro: RegistroTemporal,
    criterio: CriterioTemporal,
    competencia: CompetenciaArquivo,
    *,
    uf: str | None = None,
    corte: datetime | None = None,
) -> SelecaoVersao:
    """Decide a versão de uma fonte para uma competência exata, ou a abstenção."""
    todas = [
        o
        for o in registro.observacoes_de(criterio.fonte, uf, competencia)
        if criterio.canal is None or o.chave.canal is criterio.canal
    ]
    sufixo = f"fonte={criterio.fonte} competencia={competencia}"
    if not todas:
        return _selecao(criterio, competencia, EstadoSelecao.AUSENTE, f"sem_observacao {sufixo}")
    observadas = _no_corte(todas, corte)
    if not observadas:
        motivo = f"observada_so_apos_o_corte {sufixo}"
        return _selecao(criterio, competencia, EstadoSelecao.FORA_DO_CORTE, motivo)
    por_parte: dict[str | None, list[ArtifactObservation]] = defaultdict(list)
    for obs in observadas:
        por_parte[obs.chave.parte].append(obs)
    partes = {parte: _avaliar_parte(registro, obs) for parte, obs in por_parte.items()}
    esperadas = registro.partes_esperadas.get((criterio.fonte, competencia.valor))
    estado, motivo = _estado_combinado(partes, esperadas)
    artefatos = sorted({a for p in partes.values() for a in p.artefatos})
    selecao = _selecao(
        criterio,
        competencia,
        estado,
        f"{motivo} {sufixo}",
        artefatos=tuple(artefatos),
        observacoes=tuple(sorted({o for p in partes.values() for o in p.observacoes})),
    )
    selecao.confere(registro.versoes[a] for a in artefatos if a in registro.versoes)
    return selecao


def criterio_ou_motivo(politica: PoliticaTemporal, fonte: FamiliaFonte) -> CriterioTemporal | str:
    """Critério da política para a fonte, ou o motivo da abstenção (política sem suporte)."""
    if politica.tipo is TipoPolitica.NAO_RESOLVIDA:
        return f"politica_nao_resolvida politica={politica.politica_id}"
    if politica.documento_pendente:
        return f"politica_documento_pendente politica={politica.politica_id}"
    for criterio in politica.criterios:
        if criterio.fonte is fonte:
            return criterio
    return f"politica_sem_criterio politica={politica.politica_id} fonte={fonte}"


def fontes_auxiliares(rule: RuleSpec) -> list[FamiliaFonte]:
    return [r.fonte for r in rule.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA]


def _competencia_base(record: ProductionRecord, base: BaseTemporal) -> str | None:
    competencia = (
        record.competencia_atendimento
        if base is BaseTemporal.ATENDIMENTO
        else record.competencia_processamento
    )
    return None if competencia is None else competencia.valor


def _selecao_do_registro(
    record: ProductionRecord,
    fonte: FamiliaFonte,
    politica: PoliticaTemporal,
    contexto: tuple[RegistroTemporal, str | None, datetime | None],
) -> SelecaoVersao:
    registro, uf, corte = contexto
    criterio = criterio_ou_motivo(politica, fonte)
    if isinstance(criterio, str):
        return nao_resolvida(fonte, criterio)
    base = _competencia_base(record, criterio.base)
    if base is None:
        return nao_resolvida(fonte, f"competencia_base_ausente base={criterio.base}")
    requerida = CompetenciaArquivo(base).deslocar(criterio.deslocamento_meses)
    return selecionar_versao(registro, criterio, requerida, uf=uf, corte=corte)


def _ordenados(selecoes: Iterable[SelecaoVersao], campo: str) -> tuple[str, ...]:
    return tuple(sorted({valor for s in selecoes for valor in getattr(s, campo)}))


def select_snapshots(
    record: ProductionRecord,
    rule: RuleSpec,
    config: RunConfig,
    *,
    registro: RegistroTemporal | None = None,
    politica: PoliticaTemporal | None = None,
    politicas: Path | None = None,
) -> SnapshotSet:
    """Seleciona as versões exigidas pela regra ou registra a abstenção.

    A política é a da execução (`config.politica_id`, senão a da regra). Com corte de observação,
    o conjunto é congelado: observações posteriores ao corte não o alteram.

    Raises:
        ConfigInvalida: política inexistente ou inválida.
        ManifestoCorrompido: manifesto padrão não passa na verificação.
    """
    if politica is None:
        politica_id = config.politica_id or rule.politica_id
        politica = carregar_politica(politica_id, politicas or DIRETORIO_POLITICAS)
    if registro is None:
        caminho = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
        registro = RegistroTemporal.de_manifesto(caminho)
    uf = config.piloto.uf if config.piloto is not None else None
    corte = config.corte_observacao
    contexto = (registro, uf, corte)
    selecoes = tuple(
        _selecao_do_registro(record, fonte, politica, contexto) for fonte in fontes_auxiliares(rule)
    )
    return SnapshotSet.criar(
        artifact_ids=_ordenados(selecoes, "artifact_ids"),
        observation_ids=_ordenados(selecoes, "observation_ids"),
        dataset_hashes=(),
        selecoes=selecoes,
        corte_observacao=corte,
        congelado=corte is not None,
    )


def unir_snapshots(conjuntos: Iterable[SnapshotSet]) -> SnapshotSet:
    raise NotImplementedError
