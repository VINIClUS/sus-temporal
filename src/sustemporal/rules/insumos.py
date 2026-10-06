"""Insumos explícitos da avaliação de regras e política temporal da execução."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.gates import DIR_DECISOES
from sustemporal.runtime_info import RAIZ_DO_PACOTE
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sustemporal.contracts.artifacts import EstadoIntegridade
    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "METODOS_DE_VALIDACAO",
    "InsumosAvaliacao",
    "MetodoInvalido",
    "politica_da_execucao",
    "politica_padrao",
]

METODOS_DE_VALIDACAO = (MetodoId.M_TEMP, MetodoId.B_ATEND, MetodoId.B_PROC)
_BASE_DA_BASELINE = {
    MetodoId.B_ATEND: BaseTemporal.ATENDIMENTO,
    MetodoId.B_PROC: BaseTemporal.PROCESSAMENTO,
}


class MetodoInvalido(ValueError):
    """Método ou política fora de M_TEMP, B_ATEND e B_PROC."""


@dataclass(frozen=True)
class InsumosAvaliacao:
    """Conjuntos auxiliares, seleção por registro, cobertura, integridade e política explícitos.

    `selecoes` ausente: a seleção é derivada do `SnapshotSet` por correspondência exata.
    `politica` ausente: `config.politica_id` (em `diretorio_politicas`), senão a padrão do método.
    `identidade_adicional`: insumos fora dos `DatasetRef` que mudam o resultado (ex.: território);
    entram no `run_id` só quando não vazios, assim ids já emitidos continuam válidos.
    """

    auxiliares: tuple[DatasetRef, ...] = ()
    selecoes: DatasetRef | None = None
    cobertura: DatasetRef | None = None
    integridade: Mapping[str, EstadoIntegridade] = field(default_factory=dict)
    politica: PoliticaTemporal | None = None
    raiz_codigo: Path = RAIZ_DO_PACOTE
    diretorio_decisoes: Path = DIR_DECISOES
    diretorio_politicas: Path = DIRETORIO_POLITICAS
    identidade_adicional: Mapping[str, str] = field(default_factory=dict)


def _fontes_auxiliares(regras: list[RuleSpec]) -> list[FamiliaFonte]:
    fontes = {
        requisito.fonte
        for regra in regras
        for requisito in regra.requisitos_fonte
        if requisito.fonte is not FamiliaFonte.SIA_PA
    }
    return sorted(fontes)


def politica_padrao(metodo: MetodoId, regras: list[RuleSpec]) -> PoliticaTemporal:
    """Baselines usam a competência do próprio método; M_TEMP sem documento fica não resolvida.

    Raises:
        MetodoInvalido: método sem seleção temporal de regras.
    """
    if metodo is MetodoId.M_TEMP:
        return PoliticaTemporal(
            politica_id="m_temp_nao_resolvida",
            tipo=TipoPolitica.NAO_RESOLVIDA,
            metodo=metodo,
            criterios=(),
        )
    base = _BASE_DA_BASELINE.get(metodo)
    if base is None:
        raise MetodoInvalido(f"metodo_sem_validacao_por_regras metodo={metodo}")
    criterios = tuple(
        CriterioTemporal(fonte=fonte, base=base) for fonte in _fontes_auxiliares(regras)
    )
    return PoliticaTemporal(
        politica_id=f"{metodo.value.lower()}_exploratoria",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo=metodo,
        criterios=criterios,
    )


def _metodo_da_config(config: RunConfig) -> MetodoId | None:
    candidatos = [metodo for metodo in config.metodos if metodo in METODOS_DE_VALIDACAO]
    if len(candidatos) > 1:
        raise MetodoInvalido(f"config_com_varios_metodos metodos={candidatos}")
    return candidatos[0] if candidatos else None


def _politica_da_config(
    insumos: InsumosAvaliacao, config: RunConfig, regras: list[RuleSpec]
) -> PoliticaTemporal:
    metodo = _metodo_da_config(config)
    if config.politica_id is None:
        return politica_padrao(metodo or MetodoId.M_TEMP, regras)
    politica = carregar_politica(config.politica_id, insumos.diretorio_politicas)
    if metodo is not None and politica.metodo is not metodo:
        raise MetodoInvalido(
            f"politica_de_outro_metodo politica={politica.politica_id} "
            f"metodo={politica.metodo} config={metodo}"
        )
    return politica


def politica_da_execucao(
    insumos: InsumosAvaliacao, config: RunConfig, regras: list[RuleSpec]
) -> PoliticaTemporal:
    """Política única da execução, resolvida só aqui e repassada à seleção temporal.

    Ordem: `insumos.politica`; `config.politica_id` (`carregar_politica`); a padrão do método da
    configuração. `RuleSpec.politica_id` nunca escolhe a política.

    Raises:
        MetodoInvalido: política de método sem validação por regras ou configuração ambígua.
        ConfigInvalida: `config.politica_id` inexistente ou inválida.
    """
    politica = insumos.politica or _politica_da_config(insumos, config, regras)
    if politica.metodo not in METODOS_DE_VALIDACAO:
        raise MetodoInvalido(f"politica_de_metodo_invalido metodo={politica.metodo}")
    return politica
