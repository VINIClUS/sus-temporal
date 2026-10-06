"""Comparação de arquivos Parquet pelo hash lógico: conjuntos, saídas e execuções (T14).

Dois arquivos valem o mesmo conteúdo quando as linhas e o hash lógico (multiconjunto de linhas, nas
colunas do esquema) coincidem; os bytes do Parquet podem diferir (compressão, ordem das linhas,
metadados) e são relatados à parte, nunca como divergência. As saídas das execuções repetem o
`run_id`, que depende dos caminhos da configuração: nelas o hash lógico deixa de fora essa coluna.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao, sha256_arquivo
from sustemporal.reporting.reproduce_itens import Comparacao, Situacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from sustemporal.contracts.records import DatasetRef

__all__ = [
    "Identidade",
    "comparar_execucoes",
    "comparar_referencia",
    "comparar_saida",
    "comparar_saidas",
    "identidade_do_arquivo",
]

logger = logging.getLogger(__name__)

_TABELA = "reproducao_conferencia"
_RUNTIME = RuntimeConfig(duckdb_threads=1)


@dataclass(frozen=True)
class Identidade:
    """Contagem, hash lógico e SHA-256 dos bytes de um Parquet."""

    linhas: int
    hash_logico: str
    sha256: str


def identidade_do_arquivo(
    caminho: Path, schema_id: str, *, sem_colunas: Collection[str] = ()
) -> Identidade:
    """Linhas e hash lógico do Parquet nas colunas do esquema (menos `sem_colunas`) e seus bytes.

    Raises:
        FalhaOperacionalErro: arquivo ausente ou ilegível.
    """
    esquema = [coluna.nome for coluna in carregar_esquema(schema_id).colunas]
    try:
        with closing(conectar(_RUNTIME)) as con:
            descricao = con.execute(
                "DESCRIBE SELECT * FROM read_parquet($c)", {"c": str(caminho)}
            ).fetchall()
            fisicas = {str(linha[0]) for linha in descricao}
            colunas = [c for c in esquema if c in fisicas and c not in sem_colunas]
            projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
            con.execute(
                f"CREATE TEMP TABLE {_TABELA} AS SELECT {projecao} "  # noqa: S608
                "FROM read_parquet($c)",
                {"c": str(caminho)},
            )
            linhas = int(con.execute(f"SELECT count(*) FROM {_TABELA}").fetchall()[0][0])  # noqa: S608
            hash_logico = hash_logico_relacao(con, _TABELA, colunas)
        return Identidade(linhas, hash_logico, sha256_arquivo(caminho))
    except (duckdb.Error, OSError) as erro:
        raise FalhaOperacionalErro(f"arquivo_ilegivel caminho={caminho} erro={erro}") from erro


def _identidade_do_original(
    caminho: Path, schema_id: str, *, sem_colunas: Collection[str] = ()
) -> Identidade | None:
    """A identidade do arquivo original; `None` se ele existe mas não pode ser lido."""
    try:
        return identidade_do_arquivo(caminho, schema_id, sem_colunas=sem_colunas)
    except FalhaOperacionalErro:
        logger.warning("original_ilegivel caminho=%s", caminho)
        return None


# Só para exibir: as condições comparam os atributos, porque o SonarCloud acusa S2583 (falso
# positivo) quando as duas pontas da comparação são chamadas da mesma função.
def _texto(identidade: Identidade) -> str:
    return f"{identidade.linhas}:{identidade.hash_logico}"


def comparar_referencia(item: str, esperada: DatasetRef, obtida: DatasetRef) -> Comparacao:
    """O conjunto refeito contra o declarado no manifesto e, se existe, contra o arquivo original.

    O hash lógico do refeito é recalculado do arquivo, nunca lido do `DatasetRef`. Original
    adulterado (que não confere com o declarado) é divergência, não bytes diferentes.
    """
    declarado = f"{esperada.linhas}:{esperada.hash_logico}"
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id)
    if (refeito.linhas, refeito.hash_logico) != (esperada.linhas, esperada.hash_logico):
        return Comparacao(item, Situacao.DIVERGENTE, declarado, _texto(refeito), "refeito_diverge")
    original = _arquivo_existente(esperada)
    if original is None:
        return Comparacao(item, Situacao.IGUAL, declarado, declarado, "original_ausente")
    antigo = _identidade_do_original(original, esperada.schema_id)
    if antigo is None:
        return Comparacao(item, Situacao.IGUAL, declarado, declarado, "original_ilegivel")
    if (antigo.linhas, antigo.hash_logico) != (esperada.linhas, esperada.hash_logico):
        return Comparacao(item, Situacao.DIVERGENTE, declarado, _texto(antigo), "original_diverge")
    if antigo.sha256 != refeito.sha256:
        return Comparacao(item, Situacao.BYTES_DIFERENTES, declarado, declarado, "bytes_diferem")
    return Comparacao(item, Situacao.IGUAL, declarado, declarado)


def comparar_saida(
    item: str,
    original: DatasetRef | None,
    obtida: DatasetRef,
    *,
    sem_colunas: Collection[str] = ("run_id",),
) -> Comparacao:
    """A saída refeita contra a original, recalculando as duas sem as colunas de identidade."""
    caminho = _arquivo_existente(original) if original is not None else None
    if original is None or caminho is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, None, "original_ausente")
    antigo = _identidade_do_original(caminho, original.schema_id, sem_colunas=sem_colunas)
    if antigo is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, None, "original_ilegivel")
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id, sem_colunas=sem_colunas)
    detalhe = f"sem_colunas={','.join(sorted(sem_colunas))}"
    if (antigo.linhas, antigo.hash_logico) != (refeito.linhas, refeito.hash_logico):
        return Comparacao(item, Situacao.DIVERGENTE, _texto(antigo), _texto(refeito), detalhe)
    return Comparacao(item, Situacao.IGUAL, _texto(antigo), _texto(refeito), detalhe)


def comparar_saidas(
    metodo: str,
    originais: Mapping[str, DatasetRef] | None,
    refeitas: Mapping[str, DatasetRef] | None,
) -> list[Comparacao]:
    """As saídas da execução refeita contra as da registrada, pela união dos `schema_id`.

    `None` é a execução que não existe: sem a registrada não há original para comparar e a saída
    refeita fica inconclusiva. Com as duas, a saída registrada que a refeita não emitiu e a saída
    nova sem original são divergência de conteúdo, não inconclusão.
    """
    antigas, novas = originais or {}, refeitas or {}
    itens = []
    for schema_id in dict.fromkeys([*novas, *antigas]):
        item = f"saida:{metodo}:{schema_id}"
        if schema_id not in novas:
            itens.append(
                Comparacao(item, Situacao.DIVERGENTE, None, None, "saida_ausente_no_refeito")
            )
        elif schema_id not in antigas and originais is not None:
            itens.append(Comparacao(item, Situacao.DIVERGENTE, None, None, "saida_sem_original"))
        else:
            itens.append(comparar_saida(item, antigas.get(schema_id), novas[schema_id]))
    return itens


def comparar_execucoes(
    originais: Mapping[str, Mapping[str, DatasetRef]],
    refeitas: Mapping[str, Mapping[str, DatasetRef]],
) -> list[Comparacao]:
    """As saídas de cada método (`{método: {schema_id: saída}}`); primeiro os métodos refeitos.

    Método que só a execução registrada tem é execução que a reconstrução não refez (toda saída
    registrada diverge); o que só o refeito tem não tem execução registrada (inconclusivo).
    """
    itens = []
    for metodo in dict.fromkeys([*refeitas, *originais]):
        itens += comparar_saidas(metodo, originais.get(metodo), refeitas.get(metodo))
    return itens


def _arquivo(ref: DatasetRef) -> Path:
    return Path(ref.caminho)


def _arquivo_existente(ref: DatasetRef) -> Path | None:
    caminho = _arquivo(ref)
    return caminho if caminho.is_file() else None
