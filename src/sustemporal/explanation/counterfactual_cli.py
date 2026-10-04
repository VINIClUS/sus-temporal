"""Comando `sustemporal counterfactual --run RUN_ID --row ROW_ID` (T09).

O `run_id` resolve a pasta exata da execução (`<raiz_saidas>/runs/<run_id>` ou
`<raiz_saidas>/validacao/<run_id>`), nunca um diretório "latest". O bundle vem do `explain` real
e os insumos de `entrada_validacao.json`, conferidos pelo `run_id` recalculado. A saída fica em
`<raiz_saidas>/contrafactuais/<run_id>/row_<sha256(row_id)[:32]>/contrafactual.json`.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.base import Identificador
from sustemporal.contracts.records import RowId
from sustemporal.contracts.rules import FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.explanation.cli import ExecucaoNaoResolvida, localizar_execucao
from sustemporal.explanation.counterfactual import (
    BaselineIncoerente,
    SemViolacao,
    search_counterfactuals,
)
from sustemporal.explanation.counterfactual_contexto import (
    ContextoIndisponivel,
    contexto_da_execucao,
)
from sustemporal.explanation.counterfactual_operacoes import CatalogoOperacoesInvalido
from sustemporal.explanation.counterfactual_sobreposicao import (
    InsumoCadastralInvalido,
    RevalidacaoFalhou,
)
from sustemporal.explanation.evidence import EvidenciaDivergente
from sustemporal.explanation.explain import ExplicacaoIndisponivel, montar_explicacao

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from sustemporal.contracts.config import RunConfig

__all__ = ["ARQUIVO_RESULTADO", "diretorio_contrafactual", "executar_counterfactual"]

logger = logging.getLogger(__name__)

ARQUIVO_RESULTADO = "contrafactual.json"
_ROW_ID: TypeAdapter[str] = TypeAdapter(RowId)
_IDENTIFICADOR: TypeAdapter[str] = TypeAdapter(Identificador)
_RECUSAS = (
    ExecucaoNaoResolvida,
    ExplicacaoIndisponivel,
    ContextoIndisponivel,
    SemViolacao,
    CatalogoOperacoesInvalido,
)
_FALHAS = (
    EvidenciaDivergente,
    BaselineIncoerente,
    RevalidacaoFalhou,
    InsumoCadastralInvalido,
    OSError,
    duckdb.Error,
)


def _agora() -> datetime:
    return datetime.now(UTC)


def diretorio_contrafactual(raiz: Path, run_id: str, row_id: str) -> Path:
    """Diretório derivado só do `run_id` e do `row_id`."""
    sufixo = hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:32]
    return Path(raiz) / "contrafactuais" / run_id / f"row_{sufixo}"


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


def _remover(destino: Path | None) -> None:
    """Remove o resultado anterior: nunca convivem resultado, falha e recusa."""
    if destino is not None and destino.exists():
        shutil.rmtree(destino)


def _publicar(destino: Path, nome: str, conteudo: bytes) -> None:
    """Grava num diretório temporário irmão e só então o renomeia para `destino`."""
    temporario = destino.parent / f".{destino.name}.parcial"
    _remover(temporario)
    temporario.mkdir(parents=True)
    try:
        (temporario / nome).write_bytes(conteudo)
        _remover(destino)
        temporario.rename(destino)
    except OSError:
        _remover(temporario)
        raise


def _buscar(raiz: Path, run_id: str, row_id: str, config: RunConfig) -> bytes:
    run = localizar_execucao(raiz, run_id)
    bundle = montar_explicacao(run, row_id, runtime=config.runtime).bundle
    contexto = contexto_da_execucao(raiz, run_id, config)
    resultado = search_counterfactuals(bundle, config, contexto=contexto)
    return resultado.model_dump_json(indent=2).encode("utf-8")


def _registrar_falha(destino: Path, falha: FalhaOperacional, erro: Exception) -> None:
    logger.error("counterfactual_falhou tipo=%s erro=%s", type(erro).__name__, erro)
    try:
        _publicar(destino, "falha.json", falha.model_dump_json(indent=2).encode("utf-8"))
    except OSError as gravacao:
        logger.error("counterfactual_falha_nao_gravada erro=%s", gravacao)


def executar_counterfactual(
    args: argparse.Namespace,
    config: RunConfig,
    *,
    relogio: Callable[[], datetime] = _agora,
) -> int:
    """Publica `contrafactual.json` do registro; hipótese, nunca aprovação garantida.

    Returns:
        0; 2 para argumento, execução, linha ou insumos inexistentes ou incoerentes, ou linha
        sem violação (recusa remove o resultado anterior); 5 para falha operacional (evidência
        divergente, cadastro ilegível, motor sem concluir), com só `falha.json` publicado.
    """
    raiz = Path(config.runtime.raiz_saidas)
    destino: Path | None = None
    try:
        run_id, row_id = _validar_argumentos(args)
        destino = diretorio_contrafactual(raiz, run_id, row_id)
        _publicar(destino, ARQUIVO_RESULTADO, _buscar(raiz, run_id, row_id, config))
    except _RECUSAS as erro:
        _remover(destino)
        logger.error("counterfactual_recusado erro=%s", erro)
        return int(ExitCode.CONFIG_INVALIDA)
    except _FALHAS as erro:
        if destino is not None:
            falha = FalhaOperacional(
                run_id=run_id,
                etapa="contrafactual",
                row_id=row_id,
                erro=str(erro)[:500],
                ocorrida_em=relogio(),
            )
            _registrar_falha(destino, falha, erro)
        return int(ExitCode.FALHA_OPERACIONAL)
    logger.info("counterfactual_concluido run=%s destino=%s", run_id, destino)
    return int(ExitCode.OK)
