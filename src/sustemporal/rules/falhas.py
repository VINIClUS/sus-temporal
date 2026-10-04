"""Falhas operacionais da avaliação: registradas à parte, nunca convertidas em estado."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.rules import FalhaOperacional

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

__all__ = ["ERROS_OPERACIONAIS", "RegistroFalhas"]

logger = logging.getLogger(__name__)

ERROS_OPERACIONAIS: tuple[type[Exception], ...] = (
    duckdb.Error,
    ValueError,
    OSError,
    TypeError,
    KeyError,
    ArithmeticError,
)
_MAX_ERRO = 500


@dataclass
class RegistroFalhas:
    """Acumula `FalhaOperacional` em ordem de ocorrência (sequência a partir de 1)."""

    run_id: str
    relogio: Callable[[], datetime]
    falhas: list[FalhaOperacional] = field(default_factory=list)

    def registrar(
        self,
        etapa: str,
        erro: Exception,
        *,
        row_id: str | None = None,
        rule_id: str | None = None,
    ) -> None:
        detalhe = " ".join(str(erro).split())[:_MAX_ERRO]
        falha = FalhaOperacional(
            run_id=self.run_id,
            etapa=etapa,
            row_id=row_id,
            rule_id=rule_id,
            erro=f"tipo={type(erro).__name__} detalhe={detalhe}",
            ocorrida_em=self.relogio(),
        )
        self.falhas.append(falha)
        logger.error(
            "falha_operacional run=%s etapa=%s regra=%s registro=%s erro=%s",
            self.run_id,
            etapa,
            rule_id,
            row_id,
            falha.erro,
        )

    @property
    def regras_com_falha(self) -> set[str]:
        return {f.rule_id for f in self.falhas if f.rule_id is not None and f.row_id is None}

    @property
    def registros_com_falha(self) -> set[str]:
        return {f.row_id for f in self.falhas if f.row_id is not None}
