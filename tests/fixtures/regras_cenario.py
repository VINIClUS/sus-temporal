"""Cenários SINTETICOS de avaliação: parquet, insumos do motor e entrada da referência."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    SnapshotSet,
    TipoPolitica,
)
from sustemporal.hashing import hash_logico_linhas
from sustemporal.rules.catalog import carregar_esquema
from sustemporal.rules.insumos import InsumosAvaliacao
from sustemporal.rules.reference import CenarioReferencia, ConjuntoAuxiliar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import EstadoIntegridade

__all__ = [
    "COLUNAS_AUXILIARES",
    "COLUNAS_REGISTRO",
    "ESQUEMA_DA_FONTE",
    "CenarioRegras",
    "artefato",
    "coerente",
    "materializar",
    "para_referencia",
    "politica",
    "reemitir",
    "reemitir_insumo",
    "snapshot_vazio",
]

COLUNAS_REGISTRO = (
    "row_id",
    "artifact_id",
    "instrumento",
    "procedimento",
    "cbo",
    "cnes",
    "competencia_atendimento",
    "competencia_processamento",
)
COLUNAS_AUXILIARES: dict[str, tuple[str, ...]] = {
    "sigtap_proc_ocupacao.v1": ("artifact_id", "dt_competencia", "co_procedimento", "co_ocupacao"),
    "cnes_estab_cbo.v1": ("artifact_id", "competencia_arquivo", "cnes", "cbo", "n_vinculos"),
    "sigtap_proc_registro.v1": ("artifact_id", "dt_competencia", "co_procedimento", "co_registro"),
    "sigtap_procedimento.v1": ("artifact_id", "dt_competencia", "co_procedimento"),
}
ESQUEMA_DA_FONTE = {
    "PROC_CBO_SIGTAP": ("SIGTAP", "sigtap_proc_ocupacao.v1"),
    "ESTAB_CBO_CNES": ("CNES_PF", "cnes_estab_cbo.v1"),
    "INSTRUMENTO_REGISTRO_SIGTAP": ("SIGTAP", "sigtap_proc_registro.v1"),
    "VIGENCIA_PROCEDIMENTO_SIGTAP": ("SIGTAP", "sigtap_procedimento.v1"),
}
_SELECAO = (
    "run_id",
    "row_id",
    "rule_id",
    "fonte",
    "base",
    "competencia_requerida",
    "estado",
    "artifact_ids",
    "observation_ids",
    "motivo",
)
_COBERTURA = ("familia_regra", "instrumento", "competencia", "base_temporal", "estado", "motivo")
_INTEIRAS = {"n_vinculos"}


def artefato(numero: int) -> str:
    return f"art_{numero:064x}"


def politica(metodo: MetodoId = MetodoId.B_ATEND) -> PoliticaTemporal:
    if metodo is MetodoId.M_TEMP:
        return PoliticaTemporal(
            politica_id="m_temp_nao_resolvida",
            tipo=TipoPolitica.NAO_RESOLVIDA,
            metodo=metodo,
            criterios=(),
        )
    base = BaseTemporal.ATENDIMENTO if metodo is MetodoId.B_ATEND else BaseTemporal.PROCESSAMENTO
    return PoliticaTemporal(
        politica_id=f"{metodo.value.lower()}_sintetica",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo=metodo,
        criterios=tuple(
            CriterioTemporal(fonte=fonte, base=base)
            for fonte in (FamiliaFonte.CNES_PF, FamiliaFonte.SIGTAP)
        ),
    )


def snapshot_vazio() -> SnapshotSet:
    return SnapshotSet.criar(artifact_ids=(), observation_ids=(), dataset_hashes=(), selecoes=())


@dataclass(frozen=True)
class CenarioRegras:
    """Insumos SINTETICOS em memória; `None` em `cobertura` significa matriz não fornecida."""

    registros: tuple[dict[str, str | None], ...]
    auxiliares: dict[str, tuple[dict[str, object], ...]]
    selecoes: tuple[dict[str, str | None], ...]
    cobertura: tuple[dict[str, str | None], ...] | None
    integridade: dict[str, EstadoIntegridade]
    politica: PoliticaTemporal = field(default_factory=politica)
    colunas_ausentes_registro: frozenset[str] = frozenset()
    colunas_ausentes_auxiliar: dict[str, frozenset[str]] = field(default_factory=dict)
    artefatos_auxiliar: dict[str, tuple[str, ...]] = field(default_factory=dict)
    auxiliares_omitidos: frozenset[str] = frozenset()

    def com(self, **campos: object) -> CenarioRegras:
        return replace(self, **campos)


_COMPETENCIA = re.compile(r"[0-9]{4}(0[1-9]|1[0-2])")
_COLUNA_DA_BASE = {
    "ATENDIMENTO": "competencia_atendimento",
    "PROCESSAMENTO": "competencia_processamento",
}


def _selecao_coerente(
    selecao: dict[str, str | None], registro: dict[str, str | None] | None, cenario: CenarioRegras
) -> dict[str, str | None]:
    criterios = {str(c.fonte): c for c in cenario.politica.criterios}
    criterio = criterios.get(str(selecao["fonte"]))
    coluna = _COLUNA_DA_BASE[str(criterio.base)] if criterio else None
    valor = registro.get(coluna) if registro and coluna else None
    if coluna in cenario.colunas_ausentes_registro:
        valor = None
    if criterio is None or valor is None or not _COMPETENCIA.fullmatch(valor):
        nao_resolvida = {"estado": "NAO_RESOLVIDA", "base": None, "competencia_requerida": None}
        return selecao | nao_resolvida | {"artifact_ids": ""}
    return selecao | {"base": str(criterio.base), "competencia_requerida": valor}


def coerente(cenario: CenarioRegras) -> CenarioRegras:
    """Ajusta base e competência das seleções à política e aos registros (model.md §5)."""
    registros = {str(r["row_id"]): r for r in cenario.registros}
    selecoes = tuple(
        _selecao_coerente(dict(s), registros.get(str(s["row_id"])), cenario)
        for s in cenario.selecoes
    )
    return cenario.com(selecoes=selecoes)


def _tipo(coluna: str) -> pa.DataType:
    return pa.int64() if coluna in _INTEIRAS else pa.string()


def _gravar(caminho: Path, colunas: tuple[str, ...], linhas: list[dict[str, object]]) -> None:
    esquema = pa.schema([(coluna, _tipo(coluna)) for coluna in colunas])
    tabela = pa.Table.from_pylist([{c: linha.get(c) for c in colunas} for linha in linhas], esquema)
    pq.write_table(tabela, caminho)


def _conteudo(caminho: str, schema_id: str) -> tuple[str, int]:
    """Hash lógico das colunas do esquema presentes no arquivo, na ordem do esquema."""
    tabela = pq.read_table(caminho)
    colunas = [c.nome for c in carregar_esquema(schema_id).colunas if c.nome in tabela.column_names]
    valores = [tabela.column(c).to_pylist() for c in colunas]
    linhas = [tuple(coluna[i] for coluna in valores) for i in range(tabela.num_rows)]
    return hash_logico_linhas(colunas, linhas), tabela.num_rows


def reemitir(ref: DatasetRef) -> DatasetRef:
    """DatasetRef coerente com o conteúdo atual do arquivo (para testes que o alteram)."""
    hash_logico, linhas = _conteudo(ref.caminho, ref.schema_id)
    return ref.model_copy(
        update={
            "hash_logico": hash_logico,
            "linhas": linhas,
            "dataset_id": calcular_dataset_id(ref.schema_id, hash_logico, ref.artifact_ids),
        }
    )


def reemitir_insumo(
    dataset: DatasetRef, insumos: InsumosAvaliacao, schema_id: str
) -> tuple[DatasetRef, InsumosAvaliacao]:
    """Reemite o DatasetRef do esquema dado, onde quer que esteja nos insumos."""
    if dataset.schema_id == schema_id:
        return reemitir(dataset), insumos
    auxiliares = tuple(reemitir(d) if d.schema_id == schema_id else d for d in insumos.auxiliares)
    selecoes, cobertura = insumos.selecoes, insumos.cobertura
    if selecoes is not None and selecoes.schema_id == schema_id:
        selecoes = reemitir(selecoes)
    if cobertura is not None and cobertura.schema_id == schema_id:
        cobertura = reemitir(cobertura)
    return dataset, replace(insumos, auxiliares=auxiliares, selecoes=selecoes, cobertura=cobertura)


def _dataset(
    caminho: Path,
    schema_id: str,
    colunas: tuple[str, ...],
    linhas: list[dict[str, object]],
    artefatos: tuple[str, ...],
) -> DatasetRef:
    _gravar(caminho, colunas, linhas)
    hash_logico, quantidade = _conteudo(str(caminho), schema_id)
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artefatos),
        schema_id=schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=quantidade,
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture_regras_sintetica",
    )


def _artefatos_auxiliar(cenario: CenarioRegras, schema_id: str) -> tuple[str, ...]:
    if schema_id in cenario.artefatos_auxiliar:
        return tuple(sorted(cenario.artefatos_auxiliar[schema_id]))
    return tuple(sorted({str(linha["artifact_id"]) for linha in cenario.auxiliares[schema_id]}))


def _colunas_registro(cenario: CenarioRegras) -> tuple[str, ...]:
    return tuple(c for c in COLUNAS_REGISTRO if c not in cenario.colunas_ausentes_registro)


def _colunas_auxiliar(cenario: CenarioRegras, schema_id: str) -> tuple[str, ...]:
    ausentes = cenario.colunas_ausentes_auxiliar.get(schema_id, frozenset())
    return tuple(c for c in COLUNAS_AUXILIARES[schema_id] if c not in ausentes)


def materializar(cenario: CenarioRegras, raiz: Path) -> tuple[DatasetRef, InsumosAvaliacao]:
    """Grava os parquet SINTETICOS e devolve o conjunto SIA-PA e os insumos do motor."""
    raiz.mkdir(parents=True, exist_ok=True)
    registros = [dict(linha) for linha in cenario.registros]
    artefatos_sia = tuple(sorted({str(linha["artifact_id"]) for linha in registros}))
    dataset = _dataset(
        raiz / "sia_pa.parquet", "sia_pa.v1", _colunas_registro(cenario), registros, artefatos_sia
    )
    auxiliares = tuple(
        _dataset(
            raiz / f"{schema_id}.parquet",
            schema_id,
            _colunas_auxiliar(cenario, schema_id),
            [dict(linha) for linha in linhas],
            _artefatos_auxiliar(cenario, schema_id),
        )
        for schema_id, linhas in sorted(cenario.auxiliares.items())
        if schema_id not in cenario.auxiliares_omitidos
    )
    selecoes_linhas = [{"run_id": "sintetico"} | dict(linha) for linha in cenario.selecoes]
    selecoes = _dataset(
        raiz / "selecoes.parquet", "selecao_versoes.v1", _SELECAO, selecoes_linhas, ()
    )
    cobertura = None
    if cenario.cobertura is not None:
        linhas_cobertura = [dict(linha) for linha in cenario.cobertura]
        cobertura = _dataset(
            raiz / "cobertura.parquet", "cobertura.v1", _COBERTURA, linhas_cobertura, ()
        )
    insumos = InsumosAvaliacao(
        auxiliares=auxiliares,
        selecoes=selecoes,
        cobertura=cobertura,
        integridade=dict(cenario.integridade),
        politica=cenario.politica,
    )
    return dataset, insumos


def para_referencia(cenario: CenarioRegras) -> CenarioReferencia:
    """Mesmos insumos em estruturas Python puras para o avaliador de referência."""
    colunas = frozenset(_colunas_registro(cenario))
    registros = tuple(
        {c: v for c, v in linha.items() if c in colunas} for linha in cenario.registros
    )
    auxiliares = tuple(
        ConjuntoAuxiliar(
            schema_id=schema_id,
            colunas=frozenset(_colunas_auxiliar(cenario, schema_id)),
            artifact_ids=frozenset(_artefatos_auxiliar(cenario, schema_id)),
            linhas=tuple(
                {c: v for c, v in linha.items() if c in _colunas_auxiliar(cenario, schema_id)}
                for linha in linhas
            ),
        )
        for schema_id, linhas in sorted(cenario.auxiliares.items())
        if schema_id not in cenario.auxiliares_omitidos
    )
    selecoes = tuple(
        dict(linha)
        | {"artifact_ids": tuple(a for a in str(linha.get("artifact_ids") or "").split(";") if a)}
        for linha in cenario.selecoes
    )
    return CenarioReferencia(
        colunas_registros=colunas,
        registros=registros,
        auxiliares=auxiliares,
        selecoes=selecoes,
        cobertura=cenario.cobertura,
        integridade={a: str(e) for a, e in cenario.integridade.items()},
        politica_tipo=cenario.politica.tipo,
    )
