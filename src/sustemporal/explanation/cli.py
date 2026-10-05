"""Comando `sustemporal explain --run RUN_ID --row ROW_ID`.

O `run_id` resolve o `run_result.json` exato da execução em `<raiz_saidas>/runs/<run_id>` (o único
lugar das execuções do `validate`, ver `sustemporal.execucoes`), nunca um diretório "latest". A
saída fica em `<raiz_saidas>/explicacoes/<run_id>/row_<sha256(row_id)[:32]>/`.
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

from sustemporal.contracts.records import RowId
from sustemporal.contracts.rules import FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.execucoes import ExecucaoNaoResolvida, ler_execucao, raiz_execucoes, validar_run_id
from sustemporal.explanation.evidence import EvidenciaDivergente, sql_reexecucao
from sustemporal.explanation.explain import ExplicacaoIndisponivel, montar_explicacao
from sustemporal.explanation.explain_texto import TemplateInvalido
from sustemporal.explanation.prov import ProvIncompleto

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from sustemporal.contracts.config import RunConfig
    from sustemporal.explanation.explain import Explicacao

__all__ = ["diretorio_explicacao", "executar_explain"]

logger = logging.getLogger(__name__)

_ROW_ID: TypeAdapter[str] = TypeAdapter(RowId)
_RECUSAS = (ExecucaoNaoResolvida, ExplicacaoIndisponivel, TemplateInvalido, ProvIncompleto)


def _agora() -> datetime:
    return datetime.now(UTC)


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


def _registrar_falha(destino: Path, falha: FalhaOperacional) -> None:
    """Publica `falha.json`; se nem isso for possível, remove a explicação anterior."""
    try:
        _publicar(destino, {"falha.json": falha.model_dump_json(indent=2).encode("utf-8")})
    except OSError as erro:
        logger.error("explain_falha_nao_publicada tipo=%s", type(erro).__name__)
        try:
            _remover(destino)
        except OSError:
            logger.error("explain_destino_nao_removido destino=%s", destino)


def _validar_argumentos(args: argparse.Namespace) -> tuple[str, str]:
    """Raises: ExecucaoNaoResolvida para `--run` ou `--row` fora do formato."""
    try:
        run_id = validar_run_id(args.run)
        row_id = _ROW_ID.validate_python(args.row)
    except (ExecucaoNaoResolvida, ValidationError) as erro:
        raise ExecucaoNaoResolvida(
            f"argumento_invalido run={args.run!r} row={args.row!r}"
        ) from erro
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
        run = ler_execucao(raiz_execucoes(config), run_id)
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
        logger.error("explain_falhou erro=%s", erro)
        _registrar_falha(diretorio_explicacao(raiz, run_id, row_id), falha)
        return int(ExitCode.FALHA_OPERACIONAL)
    except (OSError, duckdb.Error) as erro:
        logger.error("explain_falhou erro=falha_operacional tipo=%s", type(erro).__name__)
        return int(ExitCode.FALHA_OPERACIONAL)
    logger.info("explain_concluido run=%s destino=%s", run_id, destino)
    return int(ExitCode.OK)
