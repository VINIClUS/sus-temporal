"""Rótulos do PA_INDICA separados dos atributos (T03).

O rótulo vem do PA_INDICA bruto por um codebook versionado; código fora do codebook vira
DESCONHECIDO com o bruto preservado. Contradições entre rótulo e quantidades ou valores formam um
vocabulário fechado: são contadas, nunca corrigidas, e só avaliadas quando os insumos existem.
"""

from __future__ import annotations

import logging
from contextlib import closing
from typing import TYPE_CHECKING

from pydantic import model_validator

from sustemporal.contracts import (
    CodigoRotulo,
    Confirmacao,
    ContratoBase,
    DatasetRef,
    DocRef,
    EsquemaCanonico,
    Identificador,
    Proveniencia,
    Reconciliacao,
    RuntimeConfig,
    calcular_dataset_id,
)
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import (
    ESQUEMA_PA,
    RAIZ_CATALOGO,
    TABELA,
    carregar_conferido,
    produtor,
)
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

ESQUEMA_ROTULOS = RAIZ_CATALOGO / "schemas" / "sia_pa_rotulos.yaml"
TABELA_ROTULOS = "sia_pa_rotulos"

CONTRADICOES = (
    "APROVADO_PARCIAL_SEM_REDUCAO",
    "APROVADO_SEM_QUANTIDADE_APROVADA",
    "APROVADO_TOTAL_COM_QUANTIDADE_DIVERGENTE",
    "APROVADO_TOTAL_COM_VALOR_DIVERGENTE",
    "NAO_APROVADO_COM_QUANTIDADE_APROVADA",
    "NAO_APROVADO_COM_VALOR_APROVADO",
    "QUANTIDADE_APROVADA_MAIOR_QUE_APRESENTADA",
    "VALOR_APROVADO_MAIOR_QUE_APRESENTADO",
)
_CONDICOES = {
    "APROVADO_PARCIAL_SEM_REDUCAO": ("rotulo = 'APROVADO_PARCIAL' AND qp = qa AND vp = va"),
    "APROVADO_SEM_QUANTIDADE_APROVADA": (
        "rotulo IN ('APROVADO_TOTAL', 'APROVADO_PARCIAL') AND qp = 0"
    ),
    "APROVADO_TOTAL_COM_QUANTIDADE_DIVERGENTE": "rotulo = 'APROVADO_TOTAL' AND qp <> qa",
    "APROVADO_TOTAL_COM_VALOR_DIVERGENTE": "rotulo = 'APROVADO_TOTAL' AND vp <> va",
    "NAO_APROVADO_COM_QUANTIDADE_APROVADA": "rotulo = 'NAO_APROVADO' AND qp > 0",
    "NAO_APROVADO_COM_VALOR_APROVADO": "rotulo = 'NAO_APROVADO' AND vp > 0",
    "QUANTIDADE_APROVADA_MAIOR_QUE_APRESENTADA": "qp > qa",
    "VALOR_APROVADO_MAIOR_QUE_APRESENTADO": "vp > va",
}


class Codebook(ContratoBase):
    """Codebook versionado de PA_INDICA (catalog/labels/)."""

    codebook_id: Identificador
    campo: str
    proveniencia: Proveniencia
    confirmacao: Confirmacao
    documento: DocRef
    codigos: dict[str, CodigoRotulo]
    contradicoes: dict[str, str]

    @model_validator(mode="after")
    def _vocabulario_fechado(self) -> Codebook:
        if tuple(sorted(self.contradicoes)) != CONTRADICOES:
            raise ValueError(f"codebook_contradicoes_fora_do_vocabulario id={self.codebook_id}")
        if CodigoRotulo.DESCONHECIDO in self.codigos.values():
            raise ValueError(f"codebook_mapeia_desconhecido id={self.codebook_id}")
        return self


def carregar_codebook(caminho: Path) -> Codebook:
    return Codebook.model_validate(carregar_yaml(caminho))


def _sql_rotulos(codebook: Codebook) -> tuple[str, dict[str, object]]:
    parametros: dict[str, object] = {
        "codebook_id": codebook.codebook_id,
        "desconhecido": CodigoRotulo.DESCONHECIDO.value,
    }
    casos = []
    for i, (codigo, rotulo) in enumerate(sorted(codebook.codigos.items())):
        parametros[f"c{i}"], parametros[f"r{i}"] = codigo, rotulo.value
        casos.append(f"WHEN $c{i} THEN $r{i}")
    rotulo_sql = f"CASE trim(pa_indica, ' ') {' '.join(casos)} ELSE $desconhecido END"
    marcas = []
    for i, codigo in enumerate(CONTRADICOES):
        parametros[f"k{i}"] = codigo
        marcas.append(f"CASE WHEN {_CONDICOES[codigo]} THEN $k{i} END")
    lista = f"list_filter([{', '.join(marcas)}], lambda x: x IS NOT NULL)"
    base = (
        f"SELECT row_id, indice_registro, pa_indica, {rotulo_sql} AS rotulo, "  # noqa: S608
        "quantidade_apresentada AS qa, quantidade_aprovada AS qp, "
        f"valor_apresentado AS va, valor_aprovado AS vp FROM {TABELA}"
    )
    sql = (
        f"CREATE TABLE {TABELA_ROTULOS} AS SELECT row_id, pa_indica AS pa_indica_bruto, "  # noqa: S608
        "rotulo, $codebook_id AS codebook_id, qa AS quantidade_apresentada, "
        "qp AS quantidade_aprovada, va AS valor_apresentado, vp AS valor_aprovado, "
        f"array_to_string({lista}, ';') AS contradicoes FROM ({base}) ORDER BY indice_registro"
    )
    return sql, parametros


def label_pa(
    dataset: DatasetRef, codebook: Path, out: Path, *, runtime: RuntimeConfig | None = None
) -> DatasetRef:
    """Gera a tabela de rótulos preservando o valor bruto e a origem do código.

    Raises:
        ValueError: dataset divergente da referência (estrutura, contagem ou hash lógico) ou
            codebook fora do vocabulário fechado.
    """
    livro = carregar_codebook(codebook)
    rotulos = EsquemaCanonico.de_yaml(ESQUEMA_ROTULOS)
    colunas = [coluna.nome for coluna in rotulos.colunas]
    with closing(conectar(runtime or RuntimeConfig())) as con:
        carregar_conferido(con, dataset, EsquemaCanonico.de_yaml(ESQUEMA_PA), TABELA)
        sql, parametros = _sql_rotulos(livro)
        con.execute(sql, parametros)
        hash_logico = hash_logico_relacao(con, TABELA_ROTULOS, colunas)
        dataset_id = calcular_dataset_id(rotulos.schema_id, hash_logico, dataset.artifact_ids)
        destino = out / f"{dataset_id}.parquet"
        temporario = destino.with_name(f".{destino.name}.tmp")
        con.table(TABELA_ROTULOS).write_parquet(str(temporario))
        temporario.replace(destino)
        contagem = con.execute(f"SELECT count(*) FROM {TABELA_ROTULOS}").fetchone()  # noqa: S608
    linhas = int(contagem[0]) if contagem else 0
    logger.info(
        "rotulos_sia_pa dataset=%s linhas=%s codebook=%s", dataset_id, linhas, livro.codebook_id
    )
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=rotulos.schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=dataset.artifact_ids,
        origem_dados=dataset.origem_dados,
        produzido_por=produtor(f"evaluation.labels.label_pa/{livro.codebook_id}"),
        reconciliacao=Reconciliacao(fisicos=dataset.linhas, canonicas=linhas),
    )
