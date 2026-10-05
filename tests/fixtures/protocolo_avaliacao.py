"""Execuções, decisões e código SINTETICO para os testes de métricas e congelamento (T11).

Decisões G0/G2 são escritas só em diretórios temporários dos testes; nada aqui representa
decisão humana real nem resultado empírico.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.base import OrigemDados, hash_canonico
from sustemporal.contracts.experiment import (
    Ambiente,
    CodeVersion,
    EstadoExecucao,
    ModoExecucao,
    RunResult,
    TipoExecucao,
)
from tests.fixtures.protocolo_dados import gravar_tabela

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.temporal import MetodoId

CODIGO_LIMPO = CodeVersion(commit="a" * 40, sujo=False, versao_pacote="0.0.0")
AMBIENTE = Ambiente(python="3.12", plataforma="teste")
INSTANTE = datetime(2026, 1, 1, tzinfo=UTC)


def relogio() -> datetime:
    return INSTANTE


def run_agregados(
    metodo: MetodoId,
    resultados: dict[str, str],
    out: Path,
    *,
    modo: ModoExecucao = ModoExecucao.EXPLORATORIO,
    origem: OrigemDados = OrigemDados.SINTETICO,
    **campos: Any,
) -> RunResult:
    """Execução sintética do motor com `agregados_registro.v1` (resultado por row_id).

    `campos` sobrescreve os campos do `RunResult`; `origem` REAL é só rótulo de teste.
    """
    run_id = f"run_{metodo.value.lower()}_{hash_canonico(resultados)[:16]}"
    linhas = [
        {
            "run_id": run_id,
            "row_id": row_id,
            "violacoes": "R1" if resultado == "ALERTA" else "",
            "conformes": "R1" if resultado == "SEM_VIOLACAO_VERIFICADA" else "",
            "inconclusivas": "R1" if resultado == "ABSTENCAO" else "",
            "nao_aplicaveis": "",
            "resultado": resultado,
        }
        for row_id, resultado in sorted(resultados.items())
    ]
    artefatos = tuple(sorted({row_id.split("#")[0] for row_id in resultados}))
    saida = gravar_tabela(
        linhas,
        "agregados_registro.v1",
        out / run_id / "agregados.parquet",
        artifact_ids=artefatos,
        origem=origem,
    )
    base: dict[str, Any] = {
        "run_id": run_id,
        "tipo": TipoExecucao.VALIDACAO,
        "metodo": metodo,
        "modo": modo,
        "config_hash": "0" * 64,
        "codigo": CODIGO_LIMPO,
        "ambiente": AMBIENTE,
        "saidas": (saida,),
        "estado": EstadoExecucao.CONCLUIDA,
        "iniciado_em": INSTANTE,
        "concluido_em": INSTANTE,
        "origem_dados": origem,
    }
    return RunResult(**{**base, **campos})


def escrever_decisao(
    diretorio: Path, portao: str, decisao: str, *, freeze_id: str | None = None
) -> Path:
    """Decisão de portão de TESTE, só em diretório temporário."""
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / f"{portao.lower()}_teste.yaml"
    linhas = [
        f"portao: {portao}",
        f"decisao: {decisao}",
        "data: 2025-06-01",
        "responsaveis: [teste_sintetico]",
        "registrado_por_humano: true",
    ]
    if freeze_id is not None:
        linhas.append(f"freeze_id: {freeze_id}")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho
