"""Comparação do refeito com o congelado: hash lógico, contagens e métricas (T14).

Dois arquivos valem o mesmo conteúdo quando as linhas e o hash lógico (multiconjunto de linhas, nas
colunas do esquema) coincidem; os bytes do Parquet podem diferir (compressão, ordem das linhas,
metadados) e são relatados à parte, nunca como divergência. As saídas das execuções repetem o
`run_id`, que depende dos caminhos da configuração: nelas o hash lógico deixa de fora essa coluna.
Divergência de conteúdo é `DIVERGENTE`; o que não tem original para comparar é `INCONCLUSIVO`, nunca
violação.
"""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from sustemporal.contracts.base import json_canonico
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.freeze_entrada import campos_divergentes
from sustemporal.hashing import hash_logico_relacao, sha256_arquivo
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from sustemporal.contracts.evaluation import ValorMetrica
    from sustemporal.contracts.experiment import CodeVersion, Particao, SplitManifest
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = [
    "Comparacao",
    "Identidade",
    "Situacao",
    "comparar_insumos",
    "comparar_metricas",
    "comparar_notas",
    "comparar_originais",
    "comparar_referencia",
    "comparar_saida",
    "comparar_split",
    "exigir_conferido",
    "identidade_do_arquivo",
    "observacoes_do_ambiente",
    "resultado_geral",
    "rodada_registrada",
]

logger = logging.getLogger(__name__)

_TABELA = "reproducao_conferencia"
_RUNTIME = RuntimeConfig(duckdb_threads=1)
_MAX_NOMES = 5
_MAX_TEXTO = 80
_NORMALIZADO = "NORMALIZADO"
_AUSENTE_DO_INGEST = "AUSENTE_DO_INGEST"
_SEM_PARTICAO = "particao_ausente"


class Situacao(StrEnum):
    IGUAL = "IGUAL"
    BYTES_DIFERENTES = "BYTES_DIFERENTES_HASH_LOGICO_IGUAL"
    DIVERGENTE = "DIVERGENTE"
    INCONCLUSIVO = "INCONCLUSIVO"


@dataclass(frozen=True)
class Identidade:
    """Contagem, hash lógico e SHA-256 dos bytes de um Parquet."""

    linhas: int
    hash_logico: str
    sha256: str


@dataclass(frozen=True)
class Comparacao:
    """Um item comparado: o que se esperava, o que se obteve e a situação."""

    item: str
    situacao: Situacao
    esperado: str | None = None
    obtido: str | None = None
    detalhe: str = ""

    def como_dict(self) -> dict[str, Any]:
        return {
            "item": self.item,
            "situacao": self.situacao.value,
            "esperado": self.esperado,
            "obtido": self.obtido,
            "detalhe": self.detalhe,
        }


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


def _texto(identidade: Identidade) -> str:
    return f"{identidade.linhas}:{identidade.hash_logico}"


def comparar_referencia(item: str, esperada: DatasetRef, obtida: DatasetRef) -> Comparacao:
    """O conjunto refeito contra o declarado no manifesto e, se existe, contra o arquivo original.

    O hash lógico do refeito é recalculado do arquivo, nunca lido do `DatasetRef`. Original
    adulterado (que não confere com o declarado) é divergência, não bytes diferentes.
    """
    declarado = f"{esperada.linhas}:{esperada.hash_logico}"
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id)
    if _texto(refeito) != declarado:
        return Comparacao(item, Situacao.DIVERGENTE, declarado, _texto(refeito), "refeito_diverge")
    original = _arquivo_existente(esperada)
    if original is None:
        return Comparacao(item, Situacao.IGUAL, declarado, declarado, "original_ausente")
    antigo = identidade_do_arquivo(original, esperada.schema_id)
    if _texto(antigo) != declarado:
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
    antigo = identidade_do_arquivo(caminho, original.schema_id, sem_colunas=sem_colunas)
    refeito = identidade_do_arquivo(_arquivo(obtida), obtida.schema_id, sem_colunas=sem_colunas)
    detalhe = f"sem_colunas={','.join(sorted(sem_colunas))}"
    if _texto(antigo) != _texto(refeito):
        return Comparacao(item, Situacao.DIVERGENTE, _texto(antigo), _texto(refeito), detalhe)
    return Comparacao(item, Situacao.IGUAL, _texto(antigo), _texto(refeito), detalhe)


def _arquivo(ref: DatasetRef) -> Path:
    return Path(ref.caminho)


def _arquivo_existente(ref: DatasetRef) -> Path | None:
    caminho = _arquivo(ref)
    return caminho if caminho.is_file() else None


def _chave(metrica: ValorMetrica) -> tuple[str, str]:
    return (metrica.nome, metrica.estrato)


def comparar_metricas(
    item: str, esperadas: Sequence[ValorMetrica] | None, obtidas: Sequence[ValorMetrica]
) -> Comparacao:
    """Métricas iguais campo a campo (numerador, denominador, valor, intervalo), por nome e estrato.

    Sem as esperadas (relatório original ausente) a comparação é inconclusiva.
    """
    if esperadas is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, str(len(obtidas)), "original_ausente")
    antigas = {_chave(m): json_canonico(m.model_dump(mode="json")) for m in esperadas}
    novas = {_chave(m): json_canonico(m.model_dump(mode="json")) for m in obtidas}
    diferentes = sorted(c for c in antigas.keys() & novas.keys() if antigas[c] != novas[c])
    faltando = sorted(antigas.keys() - novas.keys())
    sobrando = sorted(novas.keys() - antigas.keys())
    esperado, obtido = str(len(antigas)), str(len(novas))
    if not (diferentes or faltando or sobrando):
        return Comparacao(item, Situacao.IGUAL, esperado, obtido)
    nomes = [f"{n}[{e}]" for n, e in [*diferentes, *faltando, *sobrando][:_MAX_NOMES]]
    detalhe = (
        f"diferentes={len(diferentes)} faltando={len(faltando)} sobrando={len(sobrando)} "
        f"primeiras={','.join(nomes)}"
    )
    return Comparacao(item, Situacao.DIVERGENTE, esperado, obtido, detalhe)


def comparar_insumos(
    item: str, congeladas: Mapping[str, str] | None, entrada: EntradaValidacao
) -> Comparacao:
    """A entrada de validação refeita contra a identidade congelada, campo a campo."""
    if congeladas is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, None, "politica_sem_insumo_congelado")
    campos = campos_divergentes(congeladas, entrada)
    if campos:
        return Comparacao(item, Situacao.DIVERGENTE, None, None, f"campos={','.join(campos)}")
    return Comparacao(
        item, Situacao.IGUAL, f"{len(congeladas)} campos", f"{len(congeladas)} campos"
    )


_PIOR_PRIMEIRO = (Situacao.DIVERGENTE, Situacao.INCONCLUSIVO, Situacao.BYTES_DIFERENTES)
_FALHAS = (
    (Situacao.DIVERGENTE, "reproducao_divergente"),
    (Situacao.INCONCLUSIVO, "reproducao_inconclusiva"),
)


def resultado_geral(comparacoes: Iterable[Comparacao]) -> Situacao:
    """A pior situação dos itens: divergente, inconclusivo, bytes diferentes ou igual."""
    presentes = {comparacao.situacao for comparacao in comparacoes}
    return next((s for s in _PIOR_PRIMEIRO if s in presentes), Situacao.IGUAL)


def exigir_conferido(comparacoes: Sequence[Comparacao]) -> None:
    """Falha se algum item diverge ou ficou sem original para comparar.

    Raises:
        FalhaOperacionalErro: `reproducao_divergente` (conteúdo diferente) ou
            `reproducao_inconclusiva` (sem original), com a contagem e os primeiros itens.
    """
    for situacao, chave in _FALHAS:
        itens = [comparacao.item for comparacao in comparacoes if comparacao.situacao is situacao]
        if itens:
            nomes = ",".join(itens[:_MAX_NOMES])
            raise FalhaOperacionalErro(f"{chave} itens={len(itens)} primeiros={nomes}")


def _por_particao(
    nome: str, esperadas: Mapping[Particao, DatasetRef], obtidas: Mapping[Particao, DatasetRef]
) -> list[Comparacao]:
    itens = []
    for particao, ref in esperadas.items():
        item = f"split:{nome}:{particao.value}"
        novo = obtidas.get(particao)
        if novo is None:
            itens.append(
                Comparacao(item, Situacao.DIVERGENTE, ref.hash_logico, None, _SEM_PARTICAO)
            )
        else:
            itens.append(comparar_referencia(item, ref, novo))
    return itens


def comparar_split(esperado: SplitManifest, obtido: SplitManifest) -> list[Comparacao]:
    """Id do split e, por partição, a população e os rótulos refeitos contra os congelados."""
    igual = esperado.split_id == obtido.split_id
    situacao = Situacao.IGUAL if igual else Situacao.DIVERGENTE
    itens = [Comparacao("split:split_id", situacao, esperado.split_id, obtido.split_id)]
    itens += _por_particao("particao", esperado.particoes or {}, obtido.particoes or {})
    itens += _por_particao(
        "rotulos", esperado.rotulos_por_particao or {}, obtido.rotulos_por_particao or {}
    )
    return itens


def comparar_originais(
    congelados: Sequence[DatasetRef], estados: Mapping[str, str]
) -> list[Comparacao]:
    """Um item inconclusivo por conjunto congelado cujo artefato o ingest refeito não normalizou.

    `estados` é o estado de cada artefato no ingest refeito (`NORMALIZADO`, `ARQUIVOAUSENTE`,
    `QUARENTENA_*`...); o artefato ausente da lista conta como `AUSENTE_DO_INGEST`. Original
    ausente, truncado ou com leiaute incompatível é inconclusão, não conteúdo divergente.
    """
    itens = []
    for conjunto in congelados:
        falta = {
            artefato: estados.get(artefato, _AUSENTE_DO_INGEST)
            for artefato in conjunto.artifact_ids
            if estados.get(artefato) != _NORMALIZADO
        }
        if falta:
            nomes = ",".join(sorted(set(falta.values())))
            detalhe = f"originais_indisponiveis artefatos={len(falta)} estados={nomes}"
            declarado = f"{conjunto.linhas}:{conjunto.hash_logico}"
            item = f"conjunto:{conjunto.schema_id}"
            itens.append(Comparacao(item, Situacao.INCONCLUSIVO, declarado, None, detalhe))
    return itens


def comparar_notas(
    item: str, esperadas: Sequence[str] | None, obtidas: Sequence[str]
) -> Comparacao:
    """As notas do relatório refeito contra as da rodada registrada, como multiconjunto.

    As notas trazem o recorte, a especificação do bootstrap e a cobertura dos resultados.
    """
    if esperadas is None:
        return Comparacao(item, Situacao.INCONCLUSIVO, None, str(len(obtidas)), "original_ausente")
    antigas, novas = Counter(esperadas), Counter(obtidas)
    faltando = sorted((antigas - novas).elements())
    sobrando = sorted((novas - antigas).elements())
    esperado, obtido = str(len(esperadas)), str(len(obtidas))
    if not (faltando or sobrando):
        return Comparacao(item, Situacao.IGUAL, esperado, obtido)
    primeira = (faltando or sobrando)[0][:_MAX_TEXTO]
    detalhe = f"faltando={len(faltando)} sobrando={len(sobrando)} primeira={primeira}"
    return Comparacao(item, Situacao.DIVERGENTE, esperado, obtido, detalhe)


def observacoes_do_ambiente(
    *,
    config_igual: bool,
    codigo: CodeVersion,
    congelado: CodeVersion,
    pacotes: Mapping[str, str],
    congelados: Mapping[str, str],
) -> list[str]:
    """O que difere no ambiente sem ser divergência de conteúdo: config, código e pacotes.

    Só os pacotes do congelamento são conferidos; pacote a mais no ambiente atual não conta.
    """
    observacoes = []
    if not config_igual:
        observacoes.append("config_diferente_da_congelada")
    if (codigo.commit, codigo.sujo) != (congelado.commit, congelado.sujo):
        observacoes.append(
            f"codigo_diferente_do_congelado congelado={congelado.commit} atual={codigo.commit}"
        )
    diferentes = sorted(nome for nome, versao in congelados.items() if pacotes.get(nome) != versao)
    if diferentes:
        observacoes.append(f"pacotes_diferentes_do_congelado pacotes={','.join(diferentes)}")
    return observacoes


def rodada_registrada(
    registro: Sequence[Mapping[str, Any]], freeze_id: str, modo: str
) -> Mapping[str, Any] | None:
    """A última rodada registrada do congelamento e do modo, se houver."""
    rodadas = [e for e in registro if e["freeze_id"] == freeze_id and e["modo"] == modo]
    return rodadas[-1] if rodadas else None
