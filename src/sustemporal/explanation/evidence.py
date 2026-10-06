"""Evidências reexecutáveis: consulta parametrizada, fonte, cobertura e integridade (T08).

A reexecução recalcula, sobre o mesmo conjunto (`DatasetRef` da execução), o hash lógico e o
número de correspondências da consulta existencial da evidência. Divergência é falha registrada;
a evidência gravada nunca é trocada pela recalculada.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.explanation import Evidence
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sustemporal.contracts.records import DatasetRef

__all__ = [
    "EvidenciaDivergente",
    "Reexecucao",
    "exigir_reproducao",
    "ler_evidencia",
    "reexecutar_evidencia",
    "reexecutar_evidencias",
    "sql_reexecucao",
]

logger = logging.getLogger(__name__)

_FILTRO = "SELECT count(*) FROM read_parquet($caminho) WHERE list_contains($artefatos, artifact_id)"
_CONSULTAS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "procedimento_cbo.existencia": (
        "sigtap_proc_ocupacao.v1",
        f"{_FILTRO} AND co_procedimento = $procedimento AND co_ocupacao = $cbo",
        ("cbo", "procedimento"),
    ),
    "estabelecimento_cbo.existencia": (
        "cnes_estab_cbo.v1",
        f"{_FILTRO} AND cnes = $cnes AND cbo = $cbo AND n_vinculos > 0",
        ("cbo", "cnes"),
    ),
    "instrumento_registro.existencia": (
        "sigtap_proc_registro.v1",
        f"{_FILTRO} AND co_procedimento = $procedimento AND co_registro = $co_registro",
        ("co_registro", "procedimento"),
    ),
    "vigencia_procedimento.existencia": (
        "sigtap_procedimento.v1",
        f"{_FILTRO} AND co_procedimento = $procedimento",
        ("procedimento",),
    ),
}
_SO_HASH = "aplicabilidade."
_TABELA = "reexecucao_conteudo"


class EvidenciaDivergente(ValueError):
    """Reexecução da consulta da evidência não reproduz o resultado ou o hash."""


@dataclass(frozen=True)
class Reexecucao:
    """Resultado da reexecução; `n_resultados` é `None` quando só o hash é verificável."""

    evidence_id: str
    query_id: str
    sql_sha256: str | None
    parametros: dict[str, str]
    hash_logico: str | None
    n_resultados: int | None
    divergencias: tuple[str, ...]

    @property
    def reproduzida(self) -> bool:
        return not self.divergencias


def sql_reexecucao(query_id: str) -> str:
    """SQL parametrizado da consulta existencial de `query_id`.

    Raises:
        KeyError: consulta fora da allowlist.
    """
    return _CONSULTAS[query_id][1]


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _lista(texto: object) -> tuple[str, ...]:
    return tuple(parte for parte in str(texto or "").split(";") if parte)


def ler_evidencia(linha: Mapping[str, object]) -> Evidence:
    """Evidence a partir de uma linha de `evidencias.v1` (JSON canônico e listas com ';').

    Raises:
        ValueError: parâmetro nulo, `parametros` que não é objeto, `chaves_amostra` que não é
            lista, ou linha incoerente com o contrato.
    """
    parametros = json.loads(str(linha["parametros"] or "{}"))
    chaves = json.loads(str(linha["chaves_amostra"] or "[]"))
    if not isinstance(parametros, dict) or not isinstance(chaves, list):
        raise ValueError(f"evidencia_incoerente_com_contrato evidencia={linha['evidence_id']}")
    if any(valor is None for valor in parametros.values()):
        raise ValueError(f"evidencia_parametro_nulo evidencia={linha['evidence_id']}")
    return Evidence.model_validate(
        {
            **{chave: linha[chave] for chave in ("evidence_id", "tipo", "query_id")},
            **{chave: linha[chave] for chave in ("sql_sha256", "dataset_id", "hash_logico")},
            "parametros": {str(c): str(v) for c, v in parametros.items()},
            "artifact_ids": _lista(linha["artifact_ids"]),
            "cobertura": linha["cobertura"],
            "integridade": linha["integridade"],
            "n_resultados": linha["n_resultados"],
            "chaves_amostra": tuple(chaves),
        }
    )


def _hash_do_conjunto(con: duckdb.DuckDBPyConnection, dataset: DatasetRef) -> str:
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": dataset.caminho}
    ).fetchall()
    fisicas = {str(linha[0]) for linha in descricao}
    colunas = [c.nome for c in carregar_esquema(dataset.schema_id).colunas if c.nome in fisicas]
    projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {_TABELA} AS SELECT {projecao} "  # noqa: S608
        "FROM read_parquet($c)",
        {"c": dataset.caminho},
    )
    try:
        return hash_logico_relacao(con, _TABELA, colunas)
    finally:
        con.execute(f"DROP TABLE IF EXISTS {_TABELA}")


def _contar(
    con: duckdb.DuckDBPyConnection, evidencia: Evidence, dataset: DatasetRef
) -> tuple[int | None, list[str]]:
    consulta = _CONSULTAS.get(evidencia.query_id)
    if consulta is None:
        return None, [f"consulta_desconhecida query_id={evidencia.query_id}"]
    schema_id, sql, nomes = consulta
    if dataset.schema_id != schema_id:
        return None, [f"esquema_divergente esperado={schema_id} obtido={dataset.schema_id}"]
    if tuple(sorted(evidencia.parametros)) != nomes:
        return None, [f"parametros_divergentes obtidos={sorted(evidencia.parametros)}"]
    valores: dict[str, object] = dict(evidencia.parametros)
    valores |= {"caminho": dataset.caminho, "artefatos": list(evidencia.artifact_ids)}
    quantidade = int(con.execute(sql, valores).fetchall()[0][0])
    if quantidade != evidencia.n_resultados:
        return quantidade, [f"n_resultados esperado={evidencia.n_resultados} obtido={quantidade}"]
    return quantidade, []


def _divergencias_do_conjunto(evidencia: Evidence, dataset: DatasetRef, obtido: str) -> list[str]:
    divergencias = []
    if obtido != evidencia.hash_logico or dataset.hash_logico != evidencia.hash_logico:
        divergencias.append(f"hash_logico esperado={evidencia.hash_logico} obtido={obtido}")
    fora = sorted(set(evidencia.artifact_ids) - set(dataset.artifact_ids))
    if fora:
        divergencias.append(f"artefato_fora_do_conjunto artifact_ids={fora}")
    return divergencias


def _reexecutar(
    con: duckdb.DuckDBPyConnection, evidencia: Evidence, conjuntos: Mapping[str, DatasetRef]
) -> Reexecucao:
    consulta = _CONSULTAS.get(evidencia.query_id)

    def resultado(
        hash_logico: str | None, n: int | None, divergencias: Iterable[str]
    ) -> Reexecucao:
        return Reexecucao(
            evidence_id=evidencia.evidence_id,
            query_id=evidencia.query_id,
            sql_sha256=_sha256(consulta[1]) if consulta else None,
            parametros=dict(evidencia.parametros),
            hash_logico=hash_logico,
            n_resultados=n,
            divergencias=tuple(divergencias),
        )

    dataset = conjuntos.get(evidencia.dataset_id)
    if dataset is None:
        return resultado(None, None, [f"dataset_ausente dataset_id={evidencia.dataset_id}"])
    try:
        obtido = _hash_do_conjunto(con, dataset)
        so_hash = evidencia.query_id.startswith(_SO_HASH)
        quantidade, problemas = (None, []) if so_hash else _contar(con, evidencia, dataset)
    except duckdb.Error as erro:
        nome = type(erro).__name__
        return resultado(
            None, None, [f"conjunto_ilegivel dataset_id={dataset.dataset_id} erro={nome}"]
        )
    return resultado(
        obtido, quantidade, [*_divergencias_do_conjunto(evidencia, dataset, obtido), *problemas]
    )


def reexecutar_evidencias(
    evidencias: Iterable[Evidence],
    conjuntos: Mapping[str, DatasetRef],
    *,
    runtime: RuntimeConfig | None = None,
) -> tuple[Reexecucao, ...]:
    """Reexecuta cada evidência sobre o conjunto que ela cita, numa só conexão."""
    con = conectar(runtime or RuntimeConfig())
    try:
        resultados = tuple(_reexecutar(con, evidencia, conjuntos) for evidencia in evidencias)
    finally:
        con.close()
    for resultado in resultados:
        logger.info(
            "evidencia_reexecutada evidencia=%s reproduzida=%s",
            resultado.evidence_id,
            resultado.reproduzida,
        )
    return resultados


def reexecutar_evidencia(
    evidencia: Evidence,
    conjuntos: Mapping[str, DatasetRef],
    *,
    runtime: RuntimeConfig | None = None,
) -> Reexecucao:
    """Reexecuta uma evidência (hash do conjunto e, se existencial, número de correspondências)."""
    return reexecutar_evidencias((evidencia,), conjuntos, runtime=runtime)[0]


def exigir_reproducao(reexecucoes: Iterable[Reexecucao]) -> None:
    """Raises: EvidenciaDivergente na primeira evidência não reproduzida."""
    for reexecucao in reexecucoes:
        if not reexecucao.reproduzida:
            raise EvidenciaDivergente(
                f"evidencia_divergente evidencia={reexecucao.evidence_id} "
                f"divergencias={list(reexecucao.divergencias)}"
            )
