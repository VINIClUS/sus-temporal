"""Registro append-only das avaliações, com resultados nulos e correções declaradas (T11).

Cada linha JSON leva o próprio hash e o hash da linha anterior; reescrever ou apagar qualquer
linha quebra o encadeamento e o registro é recusado. Toda avaliação entra, inclusive a de
resultado nulo (métricas sem valor). Depois da abertura do teste, nova rodada confirmatória do
mesmo congelamento só entra como correção declarada, e a rodada anterior permanece. A correção
só aponta para relatório confirmatório já registrado do mesmo congelamento. A releitura final,
a checagem de rodada única e o append correm sob uma trava entre processos (`fcntl.flock` em
`arquivo_de_trava`), então dois `evaluate` simultâneos não repetem `seq` nem quebram a cadeia.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.experiment import ModoExecucao
from sustemporal.errors import FalhaOperacionalErro, PortaoRecusado

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from sustemporal.contracts import EvaluationReport

__all__ = ["arquivo_de_trava", "exigir_rodada_permitida", "ler_registro", "registrar_execucao"]

logger = logging.getLogger(__name__)


def arquivo_de_trava(registro: Path) -> Path:
    """Arquivo de trava entre processos, ao lado do registro."""
    return registro.with_name(f"{registro.name}.trava")


@contextlib.contextmanager
def _travado(registro: Path) -> Iterator[None]:
    """Trava exclusiva entre processos em `arquivo_de_trava(registro)`, solta ao sair."""
    registro.parent.mkdir(parents=True, exist_ok=True)
    with arquivo_de_trava(registro).open("a") as arquivo:
        fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _canonico(conteudo: dict[str, Any]) -> str:
    return json.dumps(conteudo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _linhas(registro: Path) -> list[str]:
    try:
        if not registro.exists():
            return []
        return registro.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as erro:
        motivo = type(erro).__name__
        raise FalhaOperacionalErro(f"registro_adulterado motivo={motivo}") from erro


def ler_registro(registro: Path) -> list[dict[str, Any]]:
    """Entradas do registro, conferindo o encadeamento de cada linha com a anterior.

    Raises:
        FalhaOperacionalErro: linha alterada, removida, reordenada ou ilegível, UTF-8 inválido
            ou arquivo que o sistema nega abrir.
    """
    entradas: list[dict[str, Any]] = []
    anterior = None
    for numero, linha in enumerate(_linhas(registro)):
        try:
            entrada = json.loads(linha)
            proprio = entrada.pop("hash")
        except (ValueError, KeyError, AttributeError) as erro:
            raise FalhaOperacionalErro(f"registro_adulterado linha={numero}") from erro
        integra = proprio == _sha(_canonico(entrada))
        if not integra or entrada.get("seq") != numero or entrada.get("anterior") != anterior:
            raise FalhaOperacionalErro(f"registro_adulterado linha={numero}")
        entradas.append(entrada)
        anterior = proprio
    return entradas


def _exigir_correcao_valida(
    entradas: list[dict[str, Any]],
    corrige: str | None,
    declaracao: str | None,
    freeze_id: str | None,
) -> None:
    if corrige is None:
        return
    if not (declaracao or "").strip():
        raise ValueError(f"correcao_sem_declaracao corrige={corrige}")
    alvos = [entrada for entrada in entradas if entrada["report_id"] == corrige]
    if not alvos:
        raise ValueError(f"correcao_de_execucao_inexistente corrige={corrige}")
    confirmatorios = [a for a in alvos if a["modo"] == ModoExecucao.CONFIRMATORIO.value]
    if not confirmatorios:
        raise ValueError(f"correcao_de_relatorio_nao_confirmatorio corrige={corrige}")
    if all(alvo["freeze_id"] != freeze_id for alvo in confirmatorios):
        raise ValueError(f"correcao_de_outro_congelamento corrige={corrige} freeze={freeze_id}")


def _exigir_unica_rodada(
    entradas: list[dict[str, Any]], modo: ModoExecucao, freeze_id: str | None
) -> None:
    if modo is not ModoExecucao.CONFIRMATORIO:
        return
    if any(
        entrada["modo"] == ModoExecucao.CONFIRMATORIO.value and entrada["freeze_id"] == freeze_id
        for entrada in entradas
    ):
        raise PortaoRecusado(f"reabertura_do_teste_sem_correcao_declarada freeze={freeze_id}")


def exigir_rodada_permitida(
    registro: Path,
    modo: ModoExecucao,
    freeze_id: str | None,
    *,
    corrige: str | None = None,
    declaracao: str | None = None,
) -> None:
    """Recusa, antes de avaliar, a segunda rodada confirmatória sem correção declarada válida.

    Raises:
        PortaoRecusado: já existe rodada confirmatória para o congelamento e não há correção.
        ValueError: correção sem declaração, ou cujo alvo não existe, não é relatório
            confirmatório ou é de outro congelamento.
        FalhaOperacionalErro: registro adulterado.
    """
    entradas = ler_registro(registro)
    _exigir_correcao_valida(entradas, corrige, declaracao, freeze_id)
    if corrige is None:
        _exigir_unica_rodada(entradas, modo, freeze_id)


def _nova_entrada(
    entradas: list[dict[str, Any]],
    relatorio: EvaluationReport,
    agora: datetime,
    *,
    corrige: str | None,
    declaracao: str | None,
) -> dict[str, Any]:
    return {
        "seq": len(entradas),
        "anterior": _sha(_canonico(entradas[-1])) if entradas else None,
        "registrado_em": agora.isoformat(),
        "report_id": relatorio.report_id,
        "modo": relatorio.modo.value,
        "origem_dados": relatorio.origem_dados.value,
        "freeze_id": relatorio.freeze_id,
        "decisao_g2": relatorio.decisao_g2,
        "runs": list(relatorio.runs),
        "metricas": len(relatorio.metricas),
        "metricas_nulas": sum(1 for m in relatorio.metricas if m.valor is None),
        "corrige": corrige,
        "declaracao": declaracao,
    }


def registrar_execucao(
    registro: Path,
    relatorio: EvaluationReport,
    *,
    corrige: str | None = None,
    declaracao: str | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Acrescenta uma entrada; nunca reescreve nem apaga as anteriores.

    A releitura do registro, a checagem de unicidade e o append correm sob a trava exclusiva
    entre processos (`arquivo_de_trava`), solta também na recusa; quem chega depois espera e
    relê o registro já com a entrada do outro.

    Raises:
        FalhaOperacionalErro: registro existente adulterado.
        ValueError: correção sem declaração, ou cujo alvo não existe, não é relatório
            confirmatório ou é de outro congelamento.
        PortaoRecusado: segunda rodada confirmatória do mesmo congelamento sem correção.
    """
    with _travado(registro):
        entradas = ler_registro(registro)
        _exigir_correcao_valida(entradas, corrige, declaracao, relatorio.freeze_id)
        if corrige is None:
            _exigir_unica_rodada(entradas, relatorio.modo, relatorio.freeze_id)
        agora = (relogio or (lambda: datetime.now(UTC)))()
        entrada = _nova_entrada(entradas, relatorio, agora, corrige=corrige, declaracao=declaracao)
        with registro.open("a", encoding="utf-8") as arquivo:
            arquivo.write(_canonico(_com_hash(entrada)) + "\n")
    logger.info("execucao_registrada report=%s seq=%d", relatorio.report_id, entrada["seq"])
    return entrada


def _com_hash(entrada: dict[str, Any]) -> dict[str, Any]:
    return {**entrada, "hash": _sha(_canonico(entrada))}
