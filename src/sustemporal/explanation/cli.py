"""Comando `sustemporal explain --run RUN_ID --row ROW_ID`.

O `run_id` resolve o `run_result.json` exato da execução (`<raiz_saidas>/runs/<run_id>` ou
`<raiz_saidas>/validacao/<run_id>`), nunca um diretório "latest". A saída fica em
`<raiz_saidas>/explicacoes/<run_id>/row_<sha256(row_id)[:32]>/`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.base import Identificador
from sustemporal.contracts.experiment import RunResult
from sustemporal.contracts.records import RowId
from sustemporal.contracts.rules import FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.explanation.evidence import EvidenciaDivergente, sql_reexecucao
from sustemporal.explanation.explain import ExplicacaoIndisponivel, montar_explicacao
from sustemporal.explanation.explain_texto import TemplateInvalido
from sustemporal.explanation.prov import ProvIncompleto

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from sustemporal.contracts.config import RunConfig
    from sustemporal.explanation.explain import Explicacao

__all__ = ["diretorio_explicacao", "executar_explain", "localizar_execucao"]

logger = logging.getLogger(__name__)

_ROW_ID: TypeAdapter[str] = TypeAdapter(RowId)
_IDENTIFICADOR: TypeAdapter[str] = TypeAdapter(Identificador)
_DIRETORIOS_DE_EXECUCAO = ("runs", "validacao")


def _agora() -> datetime:
    return datetime.now(UTC)


class ExecucaoNaoResolvida(ValueError):
    """`run_id` ou `row_id` fora do formato, ou sem `run_result.json` exato e coerente."""


_RECUSAS = (ExecucaoNaoResolvida, ExplicacaoIndisponivel, TemplateInvalido, ProvIncompleto)


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


def _remover(destino: Path | None) -> None:
    """Remove a explicação anterior: nunca convivem explicação, falha e recusa."""
    if destino is not None and destino.exists():
        shutil.rmtree(destino)


def _publicar(destino: Path, arquivos: dict[str, bytes]) -> None:
    """Grava num diretório temporário irmão e só então o renomeia para `destino`."""
    temporario = destino.parent / f".{destino.name}.parcial"
    _remover(temporario)
    temporario.mkdir(parents=True)
    try:
        for nome in sorted(arquivos):
            (temporario / nome).write_bytes(arquivos[nome])
        _remover(destino)
        temporario.rename(destino)
    except OSError:
        _remover(temporario)
        raise


def _arquivos(explicacao: Explicacao) -> dict[str, bytes]:
    bundle = explicacao.bundle
    return {
        "bundle.json": bundle.model_dump_json(indent=2).encode("utf-8"),
        "prov.provn": bundle.prov_n.encode("utf-8"),
        "prov.json": explicacao.prov_json.encode("utf-8"),
        "explicacao.txt": explicacao.texto.encode("utf-8"),
        "reexecucoes.json": _reexecucoes(explicacao).encode("utf-8"),
    }


def _json(falha: FalhaOperacional) -> bytes:
    return falha.model_dump_json(indent=2).encode("utf-8")


def _validar_argumentos(args: argparse.Namespace) -> tuple[str, str]:
    """Raises: ExecucaoNaoResolvida para `--run` ou `--row` fora do formato."""
    try:
        run_id = _IDENTIFICADOR.validate_python(args.run)
        row_id = _ROW_ID.validate_python(args.row)
    except ValidationError as erro:
        raise ExecucaoNaoResolvida(
            f"argumento_invalido run={args.run!r} row={args.row!r}"
        ) from erro
    if set(run_id) <= {"."}:
        raise ExecucaoNaoResolvida(f"argumento_invalido run={run_id!r}")
    return run_id, row_id


def executar_explain(
    args: argparse.Namespace,
    config: RunConfig,
    *,
    relogio: Callable[[], datetime] = _agora,
) -> int:
    """Grava `bundle.json`, `prov.provn`, `prov.json`, `explicacao.txt` e `reexecucoes.json`.

    Returns:
        0; 2 para argumento, execução ou linha inexistente ou incoerente; 5 para evidência
        divergente (só `falha.json`, nenhuma explicação) ou falha de gravação. A publicação é
        atômica (diretório temporário renomeado); recusa remove a explicação anterior.
    """
    raiz = Path(config.runtime.raiz_saidas)
    destino: Path | None = None
    try:
        run_id, row_id = _validar_argumentos(args)
        destino = diretorio_explicacao(raiz, run_id, row_id)
        run = localizar_execucao(raiz, run_id)
        _publicar(destino, _arquivos(montar_explicacao(run, row_id, runtime=config.runtime)))
    except _RECUSAS as erro:
        _remover(destino)
        logger.error("explain_recusado erro=%s", erro)
        return int(ExitCode.CONFIG_INVALIDA)
    except EvidenciaDivergente as erro:
        falha = FalhaOperacional(
            run_id=run_id,
            etapa="reexecutar_evidencia",
            row_id=row_id,
            erro=str(erro)[:500],
            ocorrida_em=relogio(),
        )
        _publicar(diretorio_explicacao(raiz, run_id, row_id), {"falha.json": _json(falha)})
        logger.error("explain_falhou erro=%s", erro)
        return int(ExitCode.FALHA_OPERACIONAL)
    except (OSError, duckdb.Error) as erro:
        logger.error("explain_falhou erro=falha_operacional tipo=%s", type(erro).__name__)
        return int(ExitCode.FALHA_OPERACIONAL)
    logger.info("explain_concluido run=%s destino=%s", run_id, destino)
    return int(ExitCode.OK)
