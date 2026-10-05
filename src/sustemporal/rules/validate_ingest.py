"""`sustemporal validate --ingest DIR`: da pasta do ingest e do registro temporal às saídas."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from sustemporal.contracts.base import hash_canonico
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida
from sustemporal.ingest.territorio import carregar_territorio, municipios_ibge6
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.entrada import ARQUIVO_ENTRADA, EntradaValidacao
from sustemporal.rules.ingest import (
    InsumosIngest,
    carregar_registro,
    integridade_do_registro,
    ler_datasets,
    preparar_insumos_ingest,
)
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_da_execucao
from sustemporal.rules.lote import SelecaoEmLote, selecionar_em_lote

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import MetodoId, PoliticaTemporal
    from sustemporal.temporal.registry import RegistroTemporal

__all__ = ["municipios_do_piloto", "validar_ingest"]

logger = logging.getLogger(__name__)


def municipios_do_piloto(config: RunConfig) -> frozenset[str]:
    """IBGE6 do território do piloto (`ingest.territorio`: contrato, UF e dígito verificador).

    Raises:
        ConfigInvalida: sem piloto ou território inválido.
    """
    piloto = config.piloto
    if piloto is None:
        raise ConfigInvalida("validate_ingest_sem_piloto")
    territorio = carregar_territorio(Path(piloto.territorio), uf=piloto.uf)
    return municipios_ibge6(territorio)


def _politica(metodo: MetodoId, config: RunConfig, regras: list[RuleSpec]) -> PoliticaTemporal:
    do_metodo = config.model_copy(update={"metodos": (metodo,)})
    return politica_da_execucao(InsumosAvaliacao(), do_metodo, regras)


def _recorte(municipios: frozenset[str], insumos: InsumosIngest) -> dict[str, object]:
    """Conteúdo de `recorte_territorial.json`; o hash dele entra no `run_id`."""
    origem = insumos.cobertura_da_ingestao
    return {
        "municipios": sorted(municipios),
        "exclusoes": insumos.exclusoes,
        "cobertura_da_ingestao": origem.dataset_id if origem else None,
    }


def _anexos(
    insumos: InsumosAvaliacao,
    lote: SelecaoEmLote,
    producao: DatasetRef,
    recorte: dict[str, object],
) -> dict[str, str]:
    """`entrada_validacao.json` (o que basta para reavaliar) e `recorte_territorial.json`."""
    entrada = EntradaValidacao(
        dataset=producao,
        snapshots=lote.snapshots,
        auxiliares=insumos.auxiliares,
        selecoes=lote.selecoes,
        cobertura=insumos.cobertura,
        integridade=dict(insumos.integridade),
        politica=insumos.politica,
        identidade_adicional=dict(insumos.identidade_adicional) or None,
    )
    return {
        ARQUIVO_ENTRADA: entrada.model_dump_json(indent=2),
        "recorte_territorial.json": json.dumps(recorte, indent=2, sort_keys=True),
    }


def _preparar(
    datasets: list[DatasetRef],
    regras: list[RuleSpec],
    contexto: tuple[RunConfig, RegistroTemporal, frozenset[str]],
    destino: Path,
) -> InsumosIngest:
    con = conectar(contexto[0].runtime)
    try:
        return preparar_insumos_ingest(con, datasets, regras, contexto, destino)
    except (ValueError, duckdb.Error) as erro:
        raise ConfigInvalida(f"ingest_semanticamente_invalido detalhe={erro}") from erro
    finally:
        con.close()


def validar_ingest(pasta: Path, metodo: MetodoId, config: RunConfig, saida: Path) -> RunResult:
    """Confere a pasta e o registro antes de gravar qualquer coisa; depois avalia em lote.

    Raises:
        ConfigInvalida: catálogo, política, manifesto, território ou pasta do ingest inválidos, ou
            execução já gravada com outro código (`evaluate_rules`: a execução é imutável).
        FalhaOperacionalErro: `row_id` repetido na produção.
    """
    try:
        regras = carregar_regras()
        politica = _politica(metodo, config, regras)
    except (CatalogoInvalido, MetodoInvalido) as erro:
        raise ConfigInvalida(str(erro)) from erro
    registro = carregar_registro(config)
    datasets = ler_datasets(pasta)
    municipios = municipios_do_piloto(config)
    insumos = _preparar(datasets, regras, (config, registro, municipios), saida / "entradas")
    recorte = _recorte(municipios, insumos)
    avaliacao = InsumosAvaliacao(
        auxiliares=insumos.auxiliares,
        cobertura=insumos.cobertura,
        integridade=integridade_do_registro(registro, corte=config.corte_observacao),
        politica=politica,
        identidade_adicional={"recorte_territorial": hash_canonico(recorte)},
    )
    try:
        lote = selecionar_em_lote(
            insumos.producao, regras, config, registro, saida / "selecoes", insumos=avaliacao
        )
        anexos = _anexos(avaliacao, lote, insumos.producao, recorte)
        return evaluate_rules(
            insumos.producao,
            lote.snapshots,
            regras,
            config,
            saida,
            insumos=replace(avaliacao, selecoes=lote.selecoes),
            anexos=anexos,
        )
    except ValueError as erro:
        raise ConfigInvalida(f"entrada_semanticamente_invalida detalhe={erro}") from erro
