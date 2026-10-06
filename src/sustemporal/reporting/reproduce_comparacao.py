"""Comparação do refeito com o congelado: split, métricas, notas, insumos e o ambiente (T14).

Os arquivos (conjuntos, saídas e execuções) são comparados em `reproduce_arquivos`, por hash
lógico, e este módulo os reexporta junto de `Comparacao` e `Situacao`. Divergência de conteúdo é
`DIVERGENTE`; o que não tem original para comparar é `INCONCLUSIVO`, nunca violação.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.base import json_canonico
from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.freeze_entrada import campos_divergentes
from sustemporal.reporting.reproduce_arquivos import (
    Identidade,
    comparar_execucoes,
    comparar_referencia,
    comparar_saida,
    comparar_saidas,
    identidade_do_arquivo,
)
from sustemporal.reporting.reproduce_itens import Comparacao, Situacao

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts.evaluation import ValorMetrica
    from sustemporal.contracts.experiment import CodeVersion, Particao, SplitManifest
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = [
    "Comparacao",
    "Identidade",
    "Situacao",
    "comparar_auxiliares",
    "comparar_conjuntos",
    "comparar_entradas_originais",
    "comparar_execucoes",
    "comparar_insumos",
    "comparar_metricas",
    "comparar_notas",
    "comparar_originais",
    "comparar_referencia",
    "comparar_saida",
    "comparar_saidas",
    "comparar_split",
    "exigir_conferido",
    "identidade_do_arquivo",
    "ler_relatorio_original",
    "observacoes_do_ambiente",
    "observacoes_do_ingest",
    "resultado_geral",
    "rodada_registrada",
]

logger = logging.getLogger(__name__)

_MAX_NOMES = 5
_MAX_TEXTO = 80
_NORMALIZADO = "NORMALIZADO"
_AUSENTE_DO_INGEST = "AUSENTE_DO_INGEST"
_SEM_PARTICAO = "particao_ausente"
_SEM_FALHA = frozenset(
    {_NORMALIZADO, "FAMILIA_RESERVADA", "FAMILIARESERVADA", "FORA_DO_RECORTE", "FORA_DO_CORTE"}
)


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


def comparar_conjuntos(
    congelados: Sequence[DatasetRef], refeitos: Mapping[str, DatasetRef]
) -> list[Comparacao]:
    """Os conjuntos do manifesto contra os refeitos, pareados pelo `schema_id`.

    O conjunto congelado que nenhuma etapa refaz (`sem_etapa`) fica inconclusivo.
    """
    itens = []
    for esperada in congelados:
        obtida = refeitos.get(esperada.schema_id)
        item = f"conjunto:{esperada.schema_id}"
        if obtida is None:
            itens.append(Comparacao(item, Situacao.INCONCLUSIVO, None, None, "sem_etapa"))
        else:
            itens.append(comparar_referencia(item, esperada, obtida))
    return itens


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


def _nao_normalizados(artefatos: Iterable[str], estados: Mapping[str, str]) -> dict[str, str]:
    return {
        artefato: estados.get(artefato, _AUSENTE_DO_INGEST)
        for artefato in artefatos
        if estados.get(artefato) != _NORMALIZADO
    }


def _inconclusivo(item: str, esperado: str | None, falta: Mapping[str, str]) -> Comparacao:
    nomes = ",".join(sorted(set(falta.values())))
    detalhe = f"originais_indisponiveis artefatos={len(falta)} estados={nomes}"
    return Comparacao(item, Situacao.INCONCLUSIVO, esperado, None, detalhe)


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
        falta = _nao_normalizados(conjunto.artifact_ids, estados)
        if falta:
            declarado = f"{conjunto.linhas}:{conjunto.hash_logico}"
            itens.append(_inconclusivo(f"conjunto:{conjunto.schema_id}", declarado, falta))
    return itens


def comparar_auxiliares(
    entradas: Mapping[str, EntradaValidacao], estados: Mapping[str, str]
) -> list[Comparacao]:
    """Um item inconclusivo por política cujos auxiliares usam artefato não normalizado.

    São os auxiliares (CNES, SIGTAP) da entrada congelada de cada política; a população e os
    rótulos já são conferidos por `comparar_originais`, e a cobertura e a seleção só derivam desses
    artefatos. Mesmo item (`insumos:<politica>`) que a comparação refeita dá a essa entrada.
    """
    itens = []
    for politica_id in sorted(entradas):
        auxiliares = entradas[politica_id].auxiliares
        falta = _nao_normalizados({a for ref in auxiliares for a in ref.artifact_ids}, estados)
        if falta:
            itens.append(_inconclusivo(f"insumos:{politica_id}", None, falta))
    return itens


def comparar_entradas_originais(problemas: Mapping[str, str]) -> list[Comparacao]:
    """Um item inconclusivo por política cuja entrada original não pôde ser conferida.

    `problemas` traz o motivo (`entrada_original_ausente`, `_ilegivel` ou `_alterada`). Sem a
    entrada não se sabe de que artefatos os auxiliares dependiam, e a diferença nos insumos
    refeitos não prova divergência. Mesmo item (`insumos:<politica>`) que a comparação refeita.
    """
    return [
        Comparacao(f"insumos:{politica_id}", Situacao.INCONCLUSIVO, None, None, motivo)
        for politica_id, motivo in sorted(problemas.items())
    ]


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


def ler_relatorio_original(caminho: Path) -> EvaluationReport | None:
    """O relatório da rodada registrada; ausente, ilegível ou fora do contrato é `None`."""
    if not caminho.is_file():
        return None
    try:
        return EvaluationReport.model_validate_json(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        erro_tipo = type(erro).__name__
        logger.warning("relatorio_original_ilegivel caminho=%s erro=%s", caminho, erro_tipo)
        return None


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


def observacoes_do_ingest(estados: Mapping[str, str]) -> list[str]:
    """O ingest refeito deixou artefatos sem tabela (arquivo ausente, quarentena ou falha).

    Não conta como falha o artefato normalizado nem o que o ingest deixa de fora por desenho
    (família reservada, fora do recorte ou do corte de observação).
    """
    falhas = {artefato for artefato, estado in estados.items() if estado not in _SEM_FALHA}
    if not falhas:
        return []
    nomes = ",".join(sorted({estados[artefato] for artefato in falhas}))
    return [f"ingest_sem_tabela artefatos={len(falhas)} estados={nomes}"]


def rodada_registrada(
    registro: Sequence[Mapping[str, Any]], freeze_id: str, modo: str
) -> Mapping[str, Any] | None:
    """A última rodada registrada do congelamento e do modo, se houver."""
    rodadas = [e for e in registro if e["freeze_id"] == freeze_id and e["modo"] == modo]
    return rodadas[-1] if rodadas else None
