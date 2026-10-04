"""Normalização de arquivos do CNES (T04).

PF vira contagens por estabelecimento–CBO (`cnes_estab_cbo.v1`) e ST vira estabelecimentos
(`cnes_estabelecimento.v1`). Do PF só CNES, CBO e COMPETEN saem do leitor: CPF, CNS, nome,
registro e residência nunca entram em tabela. COMPETEN tem de ser igual à competência do arquivo,
sem fallback de mês. SR e HB pertencem a famílias reservadas e são recusados sem tabela.
"""

from __future__ import annotations

import logging
from contextlib import closing
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from sustemporal.contracts import (
    DatasetRef,
    EsquemaCanonico,
    EstadoIntegridade,
    FamiliaFonte,
    LayoutSpec,
    Multiplicidade,
    OrigemDados,
    Reconciliacao,
    RuntimeConfig,
    TipoCanonico,
)
from sustemporal.contracts.rules import FamiliaRegra
from sustemporal.duck import conectar
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.ingest.cnes_leitura import gravar_relacao, ler_artefato_dbf
from sustemporal.ingest.dbf import COLUNA_DELETADO, QuarentenaLeitura
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts import ArtifactVersion
    from sustemporal.ingest.dbf import LeituraDbf

__all__ = ["CATALOGO_LEIAUTES", "FamiliaReservada", "carregar_leiautes_cnes", "normalize_cnes"]

logger = logging.getLogger(__name__)

CATALOGO_LEIAUTES = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "cnes.yaml"
ESQUEMAS = Path(__file__).resolve().parents[3] / "catalog" / "schemas"
RESERVADAS: dict[FamiliaFonte, FamiliaRegra] = {
    FamiliaFonte.CNES_SR: FamiliaRegra.SERVICO_CLASSIFICACAO,
    FamiliaFonte.CNES_HB: FamiliaRegra.HABILITACAO,
}
_ESQUEMAS = {FamiliaFonte.CNES_PF: "cnes_estab_cbo", FamiliaFonte.CNES_ST: "cnes_estabelecimento"}
_CNES = "[0-9]{7}"
_CBO = "[0-9A-Z]{6}"
_ATRIBUTOS_ST = {
    "CODUFMUN": "municipio_estabelecimento",
    "TP_UNID": "tipo_unidade",
    "TPGESTAO": "tipo_gestao",
    "NAT_JUR": "natureza_juridica",
}

_CLASSIFICAR_PF = """
CREATE TABLE classificada AS
SELECT
    deletado,
    trim(cnes, ' ') AS cnes,
    trim(cbo, ' ') AS cbo,
    trim(competen, ' ') AS competen,
    CASE
        WHEN deletado THEN 'deletado'
        WHEN trim(cnes, ' ') = '' THEN 'cnes_VAZIO'
        WHEN NOT regexp_full_match(trim(cnes, ' '), $cnes) THEN 'cnes_CODIFICACAO_INVALIDA'
        WHEN trim(cbo, ' ') = '' THEN 'cbo_VAZIO'
        WHEN NOT regexp_full_match(trim(cbo, ' '), $cbo) THEN 'cbo_CODIFICACAO_INVALIDA'
    END AS exclusao
FROM bruto
"""
_AGREGAR_PF = """
SELECT
    CAST($competencia AS VARCHAR) AS competencia_arquivo,
    cnes,
    cbo,
    CAST($artefato AS VARCHAR) AS artifact_id,
    CAST(count(*) AS BIGINT) AS n_vinculos
FROM classificada WHERE exclusao IS NULL
GROUP BY cnes, cbo ORDER BY cnes, cbo
"""
_CLASSIFICAR_ST = """
CREATE TABLE classificada AS
SELECT
    deletado,
    trim(cnes, ' ') AS cnes,
    trim(competen, ' ') AS competen,
    nullif(trim(codufmun, ' '), '') AS municipio_estabelecimento,
    nullif(trim(tp_unid, ' '), '') AS tipo_unidade,
    nullif(trim(tpgestao, ' '), '') AS tipo_gestao,
    nullif(trim(nat_jur, ' '), '') AS natureza_juridica,
    CASE WHEN deletado THEN 'deletado' END AS exclusao
FROM bruto
"""
_DISTINTOS_ST = """
SELECT DISTINCT
    CAST($competencia AS VARCHAR) AS competencia_arquivo,
    cnes,
    CAST($artefato AS VARCHAR) AS artifact_id,
    municipio_estabelecimento, tipo_unidade, tipo_gestao, natureza_juridica
FROM classificada WHERE exclusao IS NULL ORDER BY cnes
"""


class FamiliaReservada(FalhaOperacionalErro):
    """Fonte de família de regra reservada (SR, HB): sem esquema e sem tabela, nunca vazia."""


def carregar_leiautes_cnes(caminho: Path = CATALOGO_LEIAUTES) -> dict[FamiliaFonte, LayoutSpec]:
    """Leiautes do catálogo por fonte (CNES_PF, CNES_ST).

    Raises:
        ValueError: duas entradas para a mesma fonte.
    """
    leiautes: dict[FamiliaFonte, LayoutSpec] = {}
    for bruto in carregar_yaml(caminho)["leiautes"]:
        layout = LayoutSpec.model_validate(bruto)
        if layout.fonte in leiautes:
            raise ValueError(f"leiaute_repetido fonte={layout.fonte}")
        leiautes[layout.fonte] = layout
    return leiautes


def _inesperado(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, motivo)


def _fonte(artifact: ArtifactVersion, layout: LayoutSpec) -> FamiliaFonte:
    for fonte in (artifact.chave.fonte, layout.fonte):
        if fonte in RESERVADAS:
            raise FamiliaReservada(f"familia_reservada familia={RESERVADAS[fonte]} fonte={fonte}")
    if layout.fonte is not artifact.chave.fonte or layout.fonte not in _ESQUEMAS:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_LEIAUTE,
            f"fonte_incompativel layout={layout.layout_id} artefato={artifact.chave.fonte}",
        )
    return layout.fonte


def _bruto(leitura: LeituraDbf, fisicos: list[str]) -> pa.Table:
    tabela = leitura.tabela.select([COLUNA_DELETADO, *fisicos])
    return tabela.rename_columns(["deletado", *(nome.lower() for nome in fisicos)])


def _competencia(artifact: ArtifactVersion) -> str:
    competencia = artifact.chave.competencia_arquivo
    if competencia is None:
        raise _inesperado(f"competencia_divergente arquivo=None id={artifact.artifact_id}")
    return competencia.valor


def _conferir_competen(con: duckdb.DuckDBPyConnection, esperada: str) -> None:
    lidas = con.execute(
        "SELECT DISTINCT competen FROM classificada "
        "WHERE NOT deletado AND competen IS DISTINCT FROM $c ORDER BY 1",
        {"c": esperada},
    ).fetchall()
    if lidas:
        raise _inesperado(
            f"competencia_divergente arquivo={esperada} lidas={[linha[0] for linha in lidas]}"
        )


def _motivos(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    linhas = con.execute(
        "SELECT exclusao, count(*) FROM classificada WHERE exclusao IS NOT NULL GROUP BY 1"
    ).fetchall()
    return {str(motivo): int(total) for motivo, total in linhas}


def _validas(con: duckdb.DuckDBPyConnection) -> int:
    linha = con.execute("SELECT count(*) FROM classificada WHERE exclusao IS NULL").fetchone()
    return int(linha[0]) if linha else 0


def _relacao_pf(
    leitura: LeituraDbf, artifact: ArtifactVersion, runtime: RuntimeConfig
) -> tuple[pa.Table, dict[str, int]]:
    esperada = _competencia(artifact)
    with closing(conectar(runtime)) as con:
        con.register("bruto", _bruto(leitura, ["CNES", "CBO", "COMPETEN"]))
        con.execute(_CLASSIFICAR_PF, {"cnes": _CNES, "cbo": _CBO})
        _conferir_competen(con, esperada)
        motivos, validas = _motivos(con), _validas(con)
        parametros = {"competencia": esperada, "artefato": artifact.artifact_id}
        tabela = con.execute(_AGREGAR_PF, parametros).to_arrow_table()
    if validas > tabela.num_rows:
        motivos["agregada_em_contagem"] = validas - tabela.num_rows
    return tabela, motivos


def _relacao_st(
    leitura: LeituraDbf, artifact: ArtifactVersion, runtime: RuntimeConfig
) -> tuple[pa.Table, dict[str, int]]:
    esperada = _competencia(artifact)
    with closing(conectar(runtime)) as con:
        con.register("bruto", _bruto(leitura, ["CNES", "COMPETEN", *_ATRIBUTOS_ST]))
        con.execute(_CLASSIFICAR_ST)
        invalidos = con.execute(
            "SELECT count(*) FROM classificada WHERE NOT deletado "
            "AND NOT regexp_full_match(cnes, $cnes)",
            {"cnes": _CNES},
        ).fetchall()[0][0]
        if invalidos:
            raise _inesperado(f"codigo_invalido coluna=cnes linhas={invalidos}")
        _conferir_competen(con, esperada)
        motivos, validas = _motivos(con), _validas(con)
        parametros = {"competencia": esperada, "artefato": artifact.artifact_id}
        tabela = con.execute(_DISTINTOS_ST, parametros).to_arrow_table()
    if len(set(tabela.column("cnes").to_pylist())) != tabela.num_rows:
        raise _inesperado("chave_repetida schema=cnes_estabelecimento.v1")
    if validas > tabela.num_rows:
        motivos["duplicata_exata"] = validas - tabela.num_rows
    return tabela, motivos


def _no_esquema(tabela: pa.Table, esquema: EsquemaCanonico) -> pa.Table:
    tipos = {TipoCanonico.TEXTO: pa.string(), TipoCanonico.INTEIRO: pa.int64()}
    campos = [pa.field(c.nome, tipos[c.tipo], nullable=c.anulavel) for c in esquema.colunas]
    return tabela.select([c.nome for c in esquema.colunas]).cast(pa.schema(campos))


def normalize_cnes(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.SINTETICO,
) -> DatasetRef:
    """Normaliza um artefato do CNES para o esquema canônico da família.

    `origem_dados` padrão é SINTETICO (direção segura); a ingestão de dados reais passa REAL.

    Raises:
        FamiliaReservada: artefato ou leiaute de SR ou HB.
        QuarentenaLeitura: artefato não íntegro, leiaute incompatível, COMPETEN divergente, chave
            inválida ou repetida no ST, ou nenhuma linha válida.
        ArquivoAusente: conteúdo do artefato inexistente.
    """
    configuracao = runtime or RuntimeConfig()
    fonte = _fonte(artifact, layout)
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{_ESQUEMAS[fonte]}.yaml")
    leitura = ler_artefato_dbf(artifact, layout, configuracao)
    relacionar = _relacao_pf if fonte is FamiliaFonte.CNES_PF else _relacao_st
    tabela, motivos = relacionar(leitura, artifact, configuracao)
    if tabela.num_rows == 0:
        raise _inesperado(f"tabela_vazia layout={layout.layout_id} motivos={sorted(motivos)}")
    gravado = gravar_relacao(
        _no_esquema(tabela, esquema), esquema, out, artifact.artifact_id, configuracao
    )
    return _referencia(
        artifact,
        layout,
        gravado,
        (leitura.tabela.num_rows, motivos),
        esquema,
        origem_dados=origem_dados,
    )


def _referencia(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    gravado: tuple[str, str, Path],
    contagens: tuple[int, dict[str, int]],
    esquema: EsquemaCanonico,
    *,
    origem_dados: OrigemDados,
) -> DatasetRef:
    dataset_id, hash_logico, destino = gravado
    fisicos, motivos = contagens
    linhas = fisicos - sum(motivos.values())
    logger.info(
        "cnes_normalizado id=%s schema=%s linhas=%s excluidas=%s",
        artifact.artifact_id,
        esquema.schema_id,
        linhas,
        motivos,
    )
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=esquema.schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=(artifact.artifact_id,),
        origem_dados=origem_dados,
        produzido_por=(
            f"sustemporal.ingest.cnes.normalize_cnes/{layout.layout_id}"
            f"@{metadata.version('sus-temporal')}"
        ),
        reconciliacao=Reconciliacao(
            fisicos=fisicos,
            deletados=motivos.get("deletado", 0),
            canonicas=linhas,
            excluidas_por_motivo=motivos,
        ),
        multiplicidade=Multiplicidade(
            linhas_totais=linhas, combinacoes_distintas=linhas, max_repeticoes=1
        ),
    )
