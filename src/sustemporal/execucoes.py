"""Lugar único das execuções do `validate` e leitor comum do `run_result.json`.

`validate` (`--entrada` e `--ingest`) grava cada execução em `<raiz_saidas>/runs/<run_id>/` por
padrão e os consumidores (`explain`, `counterfactual`) só a descobrem ali, pelo `run_id` exato e
nunca pela mais recente. `validate --saida` desvia a gravação; uma execução fora de `runs/` não é
encontrada por eles.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.base import Identificador
from sustemporal.contracts.experiment import RunResult

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig

__all__ = [
    "DIRETORIO_EXECUCOES",
    "ExecucaoNaoResolvida",
    "ler_execucao",
    "raiz_execucoes",
    "validar_run_id",
]

DIRETORIO_EXECUCOES = "runs"
_ARQUIVO_EXECUCAO = "run_result.json"
_IDENTIFICADOR: TypeAdapter[str] = TypeAdapter(Identificador)


class ExecucaoNaoResolvida(ValueError):
    """`run_id` fora do formato, ou sem `run_result.json` exato, legível e coerente."""


def raiz_execucoes(config: RunConfig) -> Path:
    """Raiz das execuções: `<raiz_saidas>/runs`."""
    return Path(config.runtime.raiz_saidas) / DIRETORIO_EXECUCOES


def validar_run_id(run_id: str) -> str:
    """`run_id` no formato de identificador e que não aponta para fora da raiz (`.`, `..`).

    Raises:
        ExecucaoNaoResolvida: fora de `[A-Za-z0-9_.:-]{1,128}` ou só de pontos.
    """
    try:
        valido = _IDENTIFICADOR.validate_python(run_id)
    except ValidationError as erro:
        raise ExecucaoNaoResolvida(f"argumento_invalido run={run_id!r}") from erro
    if set(valido) <= {"."}:
        raise ExecucaoNaoResolvida(f"argumento_invalido run={valido!r}")
    return valido


def _ilegivel(run_id: str, caminho: Path, erro: Exception) -> ExecucaoNaoResolvida:
    return ExecucaoNaoResolvida(
        f"execucao_ilegivel run={run_id} caminho={caminho} erro={type(erro).__name__}"
    )


def ler_execucao(raiz: Path, run_id: str) -> RunResult:
    """`RunResult` gravado em `<raiz>/<run_id>/run_result.json`; nunca a execução mais recente.

    `raiz` é a raiz das execuções (`raiz_execucoes(config)`).

    Raises:
        ExecucaoNaoResolvida: `run_id` fora do formato (`argumento_invalido`), arquivo ausente
            (`execucao_inexistente`), ilegível (`execucao_ilegivel`: erro de leitura, bytes que
            não são UTF-8, JSON inválido ou fora do contrato) ou gravado com outro `run_id`
            (`execucao_incoerente`).
    """
    run_id = validar_run_id(run_id)
    caminho = Path(raiz) / run_id / _ARQUIVO_EXECUCAO
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError) as erro:
        raise ExecucaoNaoResolvida(f"execucao_inexistente run={run_id} raiz={raiz}") from erro
    except (OSError, UnicodeDecodeError) as erro:
        raise _ilegivel(run_id, caminho, erro) from erro
    try:
        resultado = RunResult.model_validate_json(texto)
    except ValidationError as erro:
        raise _ilegivel(run_id, caminho, erro) from erro
    if resultado.run_id != run_id:
        raise ExecucaoNaoResolvida(f"execucao_incoerente run={run_id} gravada={resultado.run_id}")
    return resultado
