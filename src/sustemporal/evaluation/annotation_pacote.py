"""Pacote cego dos avaliadores, formulário versionado e mapa privado de casos (T12).

O pacote só tem as colunas da allowlist `COLUNAS_PACOTE`, o rótulo oficial e um `caso_id`
pseudônimo em ordem embaralhada; row_id, artefato, estrato e qualquer coluna fora da allowlist
(inclusive colunas estranhas ao esquema) ficam fora. O mapa caso_id → row_id fica em `privado/`.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from sustemporal.contracts import AnnotationSample, MapaCasos, hash_canonico
from sustemporal.duck import identificador_seguro
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import DatasetRef

__all__ = [
    "COLUNAS_PACOTE",
    "CONCLUSOES_POR_FORMULARIO",
    "FAMILIAS_POR_FORMULARIO",
    "FORMULARIO_VERSAO",
    "INSTRUCOES_POR_FORMULARIO",
    "carregar_mapa",
    "casos_do_pacote",
    "formulario",
    "gravar_saidas",
]

logger = logging.getLogger(__name__)

FORMULARIO_VERSAO = "anotacao_formulario.v1"
COLUNAS_PACOTE = (
    "cnes",
    "municipio_estabelecimento",
    "tipo_unidade",
    "pa_gestao",
    "pa_condic",
    "pa_regct",
    "pa_incout",
    "pa_incurg",
    "pa_srv_c",
    "competencia_processamento",
    "competencia_atendimento",
    "procedimento",
    "instrumento",
    "cbo",
    "pa_tpfin",
    "pa_subfin",
    "pa_nivcpl",
    "cid_principal",
    "cid_secundario",
    "cid_causas_associadas",
    "carater_atendimento",
    "idade",
    "idade_unidade",
    "sexo",
    "quantidade_apresentada",
    "quantidade_aprovada",
    "valor_apresentado",
    "valor_aprovado",
    "pa_codoco",
    "pa_flqt",
    "pa_fler",
    "pa_flidade",
)
CONCLUSOES_POR_FORMULARIO: dict[str, tuple[str, ...]] = {
    FORMULARIO_VERSAO: (
        "INCOMPATIBILIDADE_IDENTIFICADA",
        "CAUSA_FORA_DE_ESCOPO_DOCUMENTADA",
        "CAUSA_INDETERMINADA",
        "EVIDENCIA_INSUFICIENTE",
    ),
}
FAMILIAS_POR_FORMULARIO: dict[str, tuple[str, ...]] = {
    FORMULARIO_VERSAO: (
        "PROCEDIMENTO_CBO",
        "ESTABELECIMENTO_CBO",
        "INSTRUMENTO_REGISTRO",
        "VIGENCIA_PROCEDIMENTO",
        "SERVICO_CLASSIFICACAO",
        "HABILITACAO",
        "CID",
        "IDADE",
        "SEXO",
        "QUANTIDADE_MAXIMA",
    ),
}
INSTRUCOES_POR_FORMULARIO: dict[str, str] = {
    FORMULARIO_VERSAO: (
        "Registre todas as incompatibilidades cadastrais sustentadas pelas fontes consultadas. "
        "Use CAUSA_INDETERMINADA quando as fontes consultadas não sustentam nenhuma causa e "
        "EVIDENCIA_INSUFICIENTE quando faltam fontes para decidir. Não force causa única. "
        "Copie o sample_id do cabeçalho de casos.json no lote de respostas. "
        "O pacote não traz saídas do motor de regras e elas não devem ser consultadas."
    ),
}


def formulario(versao: str) -> dict[str, object]:
    """Formulário montado só com dados congelados da versão, nunca com enums correntes.

    Raises:
        FalhaOperacionalErro: versão de formulário desconhecida.
    """
    if versao not in CONCLUSOES_POR_FORMULARIO or versao not in FAMILIAS_POR_FORMULARIO:
        raise FalhaOperacionalErro(f"formulario_desconhecido versao={versao}")
    return {
        "versao": versao,
        "conclusoes": list(CONCLUSOES_POR_FORMULARIO[versao]),
        "familias": list(FAMILIAS_POR_FORMULARIO[versao]),
        "familias_multiplas": True,
        "campos": [
            "sample_id",
            "formulario_versao",
            "avaliador",
            "caso_id",
            "conclusao",
            "familias",
            "evidencias",
            "minutos",
        ],
        "instrucoes": INSTRUCOES_POR_FORMULARIO[versao],
    }


def _valor(valor: object) -> object:
    return str(valor) if isinstance(valor, Decimal) else valor


def casos_do_pacote(
    con: duckdb.DuckDBPyConnection,
    registros: DatasetRef,
    labels: DatasetRef,
    ordem: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    """Linhas do pacote na ordem (caso_id, row_id) dada, só com colunas da allowlist.

    Raises:
        FalhaOperacionalErro: Parquet sem alguma coluna da allowlist (leiaute incompatível).
    """
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": registros.caminho}
    ).fetchall()
    fisicas = {str(linha[0]) for linha in descricao}
    ausentes = [c for c in COLUNAS_PACOTE if c not in fisicas]
    if ausentes:
        raise FalhaOperacionalErro(
            f"anotacao_leiaute_incompativel dataset={registros.dataset_id} "
            f"ausentes={','.join(ausentes)}"
        )
    colunas = list(COLUNAS_PACOTE)
    projecao = ", ".join(f"p.{identificador_seguro(c, colunas)}" for c in colunas)
    linhas = con.execute(
        f"SELECT p.row_id, {projecao}, r.rotulo FROM read_parquet($registros) p "  # noqa: S608
        "JOIN read_parquet($rotulos) r USING (row_id) WHERE list_contains($ids, p.row_id)",
        {
            "registros": registros.caminho,
            "rotulos": labels.caminho,
            "ids": [row_id for _, row_id in ordem],
        },
    ).fetchall()
    por_row = {
        str(linha[0]): dict(zip((*colunas, "rotulo"), map(_valor, linha[1:]), strict=True))
        for linha in linhas
    }
    return [{"caso_id": caso_id, **por_row[row_id]} for caso_id, row_id in ordem]


def _gravar_json(caminho: Path, conteudo: object) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.tmp")
    temporario.write_text(
        json.dumps(conteudo, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporario.replace(caminho)


def _exigir_destino_livre(out: Path, amostra: AnnotationSample) -> None:
    existente = out / "amostra.json"
    if not existente.exists():
        return
    anterior = AnnotationSample.model_validate_json(existente.read_text(encoding="utf-8"))
    if anterior != amostra:
        raise ConfigInvalida(
            f"pacote_ja_exportado destino={out} existente={anterior.sample_id} "
            f"novo={amostra.sample_id}"
        )


def gravar_saidas(
    out: Path,
    amostra: AnnotationSample,
    pacotes: Mapping[str, list[dict[str, object]]],
    mapa: Mapping[str, str],
    estrato_por_row: Mapping[str, str],
) -> None:
    """Grava pacote cego (casos, treino, formulário), mapa privado e o AnnotationSample.

    Raises:
        ConfigInvalida: já existe amostra diferente em `out` (nunca é sobrescrita).
    """
    _exigir_destino_livre(out, amostra)
    for nome, casos in pacotes.items():
        _gravar_json(
            out / "pacote" / f"{nome}.json",
            {
                "sample_id": amostra.sample_id,
                "formulario_versao": amostra.formulario_versao,
                "casos": casos,
            },
        )
    _gravar_json(out / "pacote" / "formulario.json", formulario(amostra.formulario_versao))
    privado = MapaCasos(
        sample_id=amostra.sample_id, sha256=hash_canonico(dict(mapa)), casos=dict(mapa)
    )
    _gravar_json(out / "privado" / "mapa_casos.json", privado.model_dump(mode="json"))
    _gravar_json(out / "privado" / "estratos.json", dict(estrato_por_row))
    _gravar_json(out / "amostra.json", amostra.model_dump(mode="json"))
    logger.info(
        "pacote_anotacao_gravado amostra=%s casos=%d treino=%d destino=%s",
        amostra.sample_id,
        len(amostra.casos),
        len(amostra.casos_treino),
        out,
    )


def carregar_mapa(out: Path) -> MapaCasos:
    """Mapa privado caso_id → row_id gravado fora do pacote cego, com sample_id e sha256."""
    caminho = out / "privado" / "mapa_casos.json"
    return MapaCasos.model_validate_json(caminho.read_text(encoding="utf-8"))
