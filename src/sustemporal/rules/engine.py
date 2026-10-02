"""Motor SQL de avaliação de regras (T07): V(r, g, S, p) por registro e regra (model.md)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.experiment import EstadoExecucao, RunResult, TipoExecucao
from sustemporal.contracts.temporal import TipoPolitica
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.gates import exigir_confirmatorio_valido, exigir_politicas_resolvidas
from sustemporal.rules.catalog import (
    catalogo_sha256,
    requisito_auxiliar,
    sql_da_familia,
    sql_de_avaliacao,
    sql_sha256,
)
from sustemporal.rules.coerencia import SelecaoIncoerente, conferir_selecoes, criar_regras_fontes
from sustemporal.rules.falhas import ERROS_OPERACIONAIS, RegistroFalhas
from sustemporal.rules.insumos import InsumosAvaliacao, politica_da_execucao
from sustemporal.rules.preparo import (
    carregar_cobertura,
    carregar_integridade,
    carregar_registros,
    carregar_selecoes,
    derivar_selecoes,
    preparar_auxiliar,
    preparar_conjuntos,
)
from sustemporal.rules.saidas import COLUNAS_BRUTAS, ContextoSaida, gravar_saidas
from sustemporal.runtime_info import ambiente, versao_codigo

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import DatasetRef, RuleSpec, RunConfig, SnapshotSet
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.rules.preparo import Auxiliar

__all__ = ["InsumosAvaliacao", "calcular_run_id", "evaluate_rules", "montar_consulta"]

logger = logging.getLogger(__name__)

_FAMILIA_COM_DOMINIO = "INSTRUMENTO_REGISTRO"
_ESQUEMA_REGISTROS = "sia_pa.v1"


def _agora() -> datetime:
    return datetime.now(UTC)


def calcular_run_id(
    dataset: DatasetRef,
    snapshots: SnapshotSet,
    regras: list[RuleSpec],
    config: RunConfig,
    insumos: InsumosAvaliacao,
) -> str:
    """Identificador derivado do conteúdo dos insumos; independe de threads e memória."""
    politica = politica_da_execucao(insumos, config, regras)
    conteudo = {
        "dataset": dataset.dataset_id,
        "snapshot": snapshots.snapshot_id,
        "regras": catalogo_sha256(regras),
        "politica": politica.model_dump(mode="json"),
        "config": config.model_dump(mode="json", exclude={"runtime"}),
        "auxiliares": sorted(d.dataset_id for d in insumos.auxiliares),
        "selecoes": insumos.selecoes.dataset_id if insumos.selecoes else None,
        "cobertura": insumos.cobertura.dataset_id if insumos.cobertura else None,
        "integridade": sorted((a, str(e)) for a, e in insumos.integridade.items()),
    }
    return f"val_{hash_canonico(conteudo)[:40]}"


def _exigir_regras_unicas(rules: list[RuleSpec]) -> list[RuleSpec]:
    ids = [regra.rule_id for regra in rules]
    if len(set(ids)) != len(ids):
        raise ValueError("regras_repetidas_na_execucao")
    return sorted(rules, key=lambda regra: regra.rule_id)


def _exigir_mesma_origem(dataset: DatasetRef, insumos: InsumosAvaliacao) -> None:
    if dataset.schema_id != _ESQUEMA_REGISTROS:
        raise ValueError(f"conjunto_de_registros_invalido schema_id={dataset.schema_id}")
    outros = [*insumos.auxiliares, insumos.selecoes, insumos.cobertura]
    divergentes = [d.dataset_id for d in outros if d and d.origem_dados is not dataset.origem_dados]
    if divergentes:
        raise ValueError(f"insumos_de_outra_origem datasets={divergentes}")


def _campo_faltando(regra: RuleSpec) -> str:
    permitidas = set(regra.campos_necessarios)
    termos = [f"r.{identificador_seguro(c, permitidas)} IS NULL" for c in regra.campos_necessarios]
    if regra.familia.value == _FAMILIA_COM_DOMINIO:
        termos.append("r.instrumento NOT IN (SELECT instrumento FROM mapa_registro)")
    return f"coalesce({' OR '.join(termos)}, TRUE)"


def _parametros(
    regra: RuleSpec,
    politica: PoliticaTemporal,
    dataset: DatasetRef,
    auxiliar: Auxiliar,
) -> dict[str, object]:
    vigencia = regra.vigencia
    return {
        "rule_id": regra.rule_id,
        "fonte": str(requisito_auxiliar(regra).fonte),
        "familia": str(regra.familia),
        "instrumentos": list(regra.instrumentos),
        "politica_nao_resolvida": politica.tipo is TipoPolitica.NAO_RESOLVIDA,
        "leiaute": auxiliar.leiaute,
        "tem_vigencia": vigencia is not None,
        "vig_tipo": str(vigencia.referente_a) if vigencia else None,
        "vig_inicio": vigencia.inicio if vigencia else None,
        "vig_fim": vigencia.fim if vigencia else None,
        "query_id": f"{regra.familia.value.lower()}.existencia",
        "ds_registro": dataset.dataset_id,
        "hash_registro": dataset.hash_logico,
        "ds_auxiliar": auxiliar.dataset.dataset_id if auxiliar.dataset else None,
        "hash_auxiliar": auxiliar.dataset.hash_logico if auxiliar.dataset else None,
    }


def montar_consulta(regra: RuleSpec) -> str:
    """SQL executado para a regra (modelo comum com marcadores resolvidos)."""
    return (
        sql_de_avaliacao()
        .replace("{campo_faltando}", _campo_faltando(regra))
        .replace("{predicado}", sql_da_familia(regra.familia))
    )


def _avaliar_regra(
    con: duckdb.DuckDBPyConnection,
    contexto: ContextoSaida,
    regra: RuleSpec,
) -> None:
    insumos = contexto.insumos
    auxiliar = preparar_auxiliar(con, regra, insumos.auxiliares)
    preparar_conjuntos(con, regra, auxiliar, insumos.integridade)
    consulta = montar_consulta(regra)
    parametros = _parametros(regra, contexto.politica, contexto.dataset, auxiliar)
    parametros |= dict.fromkeys(("sql_sha256", "sql_sha256_aplicabilidade"), sql_sha256(consulta))
    con.execute(f"INSERT INTO avaliacoes_brutas {consulta}", parametros)
    logger.info("regra_avaliada regra=%s leiaute=%s", regra.rule_id, auxiliar.leiaute)


def _preparar(
    con: duckdb.DuckDBPyConnection, contexto: ContextoSaida, snapshots: SnapshotSet
) -> None:
    insumos = contexto.insumos
    carregar_registros(con, contexto.dataset, contexto.regras)
    if insumos.selecoes is not None:
        carregar_selecoes(con, insumos.selecoes)
        criar_regras_fontes(con, contexto.regras, contexto.politica)
        conferir_selecoes(con)
    else:
        derivar_selecoes(con, snapshots, contexto.regras, contexto.politica)
    carregar_cobertura(con, insumos.cobertura)
    carregar_integridade(con, insumos.integridade)
    colunas = ", ".join(f"{nome} {tipo}" for nome, tipo in COLUNAS_BRUTAS)
    con.execute(f"CREATE OR REPLACE TEMP TABLE avaliacoes_brutas ({colunas})")


def _executar(
    con: duckdb.DuckDBPyConnection, contexto: ContextoSaida, snapshots: SnapshotSet
) -> bool:
    falhas = contexto.falhas
    try:
        _preparar(con, contexto, snapshots)
    except ERROS_OPERACIONAIS as erro:
        etapa = "conferir_selecao" if isinstance(erro, SelecaoIncoerente) else "carregar_insumos"
        falhas.registrar(etapa, erro)
        return False
    for regra in contexto.regras:
        try:
            _avaliar_regra(con, contexto, regra)
        except ERROS_OPERACIONAIS as erro:
            falhas.registrar("avaliar_regra", erro, rule_id=regra.rule_id)
    return True


def _exigir_portoes(
    config: RunConfig,
    dataset: DatasetRef,
    insumos: InsumosAvaliacao,
    politica: PoliticaTemporal,
    iniciado: datetime,
) -> None:
    exigir_confirmatorio_valido(
        config, dataset.origem_dados, diretorio=insumos.diretorio_decisoes, hoje=iniciado.date()
    )
    exigir_politicas_resolvidas([politica], config.modo)


def evaluate_rules(
    dataset: DatasetRef,
    snapshots: SnapshotSet,
    rules: list[RuleSpec],
    config: RunConfig,
    out: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
    relogio: Callable[[], datetime] = _agora,
) -> RunResult:
    """Avalia as regras no conjunto de versões selecionado e grava as saídas em `out/<run_id>`.

    Falha de programa vira `FalhaOperacional` (`falhas.v1`), nunca `INCONCLUSIVO`.

    Raises:
        PortaoRecusado: política não resolvida ou documental pendente no confirmatório.
        ValueError: regras repetidas, método inválido ou insumos de outra origem de dados.
    """
    insumos = insumos or InsumosAvaliacao()
    iniciado = relogio()
    regras = _exigir_regras_unicas(rules)
    politica = politica_da_execucao(insumos, config, regras)
    _exigir_portoes(config, dataset, insumos, politica, iniciado)
    _exigir_mesma_origem(dataset, insumos)
    run_id = calcular_run_id(dataset, snapshots, regras, config, insumos)
    destino = out / run_id
    destino.mkdir(parents=True, exist_ok=True)
    contexto = ContextoSaida(
        run_id=run_id,
        dataset=dataset,
        regras=regras,
        politica=politica,
        insumos=insumos,
        destino=destino,
        falhas=RegistroFalhas(run_id, relogio),
    )
    logger.info(
        "validacao_iniciada run=%s metodo=%s regras=%d", run_id, politica.metodo, len(regras)
    )
    con = conectar(config.runtime)
    try:
        preparado = _executar(con, contexto, snapshots)
        saidas = gravar_saidas(con, contexto, avaliadas=preparado)
    finally:
        con.close()
    return _resultado(contexto, snapshots, config, saidas, iniciado=iniciado, preparado=preparado)


def _resultado(
    contexto: ContextoSaida,
    snapshots: SnapshotSet,
    config: RunConfig,
    saidas: tuple[DatasetRef, ...],
    *,
    iniciado: datetime,
    preparado: bool,
) -> RunResult:
    insumos = contexto.insumos
    n_falhas = len(contexto.falhas.falhas)
    estado = EstadoExecucao.CONCLUIDA
    if n_falhas:
        estado = EstadoExecucao.PARCIAL if preparado else EstadoExecucao.FALHOU
    entradas = [contexto.dataset, *insumos.auxiliares, insumos.selecoes, insumos.cobertura]
    resultado = RunResult(
        run_id=contexto.run_id,
        tipo=TipoExecucao.VALIDACAO,
        metodo=contexto.politica.metodo,
        politica_id=contexto.politica.politica_id,
        modo=config.modo,
        config_hash=config.config_hash,
        codigo=versao_codigo(insumos.raiz_codigo),
        ambiente=ambiente(insumos.raiz_codigo),
        snapshot_set_id=snapshots.snapshot_id,
        catalogo_regras_sha256=catalogo_sha256(contexto.regras),
        entradas=tuple(d for d in entradas if d is not None),
        saidas=saidas,
        falhas=n_falhas,
        estado=estado,
        iniciado_em=iniciado,
        concluido_em=max(iniciado, contexto.falhas.relogio()),
        freeze_id=config.freeze_id,
        origem_dados=contexto.dataset.origem_dados,
    )
    (contexto.destino / "run_result.json").write_text(
        resultado.model_dump_json(indent=2), encoding="utf-8"
    )
    logger.info(
        "validacao_concluida run=%s estado=%s falhas=%d", resultado.run_id, estado, n_falhas
    )
    return resultado
