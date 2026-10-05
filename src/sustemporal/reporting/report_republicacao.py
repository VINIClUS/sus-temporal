"""Versões de conteúdo concorrentes do SIA-PA ingerido: a competência sai da população (T05).

O `ingest` normaliza um `sia_pa.v1` por versão de conteúdo do arquivo. Quando a mesma (UF,
competência do arquivo, parte) tem mais de uma versão, somar as tabelas contaria cada republicação
como registros distintos e inflaria contagens, ausências, rótulos e denominadores. O relatório não
escolhe versão: tira da população todas as linhas dos arquivos daquela competência (classe de
exclusão `versoes_concorrentes`, também as de outras partes e as deletadas), marca a competência
como incompleta na disponibilidade (`sia_pa_incompleto`) e cita as versões em notas. A chave de
cada artefato (UF, competência e parte) vem do manifesto lido pela ingestão; sem ela nada é
detectado. Versão é conteúdo: o mesmo conteúdo observado duas vezes continua sendo uma versão só.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import duckdb

    from sustemporal.contracts import ChaveArtefato, DatasetRef

__all__ = [
    "CLASSE_EXCLUSAO",
    "VersoesConcorrentes",
    "artefatos_excluidos",
    "marcas_de_concorrencia",
    "notas_de_concorrencia",
    "versoes_concorrentes",
]

CLASSE_EXCLUSAO = "versoes_concorrentes"
_SQL_COMPETENCIAS_EXCLUIDAS = (
    "SELECT DISTINCT competencia_processamento FROM pa "
    "WHERE list_contains($artefatos, artifact_id) AND NOT deletado "
    "AND competencia_processamento IS NOT NULL"
)


@dataclass(frozen=True)
class VersoesConcorrentes:
    """Competência do arquivo cuja tabela SIA-PA tem versões divergentes numa mesma parte.

    `partes` traz, por parte com mais de uma versão, os ids das versões; `artefatos`, todas as
    versões da competência com tabela `sia_pa.v1` (todas saem da população).
    """

    uf: str | None
    competencia: str
    partes: tuple[tuple[str | None, tuple[str, ...]], ...]
    artefatos: frozenset[str]


def _concorrente(
    uf: str | None, competencia: str, por_parte: Mapping[str | None, set[str]]
) -> VersoesConcorrentes | None:
    divergentes = tuple(
        (parte, tuple(sorted(versoes)))
        for parte, versoes in sorted(por_parte.items(), key=lambda item: item[0] or "")
        if len(versoes) > 1
    )
    if not divergentes:
        return None
    return VersoesConcorrentes(
        uf, competencia, divergentes, frozenset(a for v in por_parte.values() for a in v)
    )


def versoes_concorrentes(
    datasets: Sequence[DatasetRef], chaves: Mapping[str, ChaveArtefato]
) -> list[VersoesConcorrentes]:
    """Competências do arquivo em que alguma parte tem mais de uma versão com `sia_pa.v1`.

    Artefato sem chave (ou sem competência do arquivo) em `chaves` não entra no agrupamento.
    """
    grupos: dict[tuple[str | None, str], dict[str | None, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for dataset in (d for d in datasets if d.schema_id == "sia_pa.v1"):
        for artefato in dataset.artifact_ids:
            chave = chaves.get(artefato)
            if chave is not None and chave.competencia_arquivo is not None:
                competencia = chave.competencia_arquivo.valor
                grupos[(chave.uf, competencia)][chave.parte].add(artefato)
    encontrados = (
        _concorrente(uf, competencia, partes)
        for (uf, competencia), partes in sorted(
            grupos.items(), key=lambda g: (g[0][0] or "", g[0][1])
        )
    )
    return [c for c in encontrados if c is not None]


def artefatos_excluidos(concorrentes: Sequence[VersoesConcorrentes]) -> list[str]:
    """Versões (ids) cujas linhas saem da população, ordenadas."""
    return sorted({artefato for c in concorrentes for artefato in c.artefatos})


def notas_de_concorrencia(concorrentes: Sequence[VersoesConcorrentes]) -> list[str]:
    """Uma nota por (competência, parte) com as versões divergentes (ids)."""
    return [
        f"{CLASSE_EXCLUSAO} competencia={c.competencia} uf={c.uf or '-'} parte={parte or '-'} "
        f"versoes={','.join(versoes)}: competência inconclusiva, nenhuma versão escolhida; "
        "linhas dos arquivos da competência fora da população"
        for c in concorrentes
        for parte, versoes in c.partes
    ]


def marcas_de_concorrencia(
    con: duckdb.DuckDBPyConnection, concorrentes: Sequence[VersoesConcorrentes]
) -> dict[str, str]:
    """Competência → motivo `sia_pa_incompleto`: a do arquivo e as de processamento das linhas.

    As linhas excluídas (não deletadas) podem trazer competências de processamento diferentes da
    do arquivo; a população delas também fica incompleta. Exige a tabela `pa` carregada.
    """
    marcas: dict[str, str] = {}
    for c in concorrentes:
        partes = ",".join(parte or "-" for parte, _ in c.partes)
        motivo = f"{CLASSE_EXCLUSAO} competencia_arquivo={c.competencia} partes={partes}"
        marcas.setdefault(c.competencia, motivo)
        linhas = con.execute(_SQL_COMPETENCIAS_EXCLUIDAS, {"artefatos": sorted(c.artefatos)})
        for (processamento,) in linhas.fetchall():
            marcas.setdefault(str(processamento), motivo)
    return marcas
