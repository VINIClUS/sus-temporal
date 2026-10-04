"""Carga e validação do catálogo formal de regras (`catalog/rules/**/*.yaml`) e do SQL associado."""

from __future__ import annotations

import hashlib
import logging
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from sustemporal.contracts.base import FamiliaFonte, hash_canonico
from sustemporal.contracts.records import EsquemaCanonico
from sustemporal.contracts.rules import (
    CatalogoFamilias,
    EstadoRegra,
    FamiliaRegra,
    RequisitoFonte,
    RuleSpec,
)
from sustemporal.yamlio import carregar_yaml

__all__ = [
    "CAMPOS_DO_PREDICADO",
    "CATALOGO_FAMILIAS",
    "CATALOGO_REGRAS",
    "DIR_ESQUEMAS",
    "FAMILIAS_COM_SQL",
    "MAPA_INSTRUMENTO_REGISTRO",
    "SQL_AVALIACAO",
    "CatalogoInvalido",
    "carregar_esquema",
    "carregar_regras",
    "catalogo_sha256",
    "requisito_auxiliar",
    "sql_da_familia",
    "sql_de_avaliacao",
    "sql_sha256",
]

logger = logging.getLogger(__name__)

_RAIZ = Path(__file__).resolve().parents[3]
CATALOGO_REGRAS = _RAIZ / "catalog" / "rules"
CATALOGO_FAMILIAS = _RAIZ / "catalog" / "familias.yaml"
DIR_ESQUEMAS = _RAIZ / "catalog" / "schemas"
_ESQUEMA_REGISTRO = "sia_pa.v1"

FAMILIAS_COM_SQL: dict[FamiliaRegra, str] = {
    FamiliaRegra.PROCEDIMENTO_CBO: "procedimento_cbo.sql",
    FamiliaRegra.ESTABELECIMENTO_CBO: "estabelecimento_cbo.sql",
    FamiliaRegra.INSTRUMENTO_REGISTRO: "instrumento_registro.sql",
    FamiliaRegra.VIGENCIA_PROCEDIMENTO: "vigencia_procedimento.sql",
}

SQL_AVALIACAO = "avaliar.sql"
# Colunas do registro comparadas pelo predicado de cada família (model.md §4).
CAMPOS_DO_PREDICADO: dict[FamiliaRegra, frozenset[str]] = {
    FamiliaRegra.PROCEDIMENTO_CBO: frozenset({"instrumento", "procedimento", "cbo"}),
    FamiliaRegra.ESTABELECIMENTO_CBO: frozenset({"instrumento", "cnes", "cbo"}),
    FamiliaRegra.INSTRUMENTO_REGISTRO: frozenset({"instrumento", "procedimento"}),
    FamiliaRegra.VIGENCIA_PROCEDIMENTO: frozenset({"instrumento", "procedimento"}),
}
# PA_DOCORIG → CO_REGISTRO: INFERIDA dos rótulos (catalog/familias.yaml); A_CONFIRMAR.
MAPA_INSTRUMENTO_REGISTRO: dict[str, str] = {
    "C": "01",
    "I": "02",
    "P": "06",
    "S": "07",
    "A": "08",
    "B": "09",
}


class CatalogoInvalido(ValueError):
    """Regra do catálogo inválida ou incoerente com famílias, esquemas ou SQL."""


def _texto_sql(nome: str) -> str:
    return resources.files("sustemporal.rules").joinpath("sql", nome).read_text(encoding="utf-8")


def sql_de_avaliacao() -> str:
    """Modelo SQL comum da avaliação (model.md §3)."""
    return _texto_sql(SQL_AVALIACAO)


def sql_da_familia(familia: FamiliaRegra) -> str:
    """Texto SQL parametrizado do predicado da família.

    Raises:
        CatalogoInvalido: família sem SQL implementado.
    """
    nome = FAMILIAS_COM_SQL.get(familia)
    if nome is None:
        raise CatalogoInvalido(f"familia_sem_sql familia={familia}")
    return _texto_sql(nome)


def sql_sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def carregar_esquema(schema_id: str, diretorio: Path = DIR_ESQUEMAS) -> EsquemaCanonico:
    """Esquema canônico `nome.vN` lido de `catalog/schemas/nome.yaml`.

    Raises:
        CatalogoInvalido: arquivo ausente ou esquema com outro identificador.
    """
    caminho = diretorio / f"{schema_id.rsplit('.', 1)[0]}.yaml"
    if not caminho.is_file():
        raise CatalogoInvalido(f"esquema_ausente schema_id={schema_id}")
    esquema = EsquemaCanonico.model_validate(carregar_yaml(caminho))
    if esquema.schema_id != schema_id:
        raise CatalogoInvalido(f"esquema_divergente esperado={schema_id} lido={esquema.schema_id}")
    return esquema


def requisito_auxiliar(regra: RuleSpec) -> RequisitoFonte:
    """Única fonte auxiliar (≠ SIA_PA) exigida pela regra.

    Raises:
        CatalogoInvalido: nenhuma ou mais de uma fonte auxiliar.
    """
    auxiliares = [r for r in regra.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA]
    if len(auxiliares) != 1:
        raise CatalogoInvalido(f"regra_exige_uma_fonte_auxiliar regra={regra.rule_id}")
    return auxiliares[0]


def _colunas(schema_id: str, diretorio: Path) -> set[str]:
    return {coluna.nome for coluna in carregar_esquema(schema_id, diretorio).colunas}


def _validar_campos(regra: RuleSpec, diretorio: Path) -> None:
    faltantes = set(regra.campos_necessarios) - _colunas(_ESQUEMA_REGISTRO, diretorio)
    for requisito in regra.requisitos_fonte:
        faltantes |= set(requisito.campos) - _colunas(requisito.schema_id, diretorio)
    if faltantes:
        raise CatalogoInvalido(
            f"regra_com_campo_fora_do_esquema regra={regra.rule_id} campos={sorted(faltantes)}"
        )
    if not CAMPOS_DO_PREDICADO.get(regra.familia, frozenset()) <= set(regra.campos_necessarios):
        raise CatalogoInvalido(f"regra_sem_campos_do_predicado regra={regra.rule_id}")


def _validar_familia(regra: RuleSpec, familias: CatalogoFamilias) -> None:
    candidatas = {entrada.familia: entrada for entrada in familias.familias}
    entrada = candidatas.get(regra.familia)
    if entrada is None:
        raise CatalogoInvalido(f"regra_de_familia_fora_do_catalogo regra={regra.rule_id}")
    exigidas = {(r.fonte, r.schema_id) for r in entrada.requisitos_fonte}
    if {(r.fonte, r.schema_id) for r in regra.requisitos_fonte} != exigidas:
        raise CatalogoInvalido(f"regra_com_fontes_diferentes_da_familia regra={regra.rule_id}")
    decididas = {EstadoRegra.APROVADA_G0, EstadoRegra.CONGELADA}
    if regra.estado in decididas and entrada.estado not in decididas:
        raise CatalogoInvalido(f"regra_com_estado_acima_da_familia regra={regra.rule_id}")


def _carregar_regra(caminho: Path) -> RuleSpec:
    try:
        return RuleSpec.model_validate(carregar_yaml(caminho))
    except (ValidationError, ValueError) as erro:
        raise CatalogoInvalido(f"regra_invalida arquivo={caminho.name} erro={erro}") from erro


def carregar_regras(
    raiz: Path = CATALOGO_REGRAS,
    *,
    familias: Path = CATALOGO_FAMILIAS,
    esquemas: Path = DIR_ESQUEMAS,
) -> list[RuleSpec]:
    """Regras do catálogo, ordenadas por `rule_id`, validadas contra famílias, esquemas e SQL.

    Raises:
        CatalogoInvalido: regra inválida, repetida ou incoerente.
    """
    catalogo = CatalogoFamilias.model_validate(carregar_yaml(familias))
    regras = [_carregar_regra(caminho) for caminho in sorted(raiz.rglob("*.yaml"))]
    ids = [regra.rule_id for regra in regras]
    if len(set(ids)) != len(ids):
        raise CatalogoInvalido("regras_repetidas_no_catalogo")
    for regra in regras:
        _validar_familia(regra, catalogo)
        _validar_campos(regra, esquemas)
        requisito_auxiliar(regra)
        sql_da_familia(regra.familia)
    logger.info("catalogo_regras_carregado regras=%d raiz=%s", len(regras), raiz)
    return sorted(regras, key=lambda regra: regra.rule_id)


def catalogo_sha256(regras: list[RuleSpec]) -> str:
    """Hash canônico das regras e do SQL de suas famílias."""
    conteudo = [
        {
            "regra": regra.model_dump(mode="json"),
            "sql": sql_sha256(sql_de_avaliacao() + sql_da_familia(regra.familia)),
        }
        for regra in sorted(regras, key=lambda regra: regra.rule_id)
    ]
    return hash_canonico(conteudo)
