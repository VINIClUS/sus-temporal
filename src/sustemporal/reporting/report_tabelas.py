"""Tabelas do relatório do piloto no DuckDB: recorte, contagens, campos, defasagem e rótulos.

Cada linha física do SIA-PA recebe no máximo um motivo de exclusão, na ordem: deletado, município
do estabelecimento ausente, fora do território, competência de processamento ausente, fora do
intervalo da coorte, instrumento fora da coorte. As demais são as incluídas; incluídas mais
excluídas reconciliam com as linhas dos conjuntos canônicos.

`campos` conta o nulo de cada campo que o G0 manda verificar, sobre as linhas incluídas:
identificação, competências, procedimento, CBO, instrumento, quantidades e valores apresentados e
aprovados, PA_INDICA e os campos de erro. Nos campos sem normalização (PA_INDICA e os de erro), nulo
é coluna fora do arquivo; texto em branco é valor lido e não conta como ausente. Campo de erro só
entra nessa tabela de observabilidade, nunca em contagem nem em atributo de classificação.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.evaluation.labels import CODEBOOK_PA, label_pa
from sustemporal.ingest.sia_pa import carregar_conferido
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import CohortSpec, DatasetRef, RuntimeConfig

__all__ = [
    "carregar_registros_piloto",
    "carregar_rotulos",
    "criar_tabelas_registros",
]

_SQL_BASE = """
CREATE TABLE base AS
SELECT row_id, cnes, municipio_estabelecimento, competencia_atendimento,
       competencia_processamento, instrumento, procedimento, cbo,
       quantidade_apresentada, quantidade_aprovada, valor_apresentado, valor_aprovado,
       pa_indica, pa_codoco, pa_flqt, pa_fler,
       CASE
         WHEN deletado THEN 'deletado'
         WHEN municipio_estabelecimento IS NULL THEN 'municipio_estabelecimento_ausente'
         WHEN NOT list_contains($municipios, municipio_estabelecimento) THEN 'fora_do_territorio'
         WHEN competencia_processamento IS NULL THEN 'competencia_processamento_ausente'
         WHEN competencia_processamento < $inicio OR competencia_processamento > $fim
           THEN 'fora_do_intervalo_da_coorte'
         WHEN $filtra_instrumento
              AND (instrumento IS NULL OR NOT list_contains($instrumentos, instrumento))
           THEN 'instrumento_fora_da_coorte'
       END AS exclusao
FROM pa
"""

_SQL_PA_VAZIO = """
CREATE TABLE pa (
  row_id VARCHAR, deletado BOOLEAN, cnes VARCHAR, municipio_estabelecimento VARCHAR,
  competencia_atendimento VARCHAR, competencia_processamento VARCHAR, instrumento VARCHAR,
  procedimento VARCHAR, cbo VARCHAR, quantidade_apresentada BIGINT, quantidade_aprovada BIGINT,
  valor_apresentado DECIMAL(18, 2), valor_aprovado DECIMAL(18, 2), pa_indica VARCHAR,
  pa_codoco VARCHAR, pa_flqt VARCHAR, pa_fler VARCHAR
)
"""

_SQL_CAMPOS = """
CREATE TABLE campos AS
WITH incluidas AS (SELECT * FROM base WHERE exclusao IS NULL)
SELECT campo, ausentes, denominador FROM (
  SELECT 1 AS ordem, 'cnes' AS campo, count(*) FILTER (WHERE cnes IS NULL) AS ausentes,
         count(*) AS denominador FROM incluidas
  UNION ALL SELECT 2, 'municipio_estabelecimento',
         count(*) FILTER (WHERE municipio_estabelecimento IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 3, 'competencia_atendimento',
         count(*) FILTER (WHERE competencia_atendimento IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 4, 'competencia_processamento',
         count(*) FILTER (WHERE competencia_processamento IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 5, 'procedimento', count(*) FILTER (WHERE procedimento IS NULL), count(*)
         FROM incluidas
  UNION ALL SELECT 6, 'instrumento', count(*) FILTER (WHERE instrumento IS NULL), count(*)
         FROM incluidas
  UNION ALL SELECT 7, 'cbo', count(*) FILTER (WHERE cbo IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 8, 'quantidade_aprovada',
         count(*) FILTER (WHERE quantidade_aprovada IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 9, 'valor_aprovado', count(*) FILTER (WHERE valor_aprovado IS NULL),
         count(*) FROM incluidas
  UNION ALL SELECT 10, 'quantidade_apresentada',
         count(*) FILTER (WHERE quantidade_apresentada IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 11, 'valor_apresentado',
         count(*) FILTER (WHERE valor_apresentado IS NULL), count(*) FROM incluidas
  UNION ALL SELECT 12, 'pa_indica', count(*) FILTER (WHERE pa_indica IS NULL), count(*)
         FROM incluidas
  UNION ALL SELECT 13, 'pa_codoco', count(*) FILTER (WHERE pa_codoco IS NULL), count(*)
         FROM incluidas
  UNION ALL SELECT 14, 'pa_flqt', count(*) FILTER (WHERE pa_flqt IS NULL), count(*)
         FROM incluidas
  UNION ALL SELECT 15, 'pa_fler', count(*) FILTER (WHERE pa_fler IS NULL), count(*)
         FROM incluidas
) ORDER BY ordem
"""

_SQL_CONTAGENS = """
CREATE TABLE contagens AS
SELECT dimensao, valor, count(*) AS linhas FROM (
  SELECT 'competencia_processamento' AS dimensao, competencia_processamento AS valor
  FROM base WHERE exclusao IS NULL
  UNION ALL SELECT 'instrumento', instrumento FROM base WHERE exclusao IS NULL
  UNION ALL SELECT 'cnes', cnes FROM base WHERE exclusao IS NULL
) GROUP BY dimensao, valor ORDER BY dimensao, valor NULLS FIRST
"""

_SQL_EXCLUSOES = """
CREATE TABLE exclusoes AS
SELECT exclusao AS motivo, count(*) AS linhas FROM base WHERE exclusao IS NOT NULL
GROUP BY exclusao ORDER BY exclusao
"""

_SQL_DEFASAGEM = """
CREATE TABLE defasagem AS
SELECT (CAST(substr(competencia_processamento, 1, 4) AS BIGINT) * 12
        + CAST(substr(competencia_processamento, 5, 2) AS BIGINT))
     - (CAST(substr(competencia_atendimento, 1, 4) AS BIGINT) * 12
        + CAST(substr(competencia_atendimento, 5, 2) AS BIGINT)) AS defasagem_meses,
       count(*) AS linhas
FROM base WHERE exclusao IS NULL GROUP BY ALL ORDER BY defasagem_meses NULLS FIRST
"""

_SQL_ROTULOS_RESUMO = """
CREATE TABLE rotulos_resumo AS
SELECT etapa, valor, count(*) AS linhas FROM (
  SELECT 'ANTES' AS etapa, r.pa_indica_bruto AS valor
  FROM rotulos r JOIN base b USING (row_id) WHERE b.exclusao IS NULL
  UNION ALL
  SELECT 'DEPOIS', r.rotulo FROM rotulos r JOIN base b USING (row_id) WHERE b.exclusao IS NULL
) GROUP BY etapa, valor ORDER BY etapa, valor NULLS FIRST
"""


def carregar_registros_piloto(
    con: duckdb.DuckDBPyConnection, datasets: Sequence[DatasetRef]
) -> int:
    """Une os conjuntos `sia_pa.v1` conferidos na tabela `pa`; devolve as linhas físicas."""
    esquema = carregar_esquema("sia_pa.v1")
    for indice, dataset in enumerate(datasets):
        if indice == 0:
            carregar_conferido(con, dataset, esquema, "pa")
            continue
        carregar_conferido(con, dataset, esquema, "pa_proximo")
        con.execute("INSERT INTO pa BY NAME SELECT * FROM pa_proximo")
        con.execute("DROP TABLE pa_proximo")
    if not datasets:
        con.execute(_SQL_PA_VAZIO)
    resultado = con.execute("SELECT count(*) FROM pa").fetchone()
    return int(resultado[0]) if resultado else 0


def criar_tabelas_registros(
    con: duckdb.DuckDBPyConnection, cohort: CohortSpec, municipios: frozenset[str]
) -> None:
    """`base` com o motivo de exclusão e as tabelas de contagens, exclusões, defasagem e campos."""
    con.execute(
        _SQL_BASE,
        {
            "municipios": sorted(municipios),
            "inicio": cohort.inicio.valor,
            "fim": cohort.fim.valor,
            "filtra_instrumento": bool(cohort.instrumentos),
            "instrumentos": list(cohort.instrumentos),
        },
    )
    for sql in (_SQL_CONTAGENS, _SQL_EXCLUSOES, _SQL_DEFASAGEM, _SQL_CAMPOS):
        con.execute(sql)


def carregar_rotulos(
    con: duckdb.DuckDBPyConnection,
    datasets: Sequence[DatasetRef],
    out: Path,
    *,
    runtime: RuntimeConfig,
) -> None:
    """Rótulos (antes: PA_INDICA bruto; depois: rótulo do codebook) de todas as linhas incluídas,
    aprovações inclusive; nenhum rótulo é filtrado."""
    con.execute("CREATE TABLE rotulos (row_id VARCHAR, pa_indica_bruto VARCHAR, rotulo VARCHAR)")
    destino = out / "rotulos"
    destino.mkdir(parents=True, exist_ok=True)
    for dataset in datasets:
        rotulos = label_pa(dataset, CODEBOOK_PA, destino, runtime=runtime)
        con.execute(
            "INSERT INTO rotulos SELECT row_id, pa_indica_bruto, rotulo FROM read_parquet($c)",
            {"c": rotulos.caminho},
        )
    con.execute(_SQL_ROTULOS_RESUMO)
