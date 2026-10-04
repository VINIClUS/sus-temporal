"""Comparação de duas versões de conteúdo de um arquivo publicado (T13).

As duas versões são normalizadas para o esquema canônico e comparadas como multiconjuntos de
linhas ativas (não deletadas), sem as colunas de papel CHAVE e LINHAGEM do esquema `sia_pa.v1`.
Linhas nunca são casadas por posição: sem identificador longitudinal, a comparação só conta
linhas que saíram e que entraram. As deletadas de cada versão são contadas à parte, e a
transição de deleção nunca é inferida por casamento de valores.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sustemporal.contracts.records import EsquemaCanonico, PapelColuna
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.ingest.sia_pa import ESQUEMA_PA, normalize_pa

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import ArtifactVersion, LayoutSpec
    from sustemporal.contracts.base import OrigemDados
    from sustemporal.contracts.config import RuntimeConfig

__all__ = [
    "ComparacaoVersoes",
    "ResultadoComparacao",
    "colunas_fora_da_comparacao",
    "comparar_versoes",
]

logger = logging.getLogger(__name__)

_DELETADO = "deletado"


class ResultadoComparacao(StrEnum):
    INALTERADA = "INALTERADA"
    REVISAO_REAL = "REVISAO_REAL"
    CORRESPONDENCIA_AMBIGUA = "CORRESPONDENCIA_AMBIGUA"
    ARQUIVO_NOVO = "ARQUIVO_NOVO"
    ARQUIVO_SUMIU = "ARQUIVO_SUMIU"
    BYTES_ALTERADOS_SEM_COMPARACAO = "BYTES_ALTERADOS_SEM_COMPARACAO"
    INCONCLUSIVO = "INCONCLUSIVO"


@dataclass(frozen=True)
class ComparacaoVersoes:
    anterior: str | None
    nova: str | None
    resultado: ResultadoComparacao
    linhas_removidas: int
    linhas_adicionadas: int
    motivo: str
    deletadas_anterior: int = 0
    deletadas_nova: int = 0


def comparar_versoes(
    anterior: ArtifactVersion,
    nova: ArtifactVersion,
    *,
    layout: LayoutSpec,
    runtime: RuntimeConfig,
    destino: Path,
    origem_dados: OrigemDados,
) -> ComparacaoVersoes:
    """Compara duas versões da mesma chave de arquivo SIA-PA por multiconjunto de linhas.

    INALTERADA: mesmos bytes, ou as mesmas linhas canônicas com as mesmas multiplicidades.
    REVISAO_REAL: só entraram linhas, ou só saíram; a diferença dispensa pareamento.
    CORRESPONDENCIA_AMBIGUA: saíram e entraram linhas. O conteúdo mudou, mas sem identificador
    longitudinal não se sabe que linha antiga virou qual nova; nada é pareado.

    Raises:
        ValueError: versões de chaves diferentes.
        QuarentenaLeitura: alguma versão não passa na normalização.
        ArquivoAusente: conteúdo de alguma versão inexistente.
    """
    _exigir_mesma_chave(anterior, nova)
    ids = (anterior.artifact_id, nova.artifact_id)
    if anterior.artifact_id == nova.artifact_id:
        return ComparacaoVersoes(*ids, ResultadoComparacao.INALTERADA, 0, 0, "mesma_versao")
    caminhos = []
    for versao in (anterior, nova):
        saida = destino / versao.artifact_id
        saida.mkdir(parents=True, exist_ok=True)
        ref = normalize_pa(versao, layout, saida, runtime=runtime, origem_dados=origem_dados)
        caminhos.append(ref.caminho)
    with closing(conectar(runtime)) as con:
        removidas, adicionadas = _diferencas(con, caminhos[0], caminhos[1])
        deletadas = (_deletadas(con, caminhos[0]), _deletadas(con, caminhos[1]))
    resultado, motivo = _classificar(removidas, adicionadas)
    if deletadas[0] != deletadas[1]:
        motivo += (
            f" transicao_de_delecao_ambigua deletadas_anterior={deletadas[0]} "
            f"deletadas_nova={deletadas[1]}"
        )
    logger.info(
        "versoes_comparadas anterior=%s nova=%s resultado=%s removidas=%d adicionadas=%d",
        *ids,
        resultado,
        removidas,
        adicionadas,
    )
    return ComparacaoVersoes(*ids, resultado, removidas, adicionadas, motivo, *deletadas)


def _exigir_mesma_chave(anterior: ArtifactVersion, nova: ArtifactVersion) -> None:
    def chave(v: ArtifactVersion) -> tuple[object, ...]:
        return (v.chave.fonte, v.chave.uf, v.chave.competencia_arquivo, v.chave.parte)

    if chave(anterior) != chave(nova):
        raise ValueError(
            f"versoes_de_chaves_diferentes anterior={anterior.artifact_id} nova={nova.artifact_id}"
        )


def colunas_fora_da_comparacao(esquema: Path = ESQUEMA_PA) -> frozenset[str]:
    """Colunas de papel CHAVE e LINHAGEM do esquema (inclui `deletado`, tratado à parte)."""
    canonico = EsquemaCanonico.de_yaml(esquema)
    papeis = (PapelColuna.CHAVE, PapelColuna.LINHAGEM)
    return frozenset(nome for papel in papeis for nome in canonico.colunas_com_papel(papel))


def _colunas(con: duckdb.DuckDBPyConnection, caminho: str, fora: frozenset[str]) -> list[str]:
    descricao = con.execute("DESCRIBE SELECT * FROM read_parquet($c)", {"c": caminho}).fetchall()
    return [str(linha[0]) for linha in descricao if str(linha[0]) not in fora]


def _deletadas(con: duckdb.DuckDBPyConnection, caminho: str) -> int:
    consulta = f"SELECT count(*) FROM read_parquet($c) WHERE {_DELETADO}"  # noqa: S608
    return int(con.execute(consulta, {"c": caminho}).fetchall()[0][0])


def _diferencas(con: duckdb.DuckDBPyConnection, anterior: str, nova: str) -> tuple[int, int]:
    """Saídas e entradas entre as linhas ativas (EXCEPT ALL: multiplicidade, nulos iguais)."""
    fora = colunas_fora_da_comparacao()
    colunas = _colunas(con, anterior, fora)
    if colunas != _colunas(con, nova, fora):
        raise ValueError(f"esquemas_divergentes anterior={anterior} nova={nova}")
    lista = ", ".join(identificador_seguro(c, colunas) for c in colunas)

    def ativas(parametro: str) -> str:
        return f"SELECT {lista} FROM read_parquet(${parametro}) WHERE NOT {_DELETADO}"  # noqa: S608

    def contar(de: str, menos: str) -> int:
        consulta = f"SELECT count(*) FROM ({ativas(de)} EXCEPT ALL {ativas(menos)})"  # noqa: S608
        return int(con.execute(consulta, {"a": anterior, "b": nova}).fetchall()[0][0])

    return contar("a", "b"), contar("b", "a")


def _classificar(removidas: int, adicionadas: int) -> tuple[ResultadoComparacao, str]:
    contagem = f"removidas={removidas} adicionadas={adicionadas}"
    if not removidas and not adicionadas:
        return ResultadoComparacao.INALTERADA, "mesmo_multiconjunto_de_linhas"
    if removidas and adicionadas:
        motivo = f"correspondencia_ambigua {contagem} sem_pareamento"
        return ResultadoComparacao.CORRESPONDENCIA_AMBIGUA, motivo
    return ResultadoComparacao.REVISAO_REAL, f"revisao_real {contagem}"
