"""Inconclusivos classificados pela seleção de versões e disponibilidade pela cobertura (T05).

Cada linha de `selecao_versoes.v1` de um registro incluído entra no denominador do seu estrato
(regra, fonte, base). A classe separa a ausência sem bytes pela observação de coleta: listagem que
não trouxe o arquivo (`NAO_ENCONTRADO`), tentativa sem bytes (`FALHA_TRANSPORTE`,
`RECUSADO_OFFLINE`, `INTERROMPIDO`, `FALHA_ARMAZENAMENTO`) ou nenhuma tentativa observada; nessa
ordem quando há mais de uma. Seleção que cita observação sem resultado conhecido (id fora do mapa
de resultados recebido) é `ausente_tentativa_sem_resultado_conhecido`: não afirma ausência nem
falha, e `ausente_sem_tentativa` fica para a que não cita observação. EM_QUARENTENA leva o motivo
do seletor (por exemplo, `falha_de_coleta_com_bytes`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts import ResultadoTentativa
from sustemporal.ingest.sia_pa import carregar_conferido
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import duckdb

    from sustemporal.contracts import CohortSpec, DatasetRef

__all__ = ["RESULTADOS_SEM_BYTES", "carregar_disponibilidade", "carregar_inconclusivos"]

RESULTADOS_SEM_BYTES = (
    ResultadoTentativa.FALHA_TRANSPORTE,
    ResultadoTentativa.RECUSADO_OFFLINE,
    ResultadoTentativa.INTERROMPIDO,
    ResultadoTentativa.FALHA_ARMAZENAMENTO,
)

_SQL_SELECOES_VAZIAS = """
CREATE TABLE selecoes (
  row_id VARCHAR, rule_id VARCHAR, fonte VARCHAR, base VARCHAR, estado VARCHAR,
  observation_ids VARCHAR, motivo VARCHAR
)
"""

_SQL_INCONCLUSIVOS = """
CREATE TABLE inconclusivos AS
WITH sel AS (
  SELECT s.rule_id, s.fonte, s.base, s.estado, s.motivo, s.observation_ids
  FROM selecoes s JOIN base b USING (row_id) WHERE b.exclusao IS NULL
),
tentativas AS (
  SELECT ids, bool_or(o.resultado = $nao_encontrado) AS nao_encontrado,
         bool_or(list_contains($sem_bytes, o.resultado)) AS sem_bytes
  FROM (SELECT DISTINCT observation_ids AS ids,
               unnest(string_split(observation_ids, ';')) AS observation_id
        FROM sel WHERE observation_ids <> '')
  JOIN observacoes o USING (observation_id)
  GROUP BY ids
)
SELECT rule_id, fonte, coalesce(base, '') AS base, estado,
  CASE
    WHEN estado = 'SELECIONADA' THEN 'selecionada'
    WHEN estado = 'AUSENTE' AND coalesce(t.nao_encontrado, false)
      THEN 'ausente_nao_encontrado_na_listagem'
    WHEN estado = 'AUSENTE' AND coalesce(t.sem_bytes, false) THEN 'ausente_tentativa_sem_bytes'
    WHEN estado = 'AUSENTE' AND observation_ids <> ''
      THEN 'ausente_tentativa_sem_resultado_conhecido'
    WHEN estado = 'AUSENTE' THEN 'ausente_sem_tentativa'
    WHEN estado = 'EM_QUARENTENA' THEN 'em_quarentena_' || split_part(motivo, ' ', 1)
    ELSE lower(estado)
  END AS classe,
  count(*) AS linhas
FROM sel LEFT JOIN tentativas t ON t.ids = sel.observation_ids
GROUP BY ALL ORDER BY rule_id, fonte, base, classe
"""

_SQL_DISPONIBILIDADE = """
CREATE TABLE disponibilidade AS
SELECT familia_regra, instrumento, competencia, base_temporal, estado, motivo FROM cobertura
WHERE competencia BETWEEN $inicio AND $fim
  AND (NOT $filtra_instrumento OR list_contains($instrumentos, instrumento))
ORDER BY familia_regra, instrumento, competencia, base_temporal
"""


def carregar_inconclusivos(
    con: duckdb.DuckDBPyConnection,
    selecoes: Sequence[DatasetRef],
    observacoes: Mapping[str, ResultadoTentativa],
) -> None:
    """Tabela `inconclusivos` (classe e linhas por regra, fonte, base e estado)."""
    con.execute("CREATE TABLE observacoes (observation_id VARCHAR PRIMARY KEY, resultado VARCHAR)")
    if observacoes:
        con.executemany(
            "INSERT INTO observacoes VALUES (?, ?)",
            [[chave, valor.value] for chave, valor in sorted(observacoes.items())],
        )
    con.execute(_SQL_SELECOES_VAZIAS)
    esquema = carregar_esquema("selecao_versoes.v1")
    for selecao in selecoes:
        carregar_conferido(con, selecao, esquema, "selecao_lida")
        con.execute(
            "INSERT INTO selecoes SELECT row_id, rule_id, fonte, base, estado, observation_ids, "
            "motivo FROM selecao_lida"
        )
        con.execute("DROP TABLE selecao_lida")
    con.execute(
        _SQL_INCONCLUSIVOS,
        {
            "nao_encontrado": ResultadoTentativa.NAO_ENCONTRADO.value,
            "sem_bytes": [r.value for r in RESULTADOS_SEM_BYTES],
        },
    )


def carregar_disponibilidade(
    con: duckdb.DuckDBPyConnection, cobertura: DatasetRef, cohort: CohortSpec
) -> None:
    """Tabela `disponibilidade`: a cobertura no intervalo e nos instrumentos da coorte."""
    carregar_conferido(con, cobertura, carregar_esquema("cobertura.v1"), "cobertura")
    con.execute(
        _SQL_DISPONIBILIDADE,
        {
            "inicio": cohort.inicio.valor,
            "fim": cohort.fim.valor,
            "filtra_instrumento": bool(cohort.instrumentos),
            "instrumentos": list(cohort.instrumentos),
        },
    )
