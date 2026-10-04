"""Seleção explícita de versões por regra e fonte (T06).

A decisão para uma chave (fonte, competência exata, corte) é `selecionar_versao`; a seleção por
registro e a em lote (`temporal.lote`) usam a mesma decisão. Nunca há mês vizinho.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.cli import CATALOGO_PADRAO, NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.sources import carregar_catalogo
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
    from collections.abc import Callable, Iterable, Sequence

    from sustemporal.contracts import ProductionRecord, RuleSpec, RunConfig
    from sustemporal.contracts.artifacts import ArtifactObservation
    from sustemporal.contracts.temporal import CriterioTemporal, PoliticaTemporal

__all__ = [
    "criterio_da_fonte",
    "criterio_da_regra",
    "fontes_auxiliares",
    "motivo_pendencia",
    "motivo_sem_criterio",
    "nao_resolvida",
    "partes_esperadas_do_catalogo",
    "selecionar_versao",
    "select_snapshots",
    "unir_snapshots",
]

_INTEGRAS = {EstadoIntegridade.OK, EstadoIntegridade.NAO_VERIFICADO}
_COM_CONTEUDO_INTEGRO = {EstadoSelecao.SELECIONADA, EstadoSelecao.INCOMPLETA, EstadoSelecao.AMBIGUA}


@dataclass(frozen=True)
class _Parte:
    estado: EstadoSelecao
    artefatos: frozenset[str]
    observacoes: tuple[str, ...]
    descartadas: tuple[str, ...] = ()
    sem_versao: bool = False


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


def _integra(registro: RegistroTemporal, obs: ArtifactObservation) -> bool:
    return (
        obs.resultado is ResultadoTentativa.OBTIDO
        and obs.artifact_id is not None
        and _integridade(registro, obs) in _INTEGRAS
    )


def _avaliar_parte(
    registro: RegistroTemporal, observacoes: Sequence[ArtifactObservation]
) -> _Parte:
    """Por parte: um conteúdo íntegro obtido seleciona; dois ou mais divergentes são ambíguos.

    Conteúdo em quarentena ao lado de conteúdo íntegro não impede a seleção (regra pendente do
    G0), mas as observações descartadas ficam citadas no motivo.
    """
    integras = [
        o for o in observacoes if _integra(registro, o) and o.artifact_id in registro.versoes
    ]
    invalidas = [o for o in observacoes if o.sha256_obtido is not None and o not in integras]
    distintos = frozenset(o.artifact_id for o in integras if o.artifact_id is not None)
    if distintos:
        estado = EstadoSelecao.AMBIGUA if len(distintos) > 1 else EstadoSelecao.SELECIONADA
        descartadas = tuple(o.observation_id for o in invalidas)
        return _Parte(estado, distintos, tuple(o.observation_id for o in integras), descartadas)
    if invalidas:
        artefatos = frozenset(o.artifact_id for o in invalidas if o.artifact_id is not None)
        ids = tuple(o.observation_id for o in invalidas)
        sem_versao = any(_integra(registro, o) for o in invalidas)
        return _Parte(EstadoSelecao.EM_QUARENTENA, artefatos, ids, sem_versao=sem_versao)
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
    extras = {p for p in partes if p is not None} - esperadas
    if extras:
        return EstadoSelecao.INCOMPLETA, f"partes_nao_declaradas extras={','.join(sorted(extras))}"
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
        sem_versao = any(p.sem_versao for p in partes.values())
        motivo = "observacao_integra_sem_versao" if sem_versao else "conteudo_em_quarentena"
        return EstadoSelecao.EM_QUARENTENA, motivo
    if estados == {EstadoSelecao.AUSENTE}:
        return EstadoSelecao.AUSENTE, "sem_conteudo_obtido"
    if esperadas is not None or any(parte is not None for parte in partes):
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
    descartadas = sorted({o for p in partes.values() for o in p.descartadas})
    if descartadas:
        sufixo += f" descartadas_quarentena={','.join(descartadas)}"
    selecao = _selecao(
        criterio,
        competencia,
        estado,
        f"{motivo} {sufixo}",
        artefatos=tuple(artefatos),
        observacoes=tuple(sorted({o for p in partes.values() for o in p.observacoes})),
    )
    if estado in _COM_CONTEUDO_INTEGRO:
        selecao.confere(registro.versoes[a] for a in artefatos)
    return selecao


def criterio_da_fonte(politica: PoliticaTemporal, fonte: FamiliaFonte) -> CriterioTemporal | None:
    """Critério da política para a fonte; None em política NAO_RESOLVIDA ou sem critério."""
    if politica.tipo is TipoPolitica.NAO_RESOLVIDA:
        return None
    return next((c for c in politica.criterios if c.fonte is fonte), None)


def criterio_da_regra(
    politica: PoliticaTemporal, regra: RuleSpec, fonte: FamiliaFonte
) -> CriterioTemporal | None:
    raise NotImplementedError("criterio_da_regra")


def motivo_sem_criterio(fonte: FamiliaFonte) -> str:
    """Mesmo texto do motor (`rules/preparo.py`) para política sem critério para a fonte."""
    return f"politica_sem_criterio_para_a_fonte fonte={fonte}"


def motivo_pendencia(politica: PoliticaTemporal) -> str | None:
    """Política com documento pendente não seleciona, mas mantém base e competência requerida."""
    if politica.documento_pendente:
        return f"politica_documento_pendente politica={politica.politica_id}"
    return None


def fontes_auxiliares(rule: RuleSpec) -> list[FamiliaFonte]:
    """Fontes auxiliares sem repetição, na ordem da primeira ocorrência na regra."""
    fontes = (r.fonte for r in rule.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)
    return list(dict.fromkeys(fontes))


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
    criterio = criterio_da_fonte(politica, fonte)
    if criterio is None:
        return nao_resolvida(fonte, motivo_sem_criterio(fonte))
    base = _competencia_base(record, criterio.base)
    if base is None:
        return nao_resolvida(fonte, f"competencia_base_ausente base={criterio.base}")
    requerida = CompetenciaArquivo(base).deslocar(criterio.deslocamento_meses)
    pendencia = motivo_pendencia(politica)
    if pendencia is not None:
        return _selecao(criterio, requerida, EstadoSelecao.NAO_RESOLVIDA, pendencia)
    return selecionar_versao(registro, criterio, requerida, uf=uf, corte=corte)


def partes_esperadas_do_catalogo(
    config: RunConfig,
) -> dict[tuple[FamiliaFonte, str], frozenset[str]]:
    """Partes declaradas no catálogo de fontes da execução (`catalogos.fontes`), por competência.

    Raises:
        ConfigInvalida: catálogo ilegível ou inválido.
    """
    catalogo = carregar_catalogo(Path(config.catalogos.get("fontes", str(CATALOGO_PADRAO))))
    return {
        (item.fonte, competencia): frozenset(partes)
        for item in catalogo.fontes
        for competencia, partes in item.partes_esperadas.items()
    }


def _uf_da_execucao(config: RunConfig) -> str | None:
    """UF do piloto ou da vigilância; sem nenhuma, só fontes nacionais são consultadas."""
    if config.piloto is not None:
        return config.piloto.uf
    return config.vigilancia.uf if config.vigilancia is not None else None


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
    relogio: Callable[[], datetime] | None = None,
) -> SnapshotSet:
    """Seleciona as versões exigidas pela regra ou registra a abstenção.

    A política é a da execução (`config.politica_id`, senão a da regra). Com corte de observação
    já passado no `relogio`, o conjunto é congelado: observações posteriores ao corte não o
    alteram. Corte no futuro não congela.

    Raises:
        ConfigInvalida: política inexistente ou inválida.
        ManifestoCorrompido: manifesto padrão não passa na verificação.
    """
    if politica is None:
        politica_id = config.politica_id or rule.politica_id
        politica = carregar_politica(politica_id, politicas or DIRETORIO_POLITICAS)
    if registro is None:
        caminho = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
        registro = RegistroTemporal.de_manifesto(
            caminho, partes_esperadas=partes_esperadas_do_catalogo(config)
        )
    uf = _uf_da_execucao(config)
    corte = config.corte_observacao
    contexto = (registro, uf, corte)
    selecoes = tuple(
        _selecao_do_registro(record, fonte, politica, contexto) for fonte in fontes_auxiliares(rule)
    )
    return _conjunto(selecoes, corte, relogio)


def _agora() -> datetime:
    return datetime.now(UTC)


def _conjunto(
    selecoes: Iterable[SelecaoVersao],
    corte: datetime | None,
    relogio: Callable[[], datetime] | None,
) -> SnapshotSet:
    """Conjunto canônico (seleções e ids ordenados); só congela com corte já passado."""
    ordenadas = tuple(sorted(selecoes, key=_ordem))
    return SnapshotSet.criar(
        artifact_ids=_ordenados(ordenadas, "artifact_ids"),
        observation_ids=_ordenados(ordenadas, "observation_ids"),
        dataset_hashes=(),
        selecoes=ordenadas,
        corte_observacao=corte,
        congelado=corte is not None and corte <= (relogio or _agora)(),
    )


def _ordem(selecao: SelecaoVersao) -> tuple[str, ...]:
    base = "" if selecao.base is None else selecao.base.value
    competencia = (
        "" if selecao.competencia_requerida is None else selecao.competencia_requerida.valor
    )
    return (selecao.fonte.value, base, competencia, selecao.estado.value, selecao.motivo)


def unir_snapshots(
    conjuntos: Iterable[SnapshotSet], *, relogio: Callable[[], datetime] | None = None
) -> SnapshotSet:
    """`SnapshotSet` da execução: uma seleção por chave (fonte, base, competência requerida).

    Seleções iguais de registros diferentes se fundem; duas decisões diferentes para a mesma
    chave, ou cortes diferentes, são erro (o motor recusa chave repetida).

    Raises:
        ValueError: conjuntos com cortes diferentes ou decisões divergentes na mesma chave.
    """
    lista = list(conjuntos)
    cortes = {c.corte_observacao for c in lista}
    if len(cortes) > 1:
        raise ValueError("snapshots_com_cortes_diferentes")
    unicas = {s for c in lista for s in c.selecoes}
    chaves = [(s.fonte, s.base, s.competencia_requerida) for s in unicas if s.base is not None]
    if len(chaves) != len(set(chaves)):
        raise ValueError("snapshots_com_decisoes_divergentes_na_mesma_chave")
    return _conjunto(unicas, next(iter(cortes), None), relogio)
