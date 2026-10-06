"""Comparação de arquivos Parquet pelo hash lógico: conjuntos, saídas e execuções (T14).

Dois arquivos valem o mesmo conteúdo quando as linhas e o hash lógico (multiconjunto de linhas, nas
colunas do esquema) coincidem; os bytes do Parquet podem diferir (compressão, ordem das linhas,
metadados) e são relatados à parte, nunca como divergência. As saídas das execuções repetem o
`run_id`, que depende dos caminhos da configuração: nelas o hash lógico deixa de fora essa coluna.
"""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao, sha256_arquivo
from sustemporal.reporting.reproduce_esquema import (
    colunas_que_diferem,
    colunas_que_diferem_entre,
    leiaute_do_arquivo,
)
from sustemporal.reporting.reproduce_itens import Comparacao, Situacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.temporal import MetodoId
    from sustemporal.reporting.reproduce_esquema import Leiaute

__all__ = [
    "Identidade",
    "comparar_execucoes",
    "comparar_referencia",
    "comparar_saida",
    "comparar_saidas",
    "identidade_do_arquivo",
    "saidas_por_esquema",
    "saidas_por_metodo",
]

logger = logging.getLogger(__name__)

_TABELA = "reproducao_conferencia"
_MAX_ARTEFATOS = 5
_RUNTIME = RuntimeConfig(duckdb_threads=1)


@dataclass(frozen=True)
class Identidade:
    """Contagem, hash lógico e SHA-256 dos bytes de um Parquet, e o leiaute físico lido dele.

    `divergentes` traz as colunas em que o leiaute não é o do esquema; nesse caso a contagem e o
    hash lógico não foram calculados (`0` e vazio).
    """

    linhas: int
    hash_logico: str
    sha256: str
    leiaute: Leiaute = ()
    divergentes: tuple[str, ...] = ()


def identidade_do_arquivo(
    caminho: Path, schema_id: str, *, sem_colunas: Collection[str] = ()
) -> Identidade:
    """Linhas e hash lógico do Parquet nas colunas do esquema (menos `sem_colunas`) e seus bytes.

    O leiaute do arquivo tem de ser o do esquema (nomes, ordem e tipos), inclusive a coluna de
    identidade que `sem_colunas` tira do hash: senão `divergentes` traz as colunas e nada se
    calcula. `sem_colunas` que o esquema não tem (a saída sem `run_id`) não tira nada.

    Raises:
        FalhaOperacionalErro: arquivo ausente ou ilegível.
    """
    esquema = carregar_esquema(schema_id)
    try:
        with closing(conectar(_RUNTIME)) as con:
            leiaute = leiaute_do_arquivo(con, caminho)
            if diferentes := colunas_que_diferem(esquema, leiaute):
                return Identidade(0, "", sha256_arquivo(caminho), leiaute, tuple(diferentes))
            colunas = [c.nome for c in esquema.colunas if c.nome not in sem_colunas]
            projecao = ", ".join(identificador_seguro(nome, colunas) for nome in colunas)
            con.execute(
                f"CREATE TEMP TABLE {_TABELA} AS SELECT {projecao} "  # noqa: S608
                "FROM read_parquet($c)",
                {"c": str(caminho)},
            )
            linhas = int(con.execute(f"SELECT count(*) FROM {_TABELA}").fetchall()[0][0])  # noqa: S608
            hash_logico = hash_logico_relacao(con, _TABELA, colunas)
        return Identidade(linhas, hash_logico, sha256_arquivo(caminho), leiaute)
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


def _esquema_divergente(item: str, colunas: Iterable[str], lado: str) -> Comparacao:
    detalhe = f"esquema_divergente colunas={','.join(colunas)} lado={lado}"
    return Comparacao(item, Situacao.DIVERGENTE, None, None, detalhe)


def _esquema_dos_lados(item: str, antigo: Identidade, refeito: Identidade) -> Comparacao | None:
    """Divergência de esquema do refeito, do original ou de tipo físico entre os dois."""
    for lado, identidade in (("refeito", refeito), ("original", antigo)):
        if identidade.divergentes:
            return _esquema_divergente(item, identidade.divergentes, lado)
    entre = colunas_que_diferem_entre(antigo.leiaute, refeito.leiaute)
    return _esquema_divergente(item, entre, "original_e_refeito") if entre else None


def _linhagem_diverge(item: str, esperada: DatasetRef, obtida: DatasetRef) -> Comparacao | None:
    """Divergência se os artefatos de origem das duas referências não são os mesmos.

    A comparação é de multiconjuntos: o mesmo conteúdo vindo de outros arquivos não é a mesma
    reprodução, e o `dataset_id` das saídas depende do `run_id`, então só os artefatos valem.
    """
    antigos, novos = Counter(esperada.artifact_ids), Counter(obtida.artifact_ids)
    diferentes = sorted(((antigos - novos) + (novos - antigos)).elements())
    if not diferentes:
        return None
    nomes = ",".join(diferentes[:_MAX_ARTEFATOS])
    detalhe = f"linhagem_diverge diferentes={len(diferentes)} primeiros={nomes}"
    esperado = f"artefatos={len(esperada.artifact_ids)}"
    return Comparacao(
        item, Situacao.DIVERGENTE, esperado, f"artefatos={len(obtida.artifact_ids)}", detalhe
    )


def comparar_referencia(item: str, esperada: DatasetRef, obtida: DatasetRef) -> Comparacao:
    """O conjunto refeito contra o declarado no manifesto e, se existe, contra o arquivo original.

    O hash lógico do refeito é recalculado do arquivo, nunca lido do `DatasetRef`. Original
    adulterado (que não confere com o declarado) é divergência, não bytes diferentes. O leiaute
    dos arquivos é conferido antes do hash (`esquema_divergente`) e, depois do conteúdo, a linhagem
    (`linhagem_diverge`).
    """
    declarado = f"{esperada.linhas}:{esperada.hash_logico}"
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id)
    if refeito.divergentes:
        return _esquema_divergente(item, refeito.divergentes, "refeito")
    if (refeito.linhas, refeito.hash_logico) != (esperada.linhas, esperada.hash_logico):
        return Comparacao(item, Situacao.DIVERGENTE, declarado, _texto(refeito), "refeito_diverge")
    if (linhagem := _linhagem_diverge(item, esperada, obtida)) is not None:
        return linhagem
    original = _arquivo_existente(esperada)
    if original is None:
        return Comparacao(item, Situacao.IGUAL, declarado, declarado, "original_ausente")
    antigo = _identidade_do_original(original, esperada.schema_id)
    if antigo is None:
        return Comparacao(item, Situacao.IGUAL, declarado, declarado, "original_ilegivel")
    return _contra_o_original(item, esperada, antigo, refeito)


def _contra_o_original(
    item: str, esperada: DatasetRef, antigo: Identidade, refeito: Identidade
) -> Comparacao:
    declarado = f"{esperada.linhas}:{esperada.hash_logico}"
    if (divergente := _esquema_dos_lados(item, antigo, refeito)) is not None:
        return divergente
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
    """A saída refeita contra a original, recalculando as duas sem as colunas de identidade.

    Antes, o leiaute completo das duas (nomes, ordem e tipos) tem de ser o do esquema e o mesmo
    nos dois lados: a coluna de identidade ausente, a coluna a mais ou de outro tipo e a ordem
    trocada são `esquema_divergente`, nunca igualdade pela interseção das colunas. Com o mesmo
    conteúdo, os artefatos de origem também têm de ser os mesmos (`linhagem_diverge`).
    """
    caminho = _arquivo_existente(original) if original is not None else None
    if original is None or caminho is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, None, "original_ausente")
    antigo = _identidade_do_original(caminho, original.schema_id, sem_colunas=sem_colunas)
    if antigo is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, None, "original_ilegivel")
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id, sem_colunas=sem_colunas)
    if (divergente := _esquema_dos_lados(item, antigo, refeito)) is not None:
        return divergente
    detalhe = f"sem_colunas={','.join(sorted(sem_colunas))}"
    if (antigo.linhas, antigo.hash_logico) != (refeito.linhas, refeito.hash_logico):
        return Comparacao(item, Situacao.DIVERGENTE, _texto(antigo), _texto(refeito), detalhe)
    if (linhagem := _linhagem_diverge(item, original, obtida)) is not None:
        return linhagem
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


def saidas_por_esquema(saidas: Iterable[DatasetRef]) -> dict[str, DatasetRef]:
    """As saídas por `schema_id`; a repetição entra como `<schema_id>#2`, `#3`... na ordem dada.

    Nenhuma saída some: duas do mesmo esquema na mesma execução viram duas chaves, e o
    `schema_id` nunca tem `#`, então a chave repetida não colide com um esquema.
    """
    vistas: Counter[str] = Counter()
    por_esquema: dict[str, DatasetRef] = {}
    for saida in saidas:
        vistas[saida.schema_id] += 1
        vez = vistas[saida.schema_id]
        por_esquema[saida.schema_id if vez == 1 else f"{saida.schema_id}#{vez}"] = saida
    return por_esquema


def saidas_por_metodo(
    execucoes: Mapping[MetodoId, RunResult],
) -> dict[str, dict[str, DatasetRef]]:
    """As saídas de cada execução, por método (`valor`) e `schema_id` (`saidas_por_esquema`)."""
    return {metodo.value: saidas_por_esquema(run.saidas) for metodo, run in execucoes.items()}


def _arquivo(ref: DatasetRef) -> Path:
    return Path(ref.caminho)


def _arquivo_existente(ref: DatasetRef) -> Path | None:
    caminho = _arquivo(ref)
    return caminho if caminho.is_file() else None
