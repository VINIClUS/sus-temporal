"""Execuções reais do `validate` pela CLI para o e2e do `counterfactual` (T09), SINTETICO.

O `validate` roda por `sustemporal.cli.main`, sem mock do motor, em dois modos:
- `--entrada`: os cenários SINTETICOS do contrafactual (com CNES ST), uma linha `VIOLACAO` e
  duas só `INCONCLUSIVO` (mês faltante e borda de 2018);
- `--ingest`: a pasta SINTETICA do `ingest` do #27 (sem CNES ST, que as regras não exigem).

Nenhuma função daqui escreve na pasta da execução: o contexto é o que o `validate` gravou.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from sustemporal import cli
from sustemporal.contracts.experiment import RunResult
from sustemporal.explanation import counterfactual_sobreposicao
from tests.fixtures.contrafactual_execucao import entrada_sintetica
from tests.fixtures.regras_ingest import montar_ingest

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = [
    "ChamadaMotor",
    "ExecucaoReal",
    "espiar_motor",
    "instantaneo",
    "validar_entrada_pela_cli",
    "validar_ingest_pela_cli",
]

_SOBREPOSICAO = "contrafactual_sobreposicao"
_SEM_VIOLACAO = frozenset({"INCONCLUSIVO", "NAO_APLICAVEL"})


@dataclass(frozen=True)
class ExecucaoReal:
    """Execução gravada pelo `validate` real: config da CLI, saídas e estado de cada avaliação."""

    config: Path
    saidas: Path
    run_id: str
    politica_id: str
    estados: dict[str, dict[str, str]]

    @property
    def contrafactuais(self) -> Path:
        return self.saidas / "contrafactuais"

    def regras_em(self, row: str, estado: str) -> set[str]:
        return {regra for regra, atual in self.estados[row].items() if atual == estado}

    def linha_com_violacao(self) -> str:
        """A primeira linha (ordem de `row_id`) com alguma regra em `VIOLACAO`."""
        return next(row for row in sorted(self.estados) if self.regras_em(row, "VIOLACAO"))

    def linhas_so_inconclusivas(self) -> list[str]:
        """Linhas sem violação e com alguma regra `INCONCLUSIVO` (nada a corrigir)."""
        return [
            row
            for row in sorted(self.estados)
            if set(self.estados[row].values()) <= _SEM_VIOLACAO
            and self.regras_em(row, "INCONCLUSIVO")
        ]


@dataclass(frozen=True)
class ChamadaMotor:
    """Uma avaliação do motor pedida pela busca: com cadastro sobreposto ou não, e os estados."""

    sobreposta: bool
    estados: dict[tuple[str, str], str]


def _execucao(config: Path, saidas: Path) -> ExecucaoReal:
    (caminho,) = sorted(saidas.glob("*/val_*/run_result.json"))
    run = RunResult.model_validate_json(caminho.read_text(encoding="utf-8"))
    ref = next(s for s in run.saidas if s.schema_id == "avaliacoes.v1")
    estados: dict[str, dict[str, str]] = {}
    for linha in pq.read_table(ref.caminho).to_pylist():
        estados.setdefault(linha["row_id"], {})[linha["rule_id"]] = linha["estado"]
    return ExecucaoReal(config, saidas, run.run_id, str(run.politica_id), estados)


def _validar(config: Path, politica: str, origem: list[str]) -> int:
    return cli.main(["validate", "--config", str(config), "--policy", politica, *origem])


def validar_entrada_pela_cli(
    raiz: Path, *, politica: PoliticaTemporal | None = None
) -> ExecucaoReal:
    """`sustemporal validate --entrada` sobre os cenários SINTETICOS; `politica` vai na entrada."""
    entrada = raiz / "entrada.json"
    dados = entrada_sintetica(raiz).model_copy(update={"politica": politica})
    entrada.write_text(dados.model_dump_json(), encoding="utf-8")
    config = raiz / "config.yaml"
    runtime = {"raiz_saidas": str(raiz / "saidas")}
    config.write_text(json.dumps({"versao": "1", "runtime": runtime}), encoding="utf-8")
    assert _validar(config, "atendimento", ["--entrada", str(entrada)]) == 0
    return _execucao(config, raiz / "saidas")


def validar_ingest_pela_cli(raiz: Path, politica: str) -> ExecucaoReal:
    """`sustemporal validate --ingest` sobre a pasta SINTETICA do `ingest`, sem SIGTAP em 202302."""
    mundo = montar_ingest(raiz, sigtap_fev_ausente=True)
    assert _validar(mundo.config, politica, ["--ingest", str(mundo.pasta)]) == 0
    return _execucao(mundo.config, raiz / "outputs")


def instantaneo(raiz: Path, *, sem: Path) -> dict[str, str]:
    """SHA-256 de todo arquivo sob `raiz`, exceto o que está sob `sem` (o destino do resultado)."""
    return {
        str(arquivo.relative_to(raiz)): hashlib.sha256(arquivo.read_bytes()).hexdigest()
        for arquivo in sorted(raiz.rglob("*"))
        if arquivo.is_file() and not arquivo.is_relative_to(sem)
    }


def espiar_motor(monkeypatch: pytest.MonkeyPatch) -> list[ChamadaMotor]:
    """Registra cada chamada que a sobreposição faz ao motor; o motor roda de verdade."""
    real = counterfactual_sobreposicao.evaluate_rules
    chamadas: list[ChamadaMotor] = []

    def espia(*args: Any, **kwargs: Any) -> RunResult:
        resultado = real(*args, **kwargs)
        sobreposta = any(d.produzido_por == _SOBREPOSICAO for d in kwargs["insumos"].auxiliares)
        ref = next(s for s in resultado.saidas if s.schema_id == "avaliacoes.v1")
        estados = {
            (linha["row_id"], linha["rule_id"]): linha["estado"]
            for linha in pq.read_table(ref.caminho).to_pylist()
        }
        chamadas.append(ChamadaMotor(sobreposta, estados))
        return resultado

    monkeypatch.setattr(counterfactual_sobreposicao, "evaluate_rules", espia)
    return chamadas
