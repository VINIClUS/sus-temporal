"""Comando `sustemporal validate`: mesmo motor, só a política temporal muda."""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.temporal import MetodoId, PoliticaTemporal
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.execucoes import raiz_execucoes
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.entrada import ARQUIVO_ENTRADA, EntradaValidacao
from sustemporal.rules.ingest import exigir_sem_deletados
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_padrao
from sustemporal.rules.validate_ingest import validar_ingest

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult
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


def configurar_parser(parser: argparse.ArgumentParser) -> None:
    origem = parser.add_mutually_exclusive_group(required=True)
    origem.add_argument("--entrada", type=Path)
    origem.add_argument("--ingest", type=Path)
    parser.add_argument("--saida", type=Path, default=None)


def _politica(
    metodo: MetodoId, entrada: EntradaValidacao, regras: list[RuleSpec]
) -> PoliticaTemporal:
    if entrada.politica is not None:
        if entrada.politica.metodo is not metodo:
            raise ConfigInvalida(
                f"politica_da_entrada_de_outro_metodo metodo={entrada.politica.metodo}"
            )
        return entrada.politica
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


def _concluir(resultado: RunResult, metodo: MetodoId) -> int:
    logger.info(
        "validate_concluido run=%s metodo=%s estado=%s", resultado.run_id, metodo, resultado.estado
    )
    return (
        ExitCode.OK if resultado.estado is EstadoExecucao.CONCLUIDA else ExitCode.FALHA_OPERACIONAL
    )


def executar_validate(args: argparse.Namespace, config: RunConfig) -> int:
    """`--policy documented|atendimento|processamento` → M_TEMP|B_ATEND|B_PROC.

    `--ingest DIR` lê a pasta do `sustemporal ingest` e o registro temporal; `--entrada JSON`
    mantém os insumos explícitos. Nos dois modos a execução é gravada em
    `<raiz_saidas>/runs/<run_id>/` (`raiz_execucoes`), o único lugar onde `explain` e
    `counterfactual` descobrem execuções; `--saida` desvia a gravação, e então eles não a acham.

    Raises:
        ConfigInvalida: entrada, catálogo, política, manifesto ou pasta do ingest inválidos.
        FalhaOperacionalErro: `row_id` repetido na produção do ingest.
    """
    metodo = METODO_DA_POLITICA[args.policy]
    saida = args.saida or raiz_execucoes(config)
    if args.ingest is not None:
        return _concluir(validar_ingest(args.ingest, metodo, config, saida), metodo)
    entrada = _ler_entrada(args.entrada)
    with closing(conectar(config.runtime)) as con:
        exigir_sem_deletados(con, entrada.dataset)
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
        identidade_adicional=entrada.identidade_adicional or {},
    )
    try:
        gravada = entrada.model_copy(update={"politica": politica})
        resultado = evaluate_rules(
            entrada.dataset,
            entrada.snapshots,
            regras,
            config,
            saida,
            insumos=insumos,
            anexos={ARQUIVO_ENTRADA: gravada.model_dump_json(indent=2)},
        )
    except ValueError as erro:
        raise ConfigInvalida(f"entrada_semanticamente_invalida detalhe={erro}") from erro
    return _concluir(resultado, metodo)
