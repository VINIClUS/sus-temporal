"""Matriz de cobertura família × instrumento × competência × base temporal (T04, `cobertura.v1`).

A matriz é completa: uma linha por família candidata de `catalog/familias.yaml`, instrumento da
família, competência de processamento pedida e base temporal, sem nulo na chave. O estado vem das
tabelas efetivamente carregadas (conferidas por hash), não do fato de a fonte ter sido baixada:
- DISPONIVEL: todas as competências auxiliares exigidas pelos registros têm a tabela da família;
- INSUFICIENTE: só parte delas, competência de atendimento nula ou nenhum registro do instrumento;
- AUSENTE: nenhuma delas, ou nenhum SIA-PA na competência.
Competência ausente nunca é suprida pelo mês vizinho.
"""

from __future__ import annotations

import itertools
import logging
import re
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts import (
    BaseTemporal,
    CatalogoFamilias,
    DatasetRef,
    EsquemaCanonico,
    EstadoCobertura,
    FamiliaFonte,
    OrigemDados,
    RuntimeConfig,
)
from sustemporal.contracts.rules import FamiliaRegra
from sustemporal.duck import conectar
from sustemporal.ingest.cnes_leitura import gravar_relacao
from sustemporal.ingest.sia_pa import carregar_conferido
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    import duckdb

    from sustemporal.contracts.rules import FamiliaCandidata

__all__ = [
    "CATALOGO_FAMILIAS",
    "CORRESPONDENCIA_DOCORIG_REGISTRO",
    "build_coverage",
    "marcas_sia_pa_incompleto",
]

logger = logging.getLogger(__name__)

CATALOGO_FAMILIAS = Path(__file__).resolve().parents[3] / "catalog" / "familias.yaml"
ESQUEMAS = Path(__file__).resolve().parents[3] / "catalog" / "schemas"
# PA_DOCORIG → CO_REGISTRO do SIGTAP: INFERIDA dos rótulos (catalog/familias.yaml); A_CONFIRMAR.
CORRESPONDENCIA_DOCORIG_REGISTRO = {
    "C": "01",
    "I": "02",
    "P": "06",
    "S": "07",
    "A": "08",
    "B": "09",
}
_COLUNAS_COMPETENCIA = ("dt_competencia", "competencia_arquivo")
_BASES = (BaseTemporal.ATENDIMENTO, BaseTemporal.PROCESSAMENTO)
_COLUNAS_SIA_PA = (
    "competencia_processamento",
    "instrumento",
    "competencia_atendimento",
    "deletado",
)
# Exclusões que não escondem par algum da referência: agregação, duplicata exata e deletado.
_SEM_PERDA = frozenset({"agregada_em_contagem", "duplicata_exata", "deletado"})
_CONFERENCIA = "conferencia"
_DESCARTAR_CONFERENCIA = "DROP TABLE conferencia"


@dataclass
class _Grupo:
    atendimentos: set[str] = field(default_factory=set)
    atendimento_nulo: bool = False


@dataclass
class _Registros:
    competencias: set[str] = field(default_factory=set)
    grupos: dict[tuple[str, str], _Grupo] = field(default_factory=lambda: defaultdict(_Grupo))


@dataclass(frozen=True)
class _Fonte:
    schema_id: str
    disponiveis: frozenset[str]
    por_registro: dict[str, frozenset[str]]
    com_perda: frozenset[str] = frozenset()


def _conferidos(
    con: duckdb.DuckDBPyConnection, datasets: Iterable[DatasetRef], schema_id: str
) -> list[DatasetRef]:
    """Conjuntos do esquema, cada um conferido (estrutura, contagem e hash) antes do uso."""
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{schema_id.rsplit('.', 1)[0]}.yaml")
    conferidos = [d for d in datasets if d.schema_id == schema_id]
    for dataset in conferidos:
        carregar_conferido(con, dataset, esquema, _CONFERENCIA)
        con.execute(_DESCARTAR_CONFERENCIA)
    return conferidos


def _distintos(dataset: DatasetRef, colunas: Sequence[str]) -> list[dict[str, str | None]]:
    tabela = pq.read_table(dataset.caminho, columns=list(colunas))
    agrupada = tabela.group_by(list(colunas)).aggregate([])
    linhas: list[dict[str, str | None]] = agrupada.to_pylist()
    return linhas


def _registros(datasets: Sequence[DatasetRef]) -> _Registros:
    resultado = _Registros()
    for dataset in datasets:
        for linha in _distintos(dataset, _COLUNAS_SIA_PA):
            processamento, instrumento = linha["competencia_processamento"], linha["instrumento"]
            if processamento is None or linha["deletado"]:
                continue
            resultado.competencias.add(processamento)
            if instrumento is None:
                continue
            grupo = resultado.grupos[(processamento, instrumento)]
            atendimento = linha["competencia_atendimento"]
            if atendimento is None:
                grupo.atendimento_nulo = True
            else:
                grupo.atendimentos.add(atendimento)
    return resultado


def _fonte(datasets: Sequence[DatasetRef], schema_id: str, campos: Sequence[str]) -> _Fonte:
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{schema_id.rsplit('.', 1)[0]}.yaml")
    nomes = [c.nome for c in esquema.colunas]
    competencia = next(c for c in _COLUNAS_COMPETENCIA if c in nomes)
    exigidas = list(dict.fromkeys([competencia, *campos]))
    lidas = [*exigidas, "co_registro"] if "co_registro" in nomes else exigidas
    disponiveis: set[str] = set()
    com_perda: set[str] = set()
    por_registro: dict[str, set[str]] = defaultdict(set)
    for dataset in datasets:
        destino = com_perda if _perdeu_linhas(dataset) else disponiveis
        for linha in _distintos(dataset, list(dict.fromkeys(lidas))):
            if any(linha[c] is None for c in exigidas):
                continue
            valor = str(linha[competencia])
            destino.add(valor)
            if destino is disponiveis and linha.get("co_registro") is not None:
                por_registro[str(linha["co_registro"])].add(valor)
    return _Fonte(
        schema_id,
        frozenset(disponiveis - com_perda),
        {codigo: frozenset(valores - com_perda) for codigo, valores in por_registro.items()},
        frozenset(com_perda),
    )


def _perdeu_linhas(dataset: DatasetRef) -> bool:
    """Linhas do arquivo descartadas por motivo que pode esconder um par da referência."""
    if dataset.reconciliacao is None:
        return False
    motivos = dataset.reconciliacao.excluidas_por_motivo
    return any(total and motivo not in _SEM_PERDA for motivo, total in motivos.items())


def _necessarias(
    registros: _Registros, competencia: str, instrumento: str, base: BaseTemporal
) -> tuple[set[str] | None, str | None]:
    if competencia not in registros.competencias:
        return None, f"sia_pa_ausente competencia={competencia}"
    grupo = registros.grupos.get((competencia, instrumento))
    if grupo is None:
        return None, f"sem_registros instrumento={instrumento} competencia={competencia}"
    if base is BaseTemporal.PROCESSAMENTO:
        return {competencia}, None
    if grupo.atendimento_nulo:
        return None, f"competencia_atendimento_nula instrumento={instrumento}"
    return set(grupo.atendimentos), None


def _disponiveis(
    fonte: _Fonte, familia: FamiliaRegra, instrumento: str
) -> tuple[frozenset[str], str]:
    if familia is not FamiliaRegra.INSTRUMENTO_REGISTRO:
        return fonte.disponiveis, ""
    codigo = CORRESPONDENCIA_DOCORIG_REGISTRO.get(instrumento, "")
    return fonte.por_registro.get(codigo, frozenset()), f" co_registro={codigo}"


def _celula(
    registros: _Registros,
    fonte: _Fonte,
    chave: tuple[FamiliaRegra, str, str, BaseTemporal],
) -> tuple[EstadoCobertura, str | None]:
    familia, instrumento, competencia, base = chave
    necessarias, motivo = _necessarias(registros, competencia, instrumento, base)
    if necessarias is None:
        sem_pa = motivo is not None and motivo.startswith("sia_pa_ausente")
        return (EstadoCobertura.AUSENTE if sem_pa else EstadoCobertura.INSUFICIENTE), motivo
    disponiveis, sufixo = _disponiveis(fonte, familia, instrumento)
    faltam = sorted(necessarias - disponiveis)
    if not faltam:
        return EstadoCobertura.DISPONIVEL, None
    perdas = sorted(necessarias & fonte.com_perda)
    if perdas:
        motivo = f"linhas_descartadas schema={fonte.schema_id} competencias={','.join(perdas)}"
        return EstadoCobertura.INSUFICIENTE, motivo
    motivo = f"fonte_ausente schema={fonte.schema_id}{sufixo} competencias={','.join(faltam)}"
    total = len(faltam) == len(necessarias)
    return (EstadoCobertura.AUSENTE if total else EstadoCobertura.INSUFICIENTE), motivo


def _auxiliar(familia: FamiliaCandidata) -> tuple[str, tuple[str, ...]]:
    requisito = next(r for r in familia.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)
    return requisito.schema_id, tuple(requisito.campos)


def _linhas(
    con: duckdb.DuckDBPyConnection,
    catalogo: CatalogoFamilias,
    entradas: tuple[Sequence[DatasetRef], Sequence[DatasetRef]],
    competencias: Sequence[str],
) -> list[dict[str, str | None]]:
    sia_pa, auxiliares = entradas
    registros = _registros(_conferidos(con, sia_pa, "sia_pa.v1"))
    conferidos: dict[str, list[DatasetRef]] = {}
    linhas: list[dict[str, str | None]] = []
    for familia in catalogo.familias:
        schema_id, campos = _auxiliar(familia)
        if schema_id not in conferidos:
            conferidos[schema_id] = _conferidos(con, auxiliares, schema_id)
        fonte = _fonte(conferidos[schema_id], schema_id, campos)
        celulas = itertools.product(familia.instrumentos, competencias, _BASES)
        for instrumento, competencia, base in celulas:
            chave = (familia.familia, str(instrumento), competencia, base)
            estado, motivo = _celula(registros, fonte, chave)
            linhas.append(
                {
                    "familia_regra": familia.familia.value,
                    "instrumento": str(instrumento),
                    "competencia": competencia,
                    "base_temporal": base.value,
                    "estado": estado.value,
                    "motivo": motivo,
                }
            )
    return linhas


# Contrato com o `validate --ingest` (#27) e o relatório do piloto: mudar o texto exige aviso no PR.
_MARCA_INCOMPLETO = "sia_pa_incompleto competencia={competencia} motivo={motivo}"
_PADRAO_MARCA = re.compile(r"sia_pa_incompleto competencia=([0-9]{6}) motivo=(.*?)(?:; |$)")


def marcas_sia_pa_incompleto(motivos: Iterable[str | None]) -> dict[str, str]:
    """Competência → motivo das marcas `sia_pa_incompleto` lidas dos motivos de uma cobertura."""
    return {
        competencia: texto
        for motivo in motivos
        for competencia, texto in _PADRAO_MARCA.findall(motivo or "")
    }


def _marcar_incompleto(linhas: list[dict[str, str | None]], incompleto: Mapping[str, str]) -> None:
    """Competência com parte do SIA-PA não normalizada nunca fica DISPONIVEL."""
    for linha in linhas:
        competencia = str(linha["competencia"])
        if competencia not in incompleto:
            continue
        aviso = _MARCA_INCOMPLETO.format(competencia=competencia, motivo=incompleto[competencia])
        if linha["estado"] == EstadoCobertura.DISPONIVEL.value:
            linha["estado"] = EstadoCobertura.INSUFICIENTE.value
        linha["motivo"] = aviso if linha["motivo"] is None else f"{aviso}; {linha['motivo']}"


def build_coverage(
    sia_pa: Sequence[DatasetRef],
    auxiliares: Sequence[DatasetRef],
    competencias: Sequence[str],
    out: Path,
    *,
    familias: Path = CATALOGO_FAMILIAS,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.SINTETICO,
    sia_pa_incompleto: Mapping[str, str] | None = None,
) -> DatasetRef:
    """Matriz completa de cobertura a partir das tabelas efetivamente carregadas.

    `origem_dados` padrão é SINTETICO (direção segura). `sia_pa_incompleto` mapeia competência →
    motivo quando alguma parte do SIA-PA daquela competência não foi normalizada (quarentena,
    ausência ou falha): a competência nunca fica DISPONIVEL.

    Raises:
        ValueError: conjunto de entrada com estrutura, contagem ou hash divergente do declarado.
    """
    configuracao = runtime or RuntimeConfig()
    catalogo = CatalogoFamilias.model_validate(carregar_yaml(familias))
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / "cobertura.yaml")
    with closing(conectar(configuracao)) as con:
        linhas = _linhas(con, catalogo, (sia_pa, auxiliares), sorted(set(competencias)))
    _marcar_incompleto(linhas, sia_pa_incompleto or {})
    campos = [pa.field(c.nome, pa.string(), nullable=c.anulavel) for c in esquema.colunas]
    tabela = pa.Table.from_pylist(linhas, schema=pa.schema(campos))
    artefatos = tuple(sorted({a for d in [*sia_pa, *auxiliares] for a in d.artifact_ids}))
    dataset_id, hash_logico, destino = gravar_relacao(tabela, esquema, out, artefatos, configuracao)
    logger.info("cobertura_gerada linhas=%s competencias=%s", len(linhas), len(competencias))
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=esquema.schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artefatos,
        origem_dados=origem_dados,
        produzido_por=f"sustemporal.ingest.coverage.build_coverage@{metadata.version('sus-temporal')}",
    )
