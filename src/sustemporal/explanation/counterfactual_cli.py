"""Comando `sustemporal counterfactual --run RUN_ID --row ROW_ID` (T09).

O `run_id` resolve a pasta exata da execução em `<raiz_saidas>/runs/<run_id>` (o único lugar das
execuções do `validate`, ver `sustemporal.execucoes`), nunca um diretório "latest". O bundle vem
do `explain` real e os insumos de `entrada_validacao.json`, conferidos pelo `run_id` recalculado.
A saída fica em `<raiz_saidas>/contrafactuais/<run_id>/id_<identidade>/row_<sha256(row_id)[:32]>/`,
com `contrafactual.json` e `identidade.json` (SHA-256 de `catalog/operations.yaml`, versão do
código e competência AAAAMM do relógio, a as-of, lida uma vez e usada em toda a busca).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.records import RowId
from sustemporal.contracts.rules import FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.execucoes import ExecucaoNaoResolvida, ler_execucao, raiz_execucoes, validar_run_id
from sustemporal.explanation.counterfactual import (
    BaselineIncoerente,
    SemViolacao,
    search_counterfactuals,
)
from sustemporal.explanation.counterfactual_contexto import (
    ContextoIndisponivel,
    contexto_da_execucao,
)
from sustemporal.explanation.counterfactual_executabilidade import competencia_do_relogio
from sustemporal.explanation.counterfactual_operacoes import (
    CATALOGO_OPERACOES,
    CatalogoOperacoesInvalido,
    operacoes_dos_bytes,
)
from sustemporal.explanation.counterfactual_sobreposicao import (
    InsumoCadastralInvalido,
    RevalidacaoFalhou,
)
from sustemporal.explanation.evidence import EvidenciaDivergente
from sustemporal.explanation.explain import ExplicacaoIndisponivel, montar_explicacao
from sustemporal.runtime_info import versao_codigo

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable

    from sustemporal.contracts import OperationSpec
    from sustemporal.contracts.config import RunConfig

__all__ = [
    "ARQUIVO_RESULTADO",
    "diretorio_contrafactual",
    "executar_counterfactual",
    "identidade_contrafactual",
]

logger = logging.getLogger(__name__)

ARQUIVO_RESULTADO = "contrafactual.json"
_RAIZ_CODIGO = CATALOGO_OPERACOES.parents[1]
_ROW_ID: TypeAdapter[str] = TypeAdapter(RowId)
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


@dataclass(frozen=True)
class _CatalogoLido:
    """Operações e identidade derivadas dos mesmos bytes do catálogo, lidos uma vez."""

    operacoes: tuple[OperationSpec, ...]
    identidade: dict[str, object]

    @property
    def chave(self) -> str:
        return str(self.identidade["identidade"])


def _ler_catalogo(catalogo: Path, as_of: str | None) -> _CatalogoLido:
    """Raises: CatalogoOperacoesInvalido para arquivo ilegível ou catálogo inválido."""
    try:
        bruto = catalogo.read_bytes()
    except OSError as erro:
        raise CatalogoOperacoesInvalido(
            f"catalogo_operacoes_invalido caminho={catalogo} erro={erro}"
        ) from erro
    operacoes = operacoes_dos_bytes(bruto, origem=str(catalogo))
    return _CatalogoLido(operacoes, _identidade(hashlib.sha256(bruto).hexdigest(), as_of))


def _identidade(catalogo_sha256: str, as_of: str | None) -> dict[str, object]:
    conteudo: dict[str, object] = {
        "catalogo_operacoes_sha256": catalogo_sha256,
        "codigo": versao_codigo(_RAIZ_CODIGO).model_dump(mode="json"),
    }
    if as_of is not None:
        conteudo["competencia_as_of"] = as_of
    return conteudo | {"identidade": hash_canonico(conteudo)[:32]}


def identidade_contrafactual(
    catalogo: Path = CATALOGO_OPERACOES, *, as_of: str | None = None
) -> str:
    """Identidade do catálogo de operações, do código e da competência as-of do resultado.

    Outro catálogo, outra versão do código ou outro mês do relógio gera outro destino: uma
    hipótese já publicada nunca é sobrescrita por outra produzida com regras de busca ou
    executabilidade diferentes. Sem `as_of` a identidade é a de antes (catálogo e código), então
    ids já emitidos continuam válidos.
    """
    return _ler_catalogo(catalogo, as_of).chave


def diretorio_contrafactual(raiz: Path, run_id: str, row_id: str, identidade: str) -> Path:
    """Diretório derivado do `run_id`, da identidade do catálogo e código, e do `row_id`."""
    sufixo = hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:32]
    return Path(raiz) / "contrafactuais" / run_id / f"id_{identidade}" / f"row_{sufixo}"


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


def _remover(destino: Path | None) -> None:
    """Remove o resultado anterior: nunca convivem resultado, falha e recusa."""
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


def _buscar(
    alvo: tuple[str, str],
    config: RunConfig,
    catalogo: _CatalogoLido,
    relogio: Callable[[], datetime],
) -> dict[str, bytes]:
    run_id, row_id = alvo
    execucoes = raiz_execucoes(config)
    run = ler_execucao(execucoes, run_id)
    bundle = montar_explicacao(run, row_id, runtime=config.runtime).bundle
    contexto = replace(contexto_da_execucao(execucoes, run_id, config), relogio=relogio)
    resultado = search_counterfactuals(
        bundle, config, contexto=contexto, operacoes=catalogo.operacoes
    )
    identidade = json.dumps(catalogo.identidade, ensure_ascii=False, indent=2, sort_keys=True)
    return {
        ARQUIVO_RESULTADO: resultado.model_dump_json(indent=2).encode("utf-8"),
        "identidade.json": identidade.encode("utf-8"),
    }


def _registrar_falha(destino: Path, falha: FalhaOperacional, erro: Exception) -> None:
    """Remove o resultado anterior antes de tentar gravar a falha; nunca sobra resultado."""
    logger.error("counterfactual_falhou tipo=%s erro=%s", type(erro).__name__, erro)
    try:
        _remover(destino)
        _publicar(destino, {"falha.json": falha.model_dump_json(indent=2).encode("utf-8")})
    except OSError as gravacao:
        logger.error("counterfactual_falha_nao_gravada erro=%s", gravacao)


def executar_counterfactual(
    args: argparse.Namespace,
    config: RunConfig,
    *,
    relogio: Callable[[], datetime] = _agora,
    catalogo: Path = CATALOGO_OPERACOES,
) -> int:
    """Publica `contrafactual.json` do registro; hipótese, nunca aprovação garantida.

    O instante de `relogio` é lido uma vez: o mês dele entra na identidade do destino e o mesmo
    instante decide competência fechada e executabilidade em toda a busca.

    Returns:
        0; 2 para argumento, execução, linha ou insumos inexistentes ou incoerentes, ou linha
        sem violação (recusa remove o resultado anterior); 5 para falha operacional (evidência
        divergente, cadastro ilegível, motor sem concluir), com só `falha.json` publicado.
    """
    raiz = Path(config.runtime.raiz_saidas)
    destino: Path | None = None
    agora = relogio()
    try:
        run_id, row_id = _validar_argumentos(args)
        lido = _ler_catalogo(catalogo, competencia_do_relogio(agora))
        destino = diretorio_contrafactual(raiz, run_id, row_id, lido.chave)
        _publicar(destino, _buscar((run_id, row_id), config, lido, lambda: agora))
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
