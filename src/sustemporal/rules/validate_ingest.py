"""`sustemporal validate --ingest DIR`: da pasta do ingest e do registro temporal às saídas."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
from pydantic import ValidationError

from sustemporal.contracts.experiment import Territorio
from sustemporal.duck import conectar
from sustemporal.errors import ConfigInvalida
from sustemporal.rules.catalog import CatalogoInvalido, carregar_regras
from sustemporal.rules.ingest import (
    carregar_registro,
    integridade_do_registro,
    ler_datasets,
    preparar_insumos_ingest,
)
from sustemporal.rules.insumos import InsumosAvaliacao, MetodoInvalido, politica_da_execucao
from sustemporal.rules.lote import avaliar_com_registro
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import MetodoId, PoliticaTemporal

__all__ = ["municipios_do_piloto", "validar_ingest"]

logger = logging.getLogger(__name__)


def municipios_do_piloto(config: RunConfig) -> frozenset[str]:
    """IBGE6 do território do piloto (contrato `Territorio`, UF igual à do piloto).

    Raises:
        ConfigInvalida: sem piloto, território ilegível, inválido ou de outra UF.
    """
    piloto = config.piloto
    if piloto is None:
        raise ConfigInvalida("validate_ingest_sem_piloto")
    caminho = Path(piloto.territorio)
    try:
        territorio = Territorio.model_validate(carregar_yaml(caminho))
    except (OSError, ValueError, ValidationError) as erro:
        raise ConfigInvalida(f"territorio_invalido caminho={caminho}") from erro
    if territorio.uf != piloto.uf:
        raise ConfigInvalida(
            f"territorio_de_outra_uf territorio={territorio.uf} piloto={piloto.uf}"
        )
    return frozenset(m.ibge6 for m in territorio.municipios)


def _politica(metodo: MetodoId, config: RunConfig, regras: list[RuleSpec]) -> PoliticaTemporal:
    do_metodo = config.model_copy(update={"metodos": (metodo,)})
    return politica_da_execucao(InsumosAvaliacao(), do_metodo, regras)


def _gravar_recorte(
    destino: Path, resultado: RunResult, municipios: frozenset[str], exclusoes: dict[str, int]
) -> None:
    conteudo = {
        "run_id": resultado.run_id,
        "municipios": sorted(municipios),
        "exclusoes": exclusoes,
    }
    caminho = destino / resultado.run_id / "recorte_territorial.json"
    caminho.write_text(json.dumps(conteudo, indent=2, sort_keys=True), encoding="utf-8")


def validar_ingest(pasta: Path, metodo: MetodoId, config: RunConfig, saida: Path) -> RunResult:
    """Confere a pasta e o registro antes de gravar qualquer coisa; depois avalia em lote.

    Raises:
        ConfigInvalida: catálogo, política, manifesto, território ou pasta do ingest inválidos.
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
    con = conectar(config.runtime)
    try:
        insumos = preparar_insumos_ingest(
            con, datasets, regras, (config, registro, municipios), saida / "entradas"
        )
    except (ValueError, duckdb.Error) as erro:
        raise ConfigInvalida(f"ingest_semanticamente_invalido detalhe={erro}") from erro
    finally:
        con.close()
    avaliacao = InsumosAvaliacao(
        auxiliares=insumos.auxiliares,
        cobertura=insumos.cobertura,
        integridade=integridade_do_registro(registro),
        politica=politica,
    )
    try:
        resultado = avaliar_com_registro(
            insumos.producao, regras, config, registro, saida, insumos=avaliacao
        )
    except ValueError as erro:
        raise ConfigInvalida(f"entrada_semanticamente_invalida detalhe={erro}") from erro
    _gravar_recorte(saida, resultado, municipios, insumos.exclusoes)
    return resultado
