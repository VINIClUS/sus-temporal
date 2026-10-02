"""Comando `sustemporal validate`: mesmo motor, só a política temporal muda."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import ContratoBase
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.records import DatasetRef
from sustemporal.contracts.temporal import MetodoId, PoliticaTemporal, SnapshotSet
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_padrao

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "METODO_DA_POLITICA",
    "EntradaValidacao",
    "configurar_parser",
    "executar_validate",
]

logger = logging.getLogger(__name__)

METODO_DA_POLITICA = {
    "documented": MetodoId.M_TEMP,
    "atendimento": MetodoId.B_ATEND,
    "processamento": MetodoId.B_PROC,
}


class EntradaValidacao(ContratoBase):
    """Insumos explícitos da validação; nenhum diretório "latest" é resolvido implicitamente."""

    dataset: DatasetRef
    snapshots: SnapshotSet
    auxiliares: tuple[DatasetRef, ...] = ()
    selecoes: DatasetRef | None = None
    cobertura: DatasetRef | None = None
    integridade: dict[str, EstadoIntegridade] = Field(default_factory=dict)
    politica_documentada: PoliticaTemporal | None = None


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--saida", type=Path, default=None)


def _politica(
    metodo: MetodoId, entrada: EntradaValidacao, regras: list[RuleSpec]
) -> PoliticaTemporal:
    documentada = entrada.politica_documentada
    if metodo is MetodoId.M_TEMP and documentada is not None:
        if documentada.metodo is not MetodoId.M_TEMP:
            raise ConfigInvalida(
                f"politica_documentada_de_outro_metodo metodo={documentada.metodo}"
            )
        return documentada
    return politica_padrao(metodo, regras)


def _ler_entrada(caminho: Path) -> EntradaValidacao:
    try:
        return EntradaValidacao.model_validate_json(caminho.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as erro:
        raise ConfigInvalida(f"entrada_de_validacao_invalida caminho={caminho}") from erro


def executar_validate(args: argparse.Namespace, config: RunConfig) -> int:
    """`--policy documented|atendimento|processamento` → M_TEMP|B_ATEND|B_PROC.

    Raises:
        ConfigInvalida: entrada, catálogo ou política inválidos.
    """
    metodo = METODO_DA_POLITICA[args.policy]
    entrada = _ler_entrada(args.entrada)
    try:
        regras = carregar_regras()
        politica = _politica(metodo, entrada, regras)
    except (CatalogoInvalido, MetodoInvalido) as erro:
        raise ConfigInvalida(str(erro)) from erro
    insumos = InsumosAvaliacao(
        auxiliares=entrada.auxiliares,
        selecoes=entrada.selecoes,
        cobertura=entrada.cobertura,
        integridade=entrada.integridade,
        politica=politica,
    )
    saida = args.saida or Path(config.runtime.raiz_saidas) / "validacao"
    try:
        resultado = evaluate_rules(
            entrada.dataset, entrada.snapshots, regras, config, saida, insumos=insumos
        )
    except ValueError as erro:
        raise ConfigInvalida(f"entrada_semanticamente_invalida detalhe={erro}") from erro
    logger.info(
        "validate_concluido run=%s metodo=%s estado=%s", resultado.run_id, metodo, resultado.estado
    )
    return (
        ExitCode.OK if resultado.estado is EstadoExecucao.CONCLUIDA else ExitCode.FALHA_OPERACIONAL
    )
