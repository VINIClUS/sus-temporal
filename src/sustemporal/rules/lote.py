"""Motor integrado à seleção temporal em lote do T06 (`selecao_versoes.v1` e `SnapshotSet`).

A política é resolvida uma vez (`politica_da_execucao`) e repassada à seleção e ao motor. A
seleção gravada volta ao motor como insumo comum: conteúdo conferido contra o `DatasetRef` e
coerência com a política, como qualquer seleção fornecida.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.temporal import SelecaoVersao, SnapshotSet
from sustemporal.duck import conectar
from sustemporal.rules.catalog import catalogo_sha256
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao, politica_da_execucao
from sustemporal.rules.preparo import carregar_registros
from sustemporal.temporal.lote import gravar_selecoes, selecionar_lote
from sustemporal.temporal.selector import unir_snapshots

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import DatasetRef, RuleSpec, RunConfig
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["SelecaoEmLote", "avaliar_com_registro", "selecionar_em_lote"]

logger = logging.getLogger(__name__)

_COLUNAS_SELECAO = (
    "fonte",
    "base",
    "competencia_requerida",
    "estado",
    "artifact_ids",
    "observation_ids",
    "motivo",
)


@dataclass(frozen=True)
class SelecaoEmLote:
    """Seleção gravada (`DatasetRef` com hash lógico) e o `SnapshotSet` da execução."""

    selecoes: DatasetRef
    snapshots: SnapshotSet


def _agora() -> datetime:
    return datetime.now(UTC)


def _uf(config: RunConfig) -> str | None:
    """UF do piloto ou da vigilância (T06-10); sem nenhuma, só fontes nacionais."""
    if config.piloto is not None:
        return config.piloto.uf
    return config.vigilancia.uf if config.vigilancia is not None else None


def _id_da_selecao(
    dataset: DatasetRef,
    regras: list[RuleSpec],
    politica: PoliticaTemporal,
    registro: RegistroTemporal,
    config: RunConfig,
) -> str:
    observacoes = sorted(registro.observacoes, key=lambda o: o.observation_id)
    partes = {
        f"{fonte}|{competencia}": sorted(nomes)
        for (fonte, competencia), nomes in registro.partes_esperadas.items()
    }
    conteudo = {
        "dataset": dataset.dataset_id,
        "regras": catalogo_sha256(regras),
        "politica": politica.model_dump(mode="json"),
        "observacoes": [o.model_dump(mode="json") for o in observacoes],
        "versoes": [registro.versoes[a].model_dump(mode="json") for a in sorted(registro.versoes)],
        "partes": dict(sorted(partes.items())),
        "uf": _uf(config),
        "corte": config.corte_observacao.isoformat() if config.corte_observacao else None,
    }
    return f"sel_{hash_canonico(conteudo)[:40]}"


def _selecoes_distintas(con: duckdb.DuckDBPyConnection) -> list[SelecaoVersao]:
    lista = ", ".join(_COLUNAS_SELECAO)
    linhas = con.execute(
        f"SELECT DISTINCT {lista} FROM selecao_versoes ORDER BY ALL"  # noqa: S608
    ).fetchall()
    selecoes = []
    for linha in linhas:
        campos = dict(zip(_COLUNAS_SELECAO, linha, strict=True))
        for nome in ("artifact_ids", "observation_ids"):
            campos[nome] = tuple(v for v in str(campos[nome]).split(";") if v)
        selecoes.append(SelecaoVersao.model_validate(campos))
    return selecoes


def _conjunto(selecao: SelecaoVersao, corte: datetime | None) -> SnapshotSet:
    return SnapshotSet.criar(
        artifact_ids=tuple(sorted(selecao.artifact_ids)),
        observation_ids=tuple(sorted(selecao.observation_ids)),
        dataset_hashes=(),
        selecoes=(selecao,),
        corte_observacao=corte,
    )


def selecionar_em_lote(
    dataset: DatasetRef,
    regras: list[RuleSpec],
    config: RunConfig,
    registro: RegistroTemporal,
    destino: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> SelecaoEmLote:
    """`selecionar_lote` → `gravar_selecoes` em `destino/<sel_id>/` e o `SnapshotSet` das chaves.

    Raises:
        ValueError: registros inválidos, conteúdo divergente do `DatasetRef` ou política inválida.
        ConfigInvalida: `config.politica_id` inexistente ou inválida.
    """
    politica = politica_da_execucao(insumos or InsumosAvaliacao(), config, regras)
    selecao_id = _id_da_selecao(dataset, regras, politica, registro, config)
    corte = config.corte_observacao
    con = conectar(config.runtime)
    try:
        carregar_registros(con, dataset, regras)
        selecionar_lote(
            con,
            "registros",
            regras,
            politica,
            registro,
            run_id=selecao_id,
            uf=_uf(config),
            corte=corte,
        )
        caminho = destino / selecao_id / "selecao_versoes.parquet"
        ref = gravar_selecoes(con, caminho, run_id=selecao_id, origem=dataset.origem_dados)
        selecoes = _selecoes_distintas(con)
    finally:
        con.close()
    snapshots = unir_snapshots((_conjunto(s, corte) for s in selecoes), relogio=relogio)
    logger.info("selecao_em_lote_gravada selecao=%s linhas=%d", selecao_id, ref.linhas)
    return SelecaoEmLote(selecoes=ref, snapshots=snapshots)


def avaliar_com_registro(
    dataset: DatasetRef,
    regras: list[RuleSpec],
    config: RunConfig,
    registro: RegistroTemporal,
    out: Path,
    *,
    insumos: InsumosAvaliacao | None = None,
    relogio: Callable[[], datetime] = _agora,
) -> RunResult:
    """Seleção em lote do T06 e avaliação das regras com a mesma política resolvida.

    Raises:
        ValueError: seleção já fornecida nos insumos, ou os erros de `selecionar_em_lote`.
        PortaoRecusado: os portões de `evaluate_rules`.
    """
    insumos = insumos or InsumosAvaliacao()
    if insumos.selecoes is not None:
        raise ValueError(f"selecoes_fornecidas_com_registro selecoes={insumos.selecoes.dataset_id}")
    resolvidos = replace(insumos, politica=politica_da_execucao(insumos, config, regras))
    lote = selecionar_em_lote(
        dataset, regras, config, registro, out / "selecoes", insumos=resolvidos, relogio=relogio
    )
    return evaluate_rules(
        dataset,
        lote.snapshots,
        regras,
        config,
        out,
        insumos=replace(resolvidos, selecoes=lote.selecoes),
        relogio=relogio,
    )
