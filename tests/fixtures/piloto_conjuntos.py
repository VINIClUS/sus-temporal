"""Conjuntos canônicos sintéticos (SINTETICO) produzidos pelos normalizadores reais.

Monta arquivos fictícios de SIA-PA, SIGTAP e CNES, normaliza com `normalize_pa`, `normalize_sigtap`
e `normalize_cnes` e devolve os `DatasetRef`. Nenhum valor provém de arquivo real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.contracts import FamiliaFonte, OrigemDados, RuntimeConfig
from sustemporal.ingest.cnes import carregar_leiautes_cnes, normalize_cnes
from sustemporal.ingest.coverage import build_coverage
from sustemporal.ingest.sia_pa import normalize_pa
from sustemporal.ingest.sigtap import TABELAS, normalize_sigtap
from sustemporal.ingest.sigtap_zip import carregar_leiautes_sigtap
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.sia_pa_fixtures import (
    artefato_pa,
    campos_pa,
    dbc_pa,
    leiaute_pa,
    registro_pa,
)
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from sustemporal.contracts import DatasetRef, LayoutSpec

__all__ = [
    "cobertura_sintetica",
    "conjunto_cnes_pf",
    "conjunto_sia_pa",
    "conjuntos_sigtap",
    "registro",
    "runtime",
]


def runtime(pasta: Path) -> RuntimeConfig:
    return RuntimeConfig(raiz_dados=str(pasta), duckdb_memoria="256MB", duckdb_threads=1)


def registro(
    instrumento: str, processamento: str, atendimento: str, **outros: str
) -> dict[str, str]:
    """Registro PA com PA_DOCORIG, PA_MVM e PA_CMP pedidos (demais campos do padrão sintético)."""
    return registro_pa(PA_DOCORIG=instrumento, PA_MVM=processamento, PA_CMP=atendimento, **outros)


def _leiaute_com_opcionais(omitidos: Collection[str]) -> LayoutSpec:
    """Leiaute do catálogo com os campos físicos `omitidos` opcionais (arquivo sem a coluna)."""
    leiaute = leiaute_pa()
    campos = tuple(
        c.model_copy(update={"obrigatorio": False}) if c.nome_fisico in omitidos else c
        for c in leiaute.campos
    )
    return leiaute.model_copy(update={"campos": campos})


def conjunto_sia_pa(
    pasta: Path,
    registros: Sequence[dict[str, str]],
    *,
    competencia: str = "201801",
    parte: str = "a",
    deletados: Collection[int] = (),
    sem_campos: Collection[str] = (),
) -> DatasetRef:
    """`sia_pa.v1` normalizado; `sem_campos` (nomes físicos) sai do arquivo e vira nulo."""
    campos = [c for c in campos_pa() if c.nome not in sem_campos] if sem_campos else None
    dados = dbc_pa(registros, deletados=deletados, campos=campos)
    artefato = artefato_pa(pasta, dados, competencia=competencia, parte=parte)
    (pasta / "saida").mkdir(parents=True, exist_ok=True)
    return normalize_pa(
        artefato,
        _leiaute_com_opcionais(sem_campos) if sem_campos else leiaute_pa(),
        pasta / "saida",
        runtime=runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
    )


def cobertura_sintetica(
    pasta: Path, sia_pa: Sequence[DatasetRef], competencias: Sequence[str] = ("201801", "201802")
) -> DatasetRef:
    """`cobertura.v1` da ingestão pelo `build_coverage` real, sem auxiliares."""
    return build_coverage(
        sia_pa,
        [],
        competencias,
        pasta / "cobertura_ingest",
        runtime=runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
    )


def conjuntos_sigtap(
    pasta: Path, competencia: str = "201801", *, tabelas: Collection[str] = tuple(TABELAS)
) -> list[DatasetRef]:
    artefato = artefato_sigtap(
        pasta, zip_sigtap(pacote_padrao(competencia)), competencia=competencia
    )
    leiautes = carregar_leiautes_sigtap()
    return [
        normalize_sigtap(
            artefato,
            leiautes[tabela],
            pasta / "saida",
            runtime=runtime(pasta),
            origem_dados=OrigemDados.SINTETICO,
        )
        for tabela in tabelas
    ]


def conjunto_cnes_pf(
    pasta: Path, competencia: str = "201801", *, extras: Sequence[dict[str, str]] = ()
) -> DatasetRef:
    registros = [
        registro_pf("0012345", "225125", competencia),
        registro_pf("0012345", "2231F9", competencia),
        *extras,
    ]
    fonte = FamiliaFonte.CNES_PF
    artefato = artefato_cnes(pasta, dbc_cnes(fonte, registros), fonte, competencia=competencia)
    return normalize_cnes(
        artefato,
        carregar_leiautes_cnes()[fonte],
        pasta / "saida",
        runtime=runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
    )
