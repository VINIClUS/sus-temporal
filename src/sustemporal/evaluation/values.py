"""Parcela identificada de valor de tabela não aprovado (T13, P3).

Uma única execução do motor (uma seleção de versões) define a população: cada registro avaliado é
uma ocorrência, sem deduplicação (reapresentações não vinculáveis continuam distintas), e cai em
exatamente uma categoria do seu estrato de resultado oficial. `d(r) = valor_apresentado(r) -
valor_aprovado(r)` é somado em `Decimal`. O denominador soma `d(r)` das ocorrências com os dois
valores conhecidos, `d(r) >= 0` e rótulo sem contradição; o numerador, o subconjunto com ao menos
uma VIOLACAO numa família cuja governança municipal está documentada. Inconclusivos, campos
insuficientes, diferenças negativas e rótulos contraditórios saem em categorias próprias, com
contagem e valor. Totais por família se sobrepõem e saem marcados como não aditivos. A razão não é
perda financeira nem parcela de todas as perdas municipais.
"""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts import (
    DatasetRef,
    EstadoExecucao,
    Governanca,
    RuntimeConfig,
    calcular_dataset_id,
)
from sustemporal.duck import conectar
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.sia_pa import gravar_parquet, produtor
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.conteudo import ConteudoDivergente, verificar_conteudo

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts import FamiliaRegra, RuleSpec, RunResult

__all__ = [
    "CATEGORIAS",
    "COLUNAS_VALORES",
    "ESTRATOS_COM_RAZAO",
    "SCHEMA_VALORES",
    "summarize_values",
]

logger = logging.getLogger(__name__)

SCHEMA_VALORES = "valores_p3.v1"
_TIPOS = (
    ("run_id", "VARCHAR"),
    ("estrato", "VARCHAR"),
    ("categoria", "VARCHAR"),
    ("aditiva", "BOOLEAN"),
    ("ocorrencias", "BIGINT"),
    ("valor_apresentado", "DECIMAL(38, 6)"),
    ("valor_aprovado", "DECIMAL(38, 6)"),
    ("diferenca", "DECIMAL(38, 6)"),
    ("razao", "DECIMAL(38, 12)"),
)
COLUNAS_VALORES = tuple(nome for nome, _ in _TIPOS)
ESTRATOS_COM_RAZAO = ("NAO_APROVADO", "APROVADO_PARCIAL")
IDENTIFICADA = "IDENTIFICADA_GOVERNANCA_MUNICIPAL"
SEM_GOVERNANCA = "INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA"
ELEGIVEIS = (IDENTIFICADA, SEM_GOVERNANCA, "INCONCLUSIVO", "SEM_VIOLACAO_VERIFICADA")
CATEGORIAS = (*ELEGIVEIS, "DIFERENCA_NEGATIVA", "CAMPOS_INSUFICIENTES", "ROTULO_CONTRADITORIO")
_ESCALA_VALOR = Decimal("1e-6")
_ESCALA_RAZAO = Decimal("1e-12")
_EXIGIDAS = {
    "sia_pa_rotulos.v1": (
        "row_id",
        "rotulo",
        "contradicoes",
        "valor_apresentado",
        "valor_aprovado",
    ),
    "agregados_registro.v1": ("run_id", "row_id", "violacoes", "resultado"),
    "avaliacoes.v1": ("run_id", "politica_id", "metodo"),
}
_SQL_REGISTROS = (
    "SELECT a.row_id, a.violacoes, a.resultado, r.rotulo, r.contradicoes, "
    "r.valor_apresentado, r.valor_aprovado FROM read_parquet($agregados) a "
    "LEFT JOIN read_parquet($rotulos) r USING (row_id) WHERE a.run_id = $run ORDER BY a.row_id"
)


@dataclass(frozen=True)
class _Registro:
    row_id: str
    violacoes: tuple[str, ...]
    resultado: str
    rotulo: str
    contradicoes: str
    apresentado: Decimal | None
    aprovado: Decimal | None


@dataclass
class _Acumulado:
    ocorrencias: int = 0
    apresentado: Decimal | None = None
    aprovado: Decimal | None = None
    diferenca: Decimal | None = None

    def somar(self, apresentado: Decimal | None, aprovado: Decimal | None) -> None:
        self.ocorrencias += 1
        if apresentado is not None:
            self.apresentado = (self.apresentado or Decimal(0)) + apresentado
        if aprovado is not None:
            self.aprovado = (self.aprovado or Decimal(0)) + aprovado
        if apresentado is not None and aprovado is not None:
            self.diferenca = (self.diferenca or Decimal(0)) + (apresentado - aprovado)

    def juntar(self, outro: _Acumulado) -> None:
        self.ocorrencias += outro.ocorrencias
        for nome in ("apresentado", "aprovado", "diferenca"):
            valor = getattr(outro, nome)
            if valor is not None:
                setattr(self, nome, (getattr(self, nome) or Decimal(0)) + valor)


def _saida(run: RunResult, schema_id: str) -> DatasetRef:
    candidatos = [d for d in run.saidas if d.schema_id == schema_id]
    if len(candidatos) != 1:
        raise FalhaOperacionalErro(
            f"valores_saida_ausente_ou_repetida run={run.run_id} schema={schema_id} "
            f"encontradas={len(candidatos)}"
        )
    return candidatos[0]


def _exigir_execucao(run: RunResult, labels: DatasetRef) -> None:
    if run.estado is not EstadoExecucao.CONCLUIDA:
        raise ValueError(f"execucao_nao_concluida run={run.run_id} estado={run.estado}")
    if labels.schema_id != "sia_pa_rotulos.v1":
        raise ValueError(f"rotulos_schema_invalido schema={labels.schema_id}")
    if labels.origem_dados is not run.origem_dados:
        raise ValueError(
            f"origem_dados_divergente run={run.origem_dados} rotulos={labels.origem_dados}"
        )


def _conferir(con: duckdb.DuckDBPyConnection, *datasets: DatasetRef) -> None:
    for dataset in datasets:
        try:
            verificar_conteudo(con, dataset)
            descricao = con.execute(
                "DESCRIBE SELECT * FROM read_parquet($c)", {"c": dataset.caminho}
            ).fetchall()
        except (ConteudoDivergente, duckdb.Error) as erro:
            raise FalhaOperacionalErro(
                f"valores_entrada_ilegivel_ou_divergente dataset={dataset.dataset_id} erro={erro}"
            ) from erro
        fisicas = {str(linha[0]) for linha in descricao}
        ausentes = [c for c in _EXIGIDAS[dataset.schema_id] if c not in fisicas]
        if ausentes:
            raise FalhaOperacionalErro(
                f"valores_leiaute_incompativel dataset={dataset.dataset_id} "
                f"ausentes={','.join(ausentes)}"
            )


def _exigir_selecao_unica(
    con: duckdb.DuckDBPyConnection, avaliacoes: DatasetRef, run: RunResult
) -> None:
    selecoes = con.execute(
        "SELECT DISTINCT politica_id, metodo FROM read_parquet($c) WHERE run_id = $r",
        {"c": avaliacoes.caminho, "r": run.run_id},
    ).fetchall()
    politicas = {str(politica) for politica, _ in selecoes}
    if len(selecoes) > 1 or (run.politica_id is not None and politicas - {run.politica_id}):
        raise ValueError(
            f"selecao_de_versoes_multipla run={run.run_id} selecoes={len(selecoes)} "
            f"politicas={','.join(sorted(politicas))}"
        )


def _registros(
    con: duckdb.DuckDBPyConnection, agregados: DatasetRef, labels: DatasetRef, run_id: str
) -> list[_Registro]:
    linhas = con.execute(
        _SQL_REGISTROS, {"agregados": agregados.caminho, "rotulos": labels.caminho, "run": run_id}
    ).fetchall()
    sem_rotulo = sum(1 for linha in linhas if linha[3] is None)
    if sem_rotulo:
        raise FalhaOperacionalErro(
            f"valores_rotulos_incompletos run={run_id} faltantes={sem_rotulo}"
        )
    ids = [str(linha[0]) for linha in linhas]
    if len(set(ids)) != len(ids):
        raise FalhaOperacionalErro(f"valores_ocorrencia_repetida run={run_id}")
    return [
        _Registro(
            row_id=str(row_id),
            violacoes=tuple(r for r in str(violacoes).split(";") if r),
            resultado=str(resultado),
            rotulo=str(rotulo),
            contradicoes=str(contradicoes or ""),
            apresentado=apresentado,
            aprovado=aprovado,
        )
        for row_id, violacoes, resultado, rotulo, contradicoes, apresentado, aprovado in linhas
    ]


def _familias(registro: _Registro, familia_da_regra: Mapping[str, FamiliaRegra]) -> set[str]:
    desconhecidas = sorted(set(registro.violacoes) - set(familia_da_regra))
    if desconhecidas:
        raise ValueError(
            f"regra_fora_do_catalogo row_id={registro.row_id} regras={','.join(desconhecidas)}"
        )
    return {familia_da_regra[regra].value for regra in registro.violacoes}


def _categoria(registro: _Registro, familias: set[str], municipais: set[str]) -> str:
    if registro.contradicoes:
        return "ROTULO_CONTRADITORIO"
    if registro.apresentado is None or registro.aprovado is None:
        return "CAMPOS_INSUFICIENTES"
    if registro.apresentado - registro.aprovado < 0:
        return "DIFERENCA_NEGATIVA"
    if familias:
        return IDENTIFICADA if familias & municipais else SEM_GOVERNANCA
    if registro.resultado == "ABSTENCAO":
        return "INCONCLUSIVO"
    return "SEM_VIOLACAO_VERIFICADA"


def _acumular(
    registros: Iterable[_Registro],
    familia_da_regra: Mapping[str, FamiliaRegra],
    municipais: set[str],
) -> dict[tuple[str, str], _Acumulado]:
    acumulados: dict[tuple[str, str], _Acumulado] = {}
    for registro in registros:
        familias = _familias(registro, familia_da_regra)
        categoria = _categoria(registro, familias, municipais)
        chaves = [categoria]
        if categoria in (IDENTIFICADA, SEM_GOVERNANCA):
            chaves += [f"FAMILIA_{familia}" for familia in sorted(familias)]
        for chave in chaves:
            alvo = acumulados.setdefault((registro.rotulo, chave), _Acumulado())
            alvo.somar(registro.apresentado, registro.aprovado)
    return acumulados


def _razao(numerador: _Acumulado, denominador: _Acumulado) -> Decimal | None:
    base = denominador.diferenca or Decimal(0)
    if base <= 0:
        return None
    parte = numerador.diferenca or Decimal(0)
    return (parte / base).quantize(_ESCALA_RAZAO, rounding=ROUND_HALF_EVEN)


def _linha(
    run_id: str, estrato: str, categoria: str, acumulado: _Acumulado, *, aditiva: bool = True
) -> tuple[object, ...]:
    return (
        run_id,
        estrato,
        categoria,
        aditiva,
        acumulado.ocorrencias,
        acumulado.apresentado,
        acumulado.aprovado,
        acumulado.diferenca,
        None,
    )


def _linhas_do_estrato(
    run_id: str, estrato: str, acumulados: Mapping[tuple[str, str], _Acumulado]
) -> list[tuple[object, ...]]:
    linhas = [
        _linha(run_id, estrato, c, acumulados.get((estrato, c), _Acumulado())) for c in CATEGORIAS
    ]
    denominador = _Acumulado()
    for categoria in ELEGIVEIS:
        denominador.juntar(acumulados.get((estrato, categoria), _Acumulado()))
    numerador = acumulados.get((estrato, IDENTIFICADA), _Acumulado())
    linhas.append(_linha(run_id, estrato, "DENOMINADOR", denominador))
    linhas.append(_linha(run_id, estrato, "NUMERADOR", numerador))
    familias = sorted(c for e, c in acumulados if e == estrato and c.startswith("FAMILIA_"))
    linhas += [
        _linha(run_id, estrato, f, acumulados[(estrato, f)], aditiva=False) for f in familias
    ]
    if estrato in ESTRATOS_COM_RAZAO:
        razao = _razao(numerador, denominador)
        linhas.append((run_id, estrato, "RAZAO", False, None, None, None, None, razao))
    return linhas


def _escala(valor: object) -> object:
    if isinstance(valor, Decimal) and valor != valor.quantize(_ESCALA_VALOR):
        raise ValueError(f"valor_com_mais_de_6_decimais valor={valor}")
    return valor


def _gravar(
    con: duckdb.DuckDBPyConnection,
    linhas: list[tuple[object, ...]],
    out: Path,
    referencias: tuple[DatasetRef, ...],
) -> DatasetRef:
    definicao = ", ".join(f"{nome} {tipo}" for nome, tipo in _TIPOS)
    con.execute(f"CREATE OR REPLACE TEMP TABLE valores_p3 ({definicao})")
    marcadores = ", ".join("?" for _ in _TIPOS)
    if linhas:
        con.executemany(
            f"INSERT INTO valores_p3 VALUES ({marcadores})",  # noqa: S608
            [[*linha[:5], *map(_escala, linha[5:8]), linha[8]] for linha in linhas],
        )
    hash_logico = hash_logico_relacao(con, "valores_p3", COLUNAS_VALORES)
    artefatos = tuple(sorted({a for ref in referencias for a in ref.artifact_ids}))
    dataset_id = calcular_dataset_id(SCHEMA_VALORES, hash_logico, artefatos)
    out.mkdir(parents=True, exist_ok=True)
    destino = out / f"{dataset_id}.parquet"
    gravar_parquet(con, "valores_p3", destino)
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=SCHEMA_VALORES,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artefatos,
        origem_dados=referencias[0].origem_dados,
        produzido_por=produtor("evaluation.values.summarize_values"),
    )


def summarize_values(
    run: RunResult,
    labels: DatasetRef,
    out: Path,
    *,
    regras: Sequence[RuleSpec] | None = None,
    governanca_por_familia: Mapping[FamiliaRegra, Governanca] | None = None,
) -> DatasetRef:
    """Soma d(r) uma vez por ocorrência, com categorias de exclusão explícitas.

    Sem `governanca_por_familia`, nenhuma família tem governança municipal documentada e o
    numerador é zero; as incompatibilidades ficam em categoria própria.

    Raises:
        FalhaOperacionalErro: saída ausente ou repetida, Parquet ilegível ou divergente, leiaute
            incompatível, rótulos que não cobrem a execução ou ocorrência repetida.
        ValueError: execução não concluída, mais de uma seleção de versões, regra fora do
            catálogo, origem de dados divergente ou valor com mais de 6 casas decimais.
    """
    _exigir_execucao(run, labels)
    agregados = _saida(run, "agregados_registro.v1")
    avaliacoes = _saida(run, "avaliacoes.v1")
    familia_da_regra = {r.rule_id: r.familia for r in (regras or carregar_regras())}
    municipais = {
        f.value
        for f, g in (governanca_por_familia or {}).items()
        if g is Governanca.MUNICIPAL_DOCUMENTADA
    }
    with closing(conectar(RuntimeConfig(duckdb_threads=1))) as con:
        _conferir(con, labels, agregados, avaliacoes)
        _exigir_selecao_unica(con, avaliacoes, run)
        registros = _registros(con, agregados, labels, run.run_id)
        acumulados = _acumular(registros, familia_da_regra, municipais)
        estratos = sorted({e for e, _ in acumulados} | set(ESTRATOS_COM_RAZAO))
        linhas = [x for e in estratos for x in _linhas_do_estrato(run.run_id, e, acumulados)]
        ref = _gravar(con, linhas, out, (labels, agregados))
    logger.info(
        "valores_p3 run=%s ocorrencias=%d linhas=%d dataset=%s",
        run.run_id,
        len(registros),
        ref.linhas,
        ref.dataset_id,
    )
    return ref
