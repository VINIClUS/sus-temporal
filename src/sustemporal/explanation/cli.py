"""Comando `sustemporal explain --run RUN_ID --row ROW_ID`.

O `run_id` resolve o `run_result.json` exato da execução (`<raiz_saidas>/runs/<run_id>` ou
`<raiz_saidas>/validacao/<run_id>`), nunca um diretório "latest". A saída fica em
`<raiz_saidas>/explicacoes/<run_id>/row_<sha256(row_id)[:32]>/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.experiment import RunResult
from sustemporal.contracts.records import RowId
from sustemporal.contracts.rules import FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.explanation.evidence import EvidenciaDivergente, sql_reexecucao
from sustemporal.explanation.explain import ExplicacaoIndisponivel, montar_explicacao

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig
    from sustemporal.explanation.explain import Explicacao

__all__ = ["diretorio_explicacao", "executar_explain", "localizar_execucao"]

logger = logging.getLogger(__name__)

_ROW_ID: TypeAdapter[str] = TypeAdapter(RowId)
_DIRETORIOS_DE_EXECUCAO = ("runs", "validacao")


def _agora() -> datetime:
    return datetime.now(UTC)


class ExecucaoNaoResolvida(ValueError):
    """`run_id` sem `run_result.json` exato, ambíguo ou incoerente."""


def localizar_execucao(raiz: Path, run_id: str) -> RunResult:
    """`RunResult` gravado para `run_id`; nunca escolhe a execução mais recente.

    Raises:
        ExecucaoNaoResolvida: nenhum, mais de um distinto ou com `run_id` diferente.
    """
    lidos: dict[str, RunResult] = {}
    for nome in _DIRETORIOS_DE_EXECUCAO:
        caminho = raiz / nome / run_id / "run_result.json"
        if not caminho.is_file():
            continue
        try:
            resultado = RunResult.model_validate_json(caminho.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as erro:
            raise ExecucaoNaoResolvida(
                f"execucao_ilegivel run={run_id} caminho={caminho}"
            ) from erro
        lidos[resultado.model_dump_json()] = resultado
    if not lidos:
        raise ExecucaoNaoResolvida(f"execucao_inexistente run={run_id} raiz={raiz}")
    if len(lidos) > 1:
        raise ExecucaoNaoResolvida(f"execucao_ambigua run={run_id} n={len(lidos)}")
    resultado = next(iter(lidos.values()))
    if resultado.run_id != run_id:
        raise ExecucaoNaoResolvida(f"execucao_incoerente run={run_id} gravada={resultado.run_id}")
    return resultado


def diretorio_explicacao(raiz: Path, run_id: str, row_id: str) -> Path:
    """Diretório derivado só do `run_id` e do `row_id`."""
    sufixo = hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:32]
    return Path(raiz) / "explicacoes" / run_id / f"row_{sufixo}"


def _reexecucoes(explicacao: Explicacao) -> str:
    entradas = []
    for reexecucao in explicacao.reexecucoes:
        entrada = asdict(reexecucao) | {"reproduzida": reexecucao.reproduzida}
        if reexecucao.sql_sha256 is not None:
            entrada["sql"] = sql_reexecucao(reexecucao.query_id)
        entradas.append(entrada)
    return json.dumps(entradas, ensure_ascii=False, indent=2, sort_keys=True)


def _gravar(destino: Path, explicacao: Explicacao) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    bundle = explicacao.bundle
    (destino / "bundle.json").write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    (destino / "prov.provn").write_text(bundle.prov_n, encoding="utf-8")
    (destino / "prov.json").write_bytes(explicacao.prov_json.encode("utf-8"))
    (destino / "explicacao.txt").write_text(explicacao.texto, encoding="utf-8")
    (destino / "reexecucoes.json").write_text(_reexecucoes(explicacao), encoding="utf-8")


def _registrar_falha(destino: Path, run_id: str, row_id: str, erro: Exception) -> None:
    falha = FalhaOperacional(
        run_id=run_id,
        etapa="reexecutar_evidencia",
        row_id=row_id,
        erro=str(erro)[:500],
        ocorrida_em=_agora(),
    )
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "falha.json").write_text(falha.model_dump_json(indent=2), encoding="utf-8")


def executar_explain(args: argparse.Namespace, config: RunConfig) -> int:
    """Grava `bundle.json`, `prov.provn`, `prov.json`, `explicacao.txt` e `reexecucoes.json`.

    Returns:
        0; 2 para execução ou linha inexistente ou incoerente; 5 para evidência divergente
        (registrada em `falha.json`, sem gravar explicação).
    """
    raiz = Path(config.runtime.raiz_saidas)
    try:
        row_id = _ROW_ID.validate_python(args.row)
        run = localizar_execucao(raiz, args.run)
        explicacao = montar_explicacao(run, row_id, runtime=config.runtime)
    except ValidationError:
        logger.error("explain_recusado erro=row_invalido row=%s", args.row)
        return int(ExitCode.CONFIG_INVALIDA)
    except (ExecucaoNaoResolvida, ExplicacaoIndisponivel) as erro:
        logger.error("explain_recusado erro=%s", erro)
        return int(ExitCode.CONFIG_INVALIDA)
    except EvidenciaDivergente as erro:
        _registrar_falha(diretorio_explicacao(raiz, args.run, args.row), args.run, args.row, erro)
        logger.error("explain_falhou erro=%s", erro)
        return int(ExitCode.FALHA_OPERACIONAL)
    destino = diretorio_explicacao(raiz, run.run_id, row_id)
    _gravar(destino, explicacao)
    logger.info("explain_concluido run=%s destino=%s", run.run_id, destino)
    return int(ExitCode.OK)
