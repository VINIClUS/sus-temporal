"""Ablações de versão de regra e de fonte (T08): sensibilidade, não causalidade.

Uma ablação compara duas execuções do mesmo motor que diferem num só fator: a versão das regras
(entradas idênticas) ou a versão de conteúdo de uma fonte (CNES ou SIGTAP) na seleção, com
política, configuração, registros, demais fontes e catálogo fixos. Mede a sensibilidade do
modelo; não identifica causalmente a origem da decisão oficial.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.experiment import EstadoExecucao, TipoExecucao
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.rules import EstadoAvaliacao
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.conteudo import verificar_conteudo

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import duckdb

    from sustemporal.contracts.experiment import RunResult

__all__ = [
    "INTERPRETACAO_ABLACAO",
    "AblacaoNaoIsolada",
    "MudancaAblacao",
    "RelatorioAblacao",
    "TipoAblacao",
    "comparar_ablacao",
    "trocar_versao_fonte",
]

logger = logging.getLogger(__name__)

INTERPRETACAO_ABLACAO = (
    "A ablação mede a sensibilidade do modelo à troca isolada de um fator (versão da regra ou "
    "versão de conteúdo de uma fonte), com o resto fixo; não identifica causalmente a origem da "
    "decisão oficial de processamento."
)
_SELECOES = "selecao_versoes.v1"
_TABELA = "ablacao_selecoes"
_MOTIVO_COMPETENCIA = "VIGENCIA_NAO_RESOLVIDA"
_MOTIVO_TROCA = "ablacao_troca_de_versao observacao_original_descartada"
_CAMPOS_ALVO = ("base", "competencia_requerida", "estado")
_CAMPOS_SELECAO = (*_CAMPOS_ALVO, "artifact_ids", "observation_ids", "motivo")


class TipoAblacao(StrEnum):
    VERSAO_REGRA = "VERSAO_REGRA"
    VERSAO_CNES = "VERSAO_CNES"
    VERSAO_SIGTAP = "VERSAO_SIGTAP"


_FONTES_DO_TIPO = {
    TipoAblacao.VERSAO_CNES: frozenset(f for f in FamiliaFonte if f.value.startswith("CNES_")),
    TipoAblacao.VERSAO_SIGTAP: frozenset({FamiliaFonte.SIGTAP}),
}


class AblacaoNaoIsolada(ValueError):
    """As duas execuções diferem em mais do que o fator da ablação."""


@dataclass(frozen=True)
class MudancaAblacao:
    row_id: str
    rule_id: str
    estado_base: EstadoAvaliacao
    estado_variante: EstadoAvaliacao


@dataclass(frozen=True)
class RelatorioAblacao:
    tipo: TipoAblacao
    run_base: str
    run_variante: str
    comparadas: int
    mudancas: tuple[MudancaAblacao, ...]
    regras_alteradas: tuple[str, ...] = ()
    por_regra: dict[str, int] = field(default_factory=dict)
    interpretacao: str = INTERPRETACAO_ABLACAO


def _hash(con: duckdb.DuckDBPyConnection, schema_id: str) -> str:
    fisicas = {str(linha[0]) for linha in con.execute(f"DESCRIBE {_TABELA}").fetchall()}
    colunas = [c.nome for c in carregar_esquema(schema_id).colunas if c.nome in fisicas]
    return hash_logico_relacao(con, _TABELA, colunas)


def _trocadas(
    con: duckdb.DuckDBPyConnection, fonte: FamiliaFonte, troca: Mapping[str, str]
) -> list[tuple[str, str, str, str, str]]:
    linhas = con.execute(
        f"SELECT row_id, rule_id, artifact_ids FROM {_TABELA} WHERE fonte = $f",  # noqa: S608
        {"f": str(fonte)},
    ).fetchall()
    alteradas = []
    for row_id, rule_id, artefatos in linhas:
        atuais = [a for a in str(artefatos or "").split(";") if a]
        novos = ";".join(sorted({troca.get(a, a) for a in atuais}))
        if novos != ";".join(atuais):
            alteradas.append((novos, _MOTIVO_TROCA, str(row_id), str(rule_id), str(fonte)))
    return alteradas


def _reescrever(
    selecoes: DatasetRef,
    fonte: FamiliaFonte,
    troca: Mapping[str, str],
    caminho: Path,
    runtime: RuntimeConfig | None,
) -> tuple[list[tuple[str, str, str, str, str]], str]:
    con = conectar(runtime or RuntimeConfig())
    try:
        verificar_conteudo(con, selecoes)
        con.execute(
            f"CREATE TEMP TABLE {_TABELA} AS SELECT * FROM read_parquet($c)",  # noqa: S608
            {"c": selecoes.caminho},
        )
        alteradas = _trocadas(con, fonte, troca)
        if not alteradas:
            raise ValueError(f"troca_sem_efeito fonte={fonte} troca={sorted(troca)}")
        con.executemany(
            f"UPDATE {_TABELA} SET artifact_ids = ?, observation_ids = '', "  # noqa: S608
            "motivo = motivo || ' ' || ? WHERE row_id = ? AND rule_id = ? AND fonte = ?",
            alteradas,
        )
        con.sql(f"SELECT * FROM {_TABELA}").write_parquet(str(caminho))  # noqa: S608
        return alteradas, _hash(con, _SELECOES)
    finally:
        con.close()


def trocar_versao_fonte(
    selecoes: DatasetRef,
    fonte: FamiliaFonte,
    troca: Mapping[str, str],
    destino: Path,
    *,
    runtime: RuntimeConfig | None = None,
) -> DatasetRef:
    """Nova `selecao_versoes.v1` em que só as versões de `fonte` são trocadas por `troca`.

    Base, competência requerida, estado e as outras fontes ficam iguais; as linhas trocadas perdem
    as observações da versão antiga e o motivo registra a troca. Versão substituta de outra
    competência não é aceita silenciosamente: o motor a recusa como competência divergente
    (`VIGENCIA_NAO_RESOLVIDA`), nunca a usa como mês vizinho.

    Raises:
        ValueError: esquema diferente de `selecao_versoes.v1` ou troca sem efeito.
    """
    if selecoes.schema_id != _SELECOES:
        raise ValueError(f"ablacao_exige_selecoes schema_id={selecoes.schema_id}")
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"selecoes_{fonte.value.lower()}.parquet"
    alteradas, hash_logico = _reescrever(selecoes, fonte, troca, caminho, runtime)
    novos = {parte for linha in alteradas for parte in linha[0].split(";") if parte}
    artefatos = tuple(sorted({*selecoes.artifact_ids, *novos}))
    logger.info("selecao_trocada fonte=%s linhas_alteradas=%d", fonte, len(alteradas))
    return DatasetRef(
        dataset_id=calcular_dataset_id(_SELECOES, hash_logico, artefatos),
        schema_id=_SELECOES,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=selecoes.linhas,
        artifact_ids=artefatos,
        origem_dados=selecoes.origem_dados,
        produzido_por=f"ablacao_{fonte.value.lower()}",
    )


def _exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise AblacaoNaoIsolada(mensagem)


def _entradas(run: RunResult, *, sem_selecoes: bool) -> set[str]:
    return {d.dataset_id for d in run.entradas if not (sem_selecoes and d.schema_id == _SELECOES)}


def _exigir_fixos(base: RunResult, variante: RunResult, tipo: TipoAblacao) -> None:
    for run in (base, variante):
        _exigir(run.tipo is TipoExecucao.VALIDACAO, f"ablacao_exige_validacao run={run.run_id}")
        completa = run.estado is EstadoExecucao.CONCLUIDA and run.falhas == 0
        _exigir(completa, f"ablacao_execucao_incompleta run={run.run_id} estado={run.estado}")
    mesma_politica = (base.metodo, base.politica_id) == (variante.metodo, variante.politica_id)
    _exigir(mesma_politica, f"ablacao_politica_diferente tipo={tipo}")
    _exigir(base.config_hash == variante.config_hash, f"ablacao_config_diferente tipo={tipo}")
    _exigir(base.origem_dados is variante.origem_dados, f"ablacao_origem_diferente tipo={tipo}")
    mesmo_codigo = (base.codigo, base.ambiente) == (variante.codigo, variante.ambiente)
    _exigir(mesmo_codigo, f"ablacao_codigo_diferente tipo={tipo}")
    _exigir(
        base.snapshot_set_id == variante.snapshot_set_id, f"ablacao_snapshot_diferente tipo={tipo}"
    )
    if tipo is TipoAblacao.VERSAO_REGRA:
        iguais = _entradas(base, sem_selecoes=False) == _entradas(variante, sem_selecoes=False)
        _exigir(iguais, f"ablacao_entradas_diferentes tipo={tipo}")
        return
    mesmo_catalogo = base.catalogo_regras_sha256 == variante.catalogo_regras_sha256
    _exigir(mesmo_catalogo, f"ablacao_catalogo_diferente tipo={tipo}")
    iguais = _entradas(base, sem_selecoes=True) == _entradas(variante, sem_selecoes=True)
    _exigir(iguais, f"ablacao_entradas_diferentes tipo={tipo}")


def _saida(run: RunResult, schema_id: str) -> DatasetRef:
    candidatas = [d for d in run.saidas if d.schema_id == schema_id]
    _exigir(len(candidatas) == 1, f"ablacao_saida_ausente run={run.run_id} schema={schema_id}")
    _exigir(
        candidatas[0].produzido_por == run.run_id,
        f"ablacao_saida_de_outra_execucao run={run.run_id} schema={schema_id}",
    )
    return candidatas[0]


def _ler(
    con: duckdb.DuckDBPyConnection, run: RunResult, schema_id: str, chave: tuple[str, ...]
) -> dict[tuple[str, ...], dict[str, Any]]:
    ref = _saida(run, schema_id)
    verificar_conteudo(con, ref)
    cursor = con.execute("SELECT * FROM read_parquet($c)", {"c": ref.caminho})
    nomes = [coluna[0] for coluna in cursor.description or ()]
    linhas = [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]
    return {tuple(str(linha[c]) for c in chave): linha for linha in linhas}


def _exigir_selecoes_isoladas(
    base: Mapping[tuple[str, ...], dict[str, Any]],
    variante: Mapping[tuple[str, ...], dict[str, Any]],
    tipo: TipoAblacao,
) -> set[tuple[str, str]]:
    """Só as versões das fontes do tipo mudam; devolve os pares (linha, regra) trocados.

    Raises:
        AblacaoNaoIsolada: outra fonte, base, competência ou estado mudou, ou nenhuma troca real.
    """
    _exigir(base.keys() == variante.keys(), f"ablacao_selecoes_diferentes tipo={tipo}")
    alvo = {str(f) for f in _FONTES_DO_TIPO[tipo]}
    trocados: set[tuple[str, str]] = set()
    for chave, linha in base.items():
        outra = variante[chave]
        if linha["fonte"] in alvo:
            mesmas = all(linha[c] == outra[c] for c in _CAMPOS_ALVO)
            _exigir(mesmas, f"ablacao_competencia_alterada fonte={linha['fonte']}")
            if linha["artifact_ids"] != outra["artifact_ids"]:
                trocados.add((str(linha["row_id"]), str(linha["rule_id"])))
            continue
        iguais = all(linha[c] == outra[c] for c in _CAMPOS_SELECAO)
        _exigir(iguais, f"ablacao_fonte_nao_isolada tipo={tipo} fonte={linha['fonte']}")
    _exigir(bool(trocados), f"ablacao_sem_troca tipo={tipo}")
    return trocados


def _exigir_avaliacoes_isoladas(
    base: Mapping[tuple[str, ...], dict[str, Any]],
    variante: Mapping[tuple[str, ...], dict[str, Any]],
    trocados: set[tuple[str, str]],
    tipo: TipoAblacao,
) -> None:
    """Avaliação fora dos pares (linha, regra) cuja versão trocou fica idêntica (estado, motivos e
    evidências); substituta de outra competência é recusada, nunca tomada como sensibilidade."""
    for chave, linha in base.items():
        outra = variante.get(chave, {})
        if (chave[0], chave[1]) not in trocados:
            iguais = all(linha[c] == outra.get(c) for c in linha if c != "run_id")
            _exigir(
                iguais, f"ablacao_fonte_nao_isolada tipo={tipo} row={chave[0]} regra={chave[1]}"
            )
            continue
        novos = set(_lista(outra.get("motivos"))) - set(_lista(linha["motivos"]))
        _exigir(
            _MOTIVO_COMPETENCIA not in novos,
            f"ablacao_substituta_de_outra_competencia tipo={tipo} regra={chave[1]}",
        )


def _lista(texto: object) -> list[str]:
    return [parte for parte in str(texto or "").split(";") if parte]


def _mudancas(
    base: Mapping[tuple[str, ...], dict[str, Any]],
    variante: Mapping[tuple[str, ...], dict[str, Any]],
) -> tuple[MudancaAblacao, ...]:
    _exigir(base.keys() == variante.keys(), "ablacao_avaliacoes_diferentes")
    return tuple(
        MudancaAblacao(
            row_id=chave[0],
            rule_id=chave[1],
            estado_base=EstadoAvaliacao(base[chave]["estado"]),
            estado_variante=EstadoAvaliacao(variante[chave]["estado"]),
        )
        for chave in sorted(base)
        if base[chave]["estado"] != variante[chave]["estado"]
    )


def _regras_alteradas(
    base: Mapping[tuple[str, ...], dict[str, Any]],
    variante: Mapping[tuple[str, ...], dict[str, Any]],
) -> tuple[str, ...]:
    return tuple(sorted({c[1] for c in base if base[c]["versao"] != variante[c]["versao"]}))


Linhas = dict[tuple[str, ...], dict[str, Any]]


def _ler_par(
    base: RunResult, variante: RunResult, tipo: TipoAblacao, runtime: RuntimeConfig | None
) -> tuple[set[tuple[str, str]], Linhas, Linhas]:
    con = conectar(runtime or RuntimeConfig())
    try:
        trocados: set[tuple[str, str]] = set()
        if tipo is not TipoAblacao.VERSAO_REGRA:
            chave_selecao = ("row_id", "rule_id", "fonte")
            trocados = _exigir_selecoes_isoladas(
                _ler(con, base, _SELECOES, chave_selecao),
                _ler(con, variante, _SELECOES, chave_selecao),
                tipo,
            )
        return (
            trocados,
            _ler(con, base, "avaliacoes.v1", ("row_id", "rule_id")),
            _ler(con, variante, "avaliacoes.v1", ("row_id", "rule_id")),
        )
    finally:
        con.close()


def comparar_ablacao(
    base: RunResult,
    variante: RunResult,
    tipo: TipoAblacao,
    *,
    runtime: RuntimeConfig | None = None,
) -> RelatorioAblacao:
    """Compara as avaliações das duas execuções após exigir que só o fator de `tipo` mude.

    Raises:
        AblacaoNaoIsolada: execução incompleta; política, configuração, código, snapshot,
            entradas, catálogo ou outras fontes diferem; nenhuma troca real; substituta de
            outra competência.
    """
    _exigir_fixos(base, variante, tipo)
    trocados, avaliacoes_base, avaliacoes_variante = _ler_par(base, variante, tipo, runtime)
    _exigir(avaliacoes_base.keys() == avaliacoes_variante.keys(), "ablacao_avaliacoes_diferentes")
    mudancas = _mudancas(avaliacoes_base, avaliacoes_variante)
    alteradas: tuple[str, ...] = ()
    if tipo is TipoAblacao.VERSAO_REGRA:
        alteradas = _regras_alteradas(avaliacoes_base, avaliacoes_variante)
        _exigir(bool(alteradas), f"ablacao_sem_troca tipo={tipo}")
        fora = sorted({m.rule_id for m in mudancas} - set(alteradas))
        _exigir(not fora, f"ablacao_regra_nao_isolada regras={fora}")
    else:
        _exigir_avaliacoes_isoladas(avaliacoes_base, avaliacoes_variante, trocados, tipo)
    por_regra: dict[str, int] = {}
    for mudanca in mudancas:
        por_regra[mudanca.rule_id] = por_regra.get(mudanca.rule_id, 0) + 1
    logger.info("ablacao_comparada tipo=%s mudancas=%d", tipo, len(mudancas))
    return RelatorioAblacao(
        tipo=tipo,
        run_base=base.run_id,
        run_variante=variante.run_id,
        comparadas=len(avaliacoes_base),
        mudancas=mudancas,
        regras_alteradas=alteradas,
        por_regra=por_regra,
    )
