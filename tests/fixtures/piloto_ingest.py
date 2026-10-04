"""Apoio aos testes de `sustemporal ingest`: config, catálogo de fontes e leitura das saídas."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import duckdb

from sustemporal.contracts import DatasetRef

__all__ = [
    "cobertura_ingest",
    "config_ingest",
    "fontes_ingest",
    "motivos_ingest",
    "resultados_ingest",
]

RAIZ = Path(__file__).resolve().parents[2]
DRS_XI = RAIZ / "catalog" / "territorio" / "drs_xi.yaml"
FONTES = RAIZ / "catalog" / "sources.yaml"
_MULTIPARTES = '    multipartes: "true"\n'


def fontes_ingest(pasta: Path, partes: list[str] | None) -> Path:
    """Cópia do catálogo de fontes com `partes_esperadas` do SIA-PA em 201801 (ou sem)."""
    texto = FONTES.read_text(encoding="utf-8")
    if _MULTIPARTES not in texto:
        raise ValueError("catalogo_sem_marcador_multipartes")
    if partes is not None:
        declaracao = f'    partes_esperadas:\n      "201801": [{", ".join(partes)}]\n'
        texto = texto.replace(_MULTIPARTES, _MULTIPARTES + declaracao, 1)
    destino = pasta / "sources.yaml"
    destino.write_text(texto, encoding="utf-8")
    return destino


def config_ingest(
    pasta: Path,
    fontes: Path,
    *,
    familias: str = "SIA_PA, CNES_PF, SIGTAP",
    corte: str | None = None,
    competencias: str = '"201801"',
) -> Path:
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        f"catalogos:\n  fontes: {fontes}",
        *([f"corte_observacao: {corte}"] if corte else []),
        "runtime:",
        f"  raiz_dados: {pasta / 'dados'}",
        f"  raiz_manifestos: {pasta / 'manifestos'}",
        f"  raiz_saidas: {pasta / 'saidas'}",
        "  duckdb_memoria: 256MB",
        '  duckdb_threads: "1"',
        "piloto:",
        "  uf: SP",
        f"  competencias_processamento: [{competencias}]",
        f"  territorio: {DRS_XI}",
        f"  familias_fontes: [{familias}]",
    ]
    caminho = pasta / "ingest.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def _execucao(pasta: Path) -> Path:
    (execucao,) = sorted(p for p in (pasta / "saidas" / "ingest").iterdir() if p.is_dir())
    return execucao


def resultados_ingest(pasta: Path) -> list[dict[str, str]]:
    texto = (_execucao(pasta) / "resultados.jsonl").read_text(encoding="utf-8")
    return [json.loads(linha) for linha in texto.splitlines()]


def cobertura_ingest(
    pasta: Path, instrumento: str = "C", competencia: str = "201801"
) -> dict[tuple[str, str], str]:
    """Estado por (família, base) na competência pedida para o instrumento pedido."""
    linhas = (_execucao(pasta) / "datasets.jsonl").read_text(encoding="utf-8").splitlines()
    datasets = [DatasetRef.model_validate(json.loads(linha)) for linha in linhas]
    (cobertura,) = [d for d in datasets if d.schema_id == "cobertura.v1"]
    with closing(duckdb.connect()) as con:
        consulta = con.execute(
            "SELECT familia_regra, base_temporal, estado FROM read_parquet($c) "
            "WHERE competencia = $k AND instrumento = $i",
            {"c": cobertura.caminho, "i": instrumento, "k": competencia},
        ).fetchall()
    return {(str(f), str(b)): str(e) for f, b, e in consulta}


def motivos_ingest(pasta: Path, competencia: str) -> set[str]:
    """Motivos (não nulos) da cobertura na competência pedida."""
    linhas = (_execucao(pasta) / "datasets.jsonl").read_text(encoding="utf-8").splitlines()
    datasets = [DatasetRef.model_validate(json.loads(linha)) for linha in linhas]
    (cobertura,) = [d for d in datasets if d.schema_id == "cobertura.v1"]
    with closing(duckdb.connect()) as con:
        consulta = con.execute(
            "SELECT DISTINCT motivo FROM read_parquet($c) "
            "WHERE competencia = $k AND motivo IS NOT NULL",
            {"c": cobertura.caminho, "k": competencia},
        ).fetchall()
    return {str(m) for (m,) in consulta}
