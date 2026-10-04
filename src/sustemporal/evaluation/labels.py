"""Rótulos do PA_INDICA separados dos atributos (T03).

O rótulo vem do PA_INDICA bruto por um codebook versionado; código fora do codebook vira
DESCONHECIDO com o bruto preservado. Contradições entre rótulo e quantidades ou valores formam um
vocabulário fechado: são contadas, nunca corrigidas, e só avaliadas quando os insumos existem.
"""

from __future__ import annotations

import hashlib
import logging
import re
from contextlib import closing
from dataclasses import dataclass
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
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.dbf import compactar
from sustemporal.ingest.sia_pa import (
    ESQUEMA_PA,
    RAIZ_CATALOGO,
    TABELA,
    carregar_conferido,
    gravar_parquet,
    produtor,
)
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

ESQUEMA_ROTULOS = RAIZ_CATALOGO / "schemas" / "sia_pa_rotulos.yaml"
TABELA_ROTULOS = "sia_pa_rotulos"

DIMENSOES_PERFIL = (
    "competencia_processamento",
    "competencia_atendimento",
    "instrumento",
    "cnes",
)
CODEBOOK_PA = RAIZ_CATALOGO / "labels" / "sia_pa.yaml"
_CODIGO_INDICA = re.compile(r"[0-9a-z]{1,4}")

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
        if self.campo != "PA_INDICA":
            raise ValueError(f"codebook_campo_invalido campo={self.campo}")
        invalidos = sorted(c for c in self.codigos if not _CODIGO_INDICA.fullmatch(c))
        if invalidos:
            raise ValueError(f"codebook_codigo_invalido codigos={compactar(invalidos)}")
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


@dataclass(frozen=True)
class PerfilPa:
    """Perfil por estrato do bruto e do canônico, com reconciliação das contagens."""

    caminho: str
    linhas: int
    totais: dict[tuple[str, str], int]
    reconciliado: bool
    codebook_sha256: str


def _codigos_indica(codebook: Path) -> list[str]:
    conteudo = carregar_yaml(codebook)
    if not isinstance(conteudo, dict) or not isinstance(conteudo.get("codigos"), dict):
        raise ValueError(f"codebook_invalido caminho={codebook}")
    codigos = sorted(str(codigo) for codigo in conteudo["codigos"])
    invalidos = [codigo for codigo in codigos if not _CODIGO_INDICA.fullmatch(codigo)]
    if invalidos or not codigos:
        raise ValueError(f"codebook_codigo_invalido codigos={compactar(invalidos)}")
    return codigos


def _sql_perfil(codigos: list[str], colunas: set[str]) -> tuple[str, dict[str, object]]:
    parametros: dict[str, object] = {"codigos": codigos}
    indica = "trim(pa_indica, ' ')"
    apelidos = [identificador_seguro(f"indica_{c}", {f"indica_{c}"}) for c in codigos]
    contagens = [
        f"count(*) FILTER (WHERE {indica} = $c{i}) AS {apelido}"
        for i, apelido in enumerate(apelidos)
    ]
    parametros.update({f"c{i}": c for i, c in enumerate(codigos)})
    contagens.append(
        f"count(*) FILTER (WHERE pa_indica IS NULL OR NOT list_contains($codigos, {indica})) "
        "AS indica_outros"
    )
    blocos = []
    for dimensao in DIMENSOES_PERFIL:
        for origem, coluna in (("BRUTO", f"{dimensao}_bruto"), ("CANONICO", dimensao)):
            citada = identificador_seguro(coluna, colunas)
            parametros[f"d_{coluna}"] = dimensao
            parametros[f"o_{coluna}"] = origem
            blocos.append(
                f"SELECT $d_{coluna} AS dimensao, $o_{coluna} AS origem, {citada} AS valor, "  # noqa: S608
                f"count(*) AS linhas, count(*) FILTER (WHERE deletado) AS deletados, "
                f"{', '.join(contagens)} FROM {TABELA} GROUP BY {citada}"
            )
    ordem = " ORDER BY dimensao, origem, valor NULLS FIRST"
    return " UNION ALL ".join(blocos) + ordem, parametros


def perfil_pa(
    dataset: DatasetRef,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    codebook: Path | None = None,
) -> PerfilPa:
    """Contagens por competência, instrumento e estabelecimento, do bruto e do canônico.

    Cada estrato conta linhas, deletados e o PA_INDICA bruto pelos códigos do codebook (os
    demais em `indica_outros`); os totais de cada dimensão e origem devem reconciliar com o
    número de linhas do dataset.
    """
    caminho_codebook = codebook or CODEBOOK_PA
    codigos = _codigos_indica(caminho_codebook)
    codebook_sha256 = hashlib.sha256(caminho_codebook.read_bytes()).hexdigest()
    canonico = EsquemaCanonico.de_yaml(ESQUEMA_PA)
    with closing(conectar(runtime or RuntimeConfig())) as con:
        colunas = carregar_conferido(con, dataset, canonico, TABELA)
        sql, parametros = _sql_perfil(codigos, set(colunas))
        con.execute(f"CREATE TABLE perfil AS {sql}", parametros)
        destino = out / f"{dataset.dataset_id}.perfil.{codebook_sha256[:16]}.parquet"
        gravar_parquet(con, "perfil", destino)
        indicas = " + ".join(
            identificador_seguro(f"indica_{c}", {f"indica_{c}"}) for c in [*codigos, "outros"]
        )
        linhas = con.execute(
            "SELECT dimensao, origem, sum(linhas), sum(deletados), "  # noqa: S608
            f"bool_and(linhas = {indicas}) FROM perfil GROUP BY dimensao, origem"
        ).fetchall()
    totais = {(str(d), str(o)): int(n) for d, o, n, *_ in linhas}
    deletados = dataset.reconciliacao.deletados if dataset.reconciliacao else None
    reconciliado = all(
        n == dataset.linhas and indica and deletados in {None, int(d)}
        for _, _, n, d, indica in linhas
    )
    logger.info("perfil_sia_pa dataset=%s reconciliado=%s", dataset.dataset_id, reconciliado)
    return PerfilPa(str(destino), dataset.linhas, totais, reconciliado, codebook_sha256)
