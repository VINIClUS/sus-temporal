"""Cenário SINTETICO de execução do motor e rótulos para a análise P3 (T13b).

Valores inventados; nenhum registro real. Cada linha descreve um registro com rótulo, valores,
contradições, regras violadas e resultado agregado do motor.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    Ambiente,
    CodeVersion,
    DatasetRef,
    EstadoExecucao,
    MetodoId,
    ModoExecucao,
    OrigemDados,
    RunResult,
    TipoExecucao,
)
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256
from tests.fixtures.anotacao_cenario import ARTEFATO_TESTE, gravar_dataset

if TYPE_CHECKING:
    from decimal import Decimal
    from pathlib import Path

RUN_ID = "run_valores_sintetico"
POLITICA = "documentada_pendente"


@dataclass(frozen=True)
class Linha:
    row_id: str
    rotulo: str
    apresentado: Decimal | None
    aprovado: Decimal | None
    violacoes: tuple[str, ...] = ()
    resultado: str | None = None
    contradicoes: str = ""
    inconclusivas: tuple[str, ...] = field(default_factory=tuple)
    estado_avaliacao: str | None = None

    def estado(self) -> str:
        if self.estado_avaliacao is not None:
            return self.estado_avaliacao
        if self.violacoes:
            return "VIOLACAO"
        return "INCONCLUSIVO" if self.resultado == "ABSTENCAO" else "CONFORME"

    def resultado_motor(self) -> str:
        if self.resultado is not None:
            return self.resultado
        return "ALERTA" if self.violacoes else "SEM_VIOLACAO_VERIFICADA"


def _rotulos(linhas: list[Linha]) -> list[dict[str, object]]:
    return [
        {
            "row_id": linha.row_id,
            "pa_indica_bruto": "0",
            "rotulo": linha.rotulo,
            "codebook_id": "sia_pa_indica.v1",
            "quantidade_apresentada": 1,
            "quantidade_aprovada": 0,
            "valor_apresentado": linha.apresentado,
            "valor_aprovado": linha.aprovado,
            "contradicoes": linha.contradicoes,
        }
        for linha in linhas
    ]


def _agregados(linhas: list[Linha]) -> list[dict[str, object]]:
    return [
        {
            "run_id": RUN_ID,
            "row_id": linha.row_id,
            "violacoes": ";".join(sorted(linha.violacoes)),
            "conformes": "" if linha.violacoes or linha.resultado else "ESTAB_CBO_CNES",
            "inconclusivas": "ESTAB_CBO_CNES" if linha.resultado == "ABSTENCAO" else "",
            "nao_aplicaveis": "",
            "resultado": linha.resultado_motor(),
        }
        for linha in linhas
    ]


def _avaliacao(linha: Linha, regra: str, politica: str, versao: str) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "row_id": linha.row_id,
        "rule_id": regra,
        "versao": versao,
        "politica_id": politica,
        "metodo": MetodoId.M_TEMP.value,
        "estado": linha.estado(),
        "motivos": "",
        "evidence_ids": "",
    }


def _avaliacoes(
    linhas: list[Linha], politicas: tuple[str, ...], versao: str
) -> list[dict[str, object]]:
    return [
        _avaliacao(linha, regra, politicas[i % len(politicas)], versao)
        for i, linha in enumerate(linhas)
        for regra in linha.violacoes or ("ESTAB_CBO_CNES",)
    ]


@dataclass(frozen=True)
class CenarioValores:
    run: RunResult
    labels: DatasetRef


def montar_valores(
    raiz: Path,
    linhas: list[Linha],
    *,
    politicas: tuple[str, ...] = (POLITICA,),
    estado: EstadoExecucao = EstadoExecucao.CONCLUIDA,
    versao_regras: str = "0.1.0",
) -> CenarioValores:
    raiz.mkdir(parents=True, exist_ok=True)
    artefatos = (ARTEFATO_TESTE,)
    linhas = [replace(linha, row_id=f"{ARTEFATO_TESTE}#{i}") for i, linha in enumerate(linhas)]
    labels = gravar_dataset(
        raiz / "rotulos.parquet", "sia_pa_rotulos.v1", _rotulos(linhas), artefatos
    )
    agregados = gravar_dataset(
        raiz / "agregados.parquet", "agregados_registro.v1", _agregados(linhas), artefatos
    )
    avaliacoes = gravar_dataset(
        raiz / "avaliacoes.parquet",
        "avaliacoes.v1",
        _avaliacoes(linhas, politicas, versao_regras),
        artefatos,
    )
    run = RunResult(
        run_id=RUN_ID,
        tipo=TipoExecucao.VALIDACAO,
        metodo=MetodoId.M_TEMP,
        politica_id=POLITICA,
        modo=ModoExecucao.EXPLORATORIO,
        config_hash="a" * 64,
        catalogo_regras_sha256=catalogo_sha256(carregar_regras()),
        codigo=CodeVersion(commit="abc", sujo=False, versao_pacote="0.1"),
        ambiente=Ambiente(python="3.12", plataforma="linux"),
        saidas=(avaliacoes, agregados),
        estado=estado,
        falhas=0,
        iniciado_em=datetime(2026, 1, 1, tzinfo=UTC),
        origem_dados=OrigemDados.SINTETICO,
    )
    return CenarioValores(run=run, labels=labels)
