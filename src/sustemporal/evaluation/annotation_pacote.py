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

from sustemporal.contracts import AnnotationSample, ConclusaoCaso, FamiliaRegra
from sustemporal.duck import identificador_seguro
from sustemporal.errors import ConfigInvalida

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import duckdb

    from sustemporal.contracts import DatasetRef

__all__ = [
    "COLUNAS_PACOTE",
    "FORMULARIO",
    "FORMULARIO_VERSAO",
    "carregar_mapa",
    "casos_do_pacote",
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
FORMULARIO: dict[str, object] = {
    "versao": FORMULARIO_VERSAO,
    "conclusoes": [c.value for c in ConclusaoCaso],
    "familias": [f.value for f in FamiliaRegra],
    "familias_multiplas": True,
    "campos": ["caso_id", "avaliador", "conclusao", "familias", "evidencias", "minutos"],
    "instrucoes": (
        "Registre todas as incompatibilidades cadastrais sustentadas pelas fontes consultadas. "
        "Use CAUSA_INDETERMINADA quando as fontes consultadas não sustentam nenhuma causa e "
        "EVIDENCIA_INSUFICIENTE quando faltam fontes para decidir. Não force causa única. "
        "O pacote não traz saídas do motor de regras e elas não devem ser consultadas."
    ),
}


def _valor(valor: object) -> object:
    return str(valor) if isinstance(valor, Decimal) else valor


def casos_do_pacote(
    con: duckdb.DuckDBPyConnection,
    registros: DatasetRef,
    labels: DatasetRef,
    ordem: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    """Linhas do pacote na ordem (caso_id, row_id) dada, só com colunas da allowlist."""
    descricao = con.execute(
        "DESCRIBE SELECT * FROM read_parquet($c)", {"c": registros.caminho}
    ).fetchall()
    fisicas = {str(linha[0]) for linha in descricao}
    colunas = [c for c in COLUNAS_PACOTE if c in fisicas]
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
            {"formulario_versao": amostra.formulario_versao, "casos": casos},
        )
    _gravar_json(out / "pacote" / "formulario.json", FORMULARIO)
    _gravar_json(out / "privado" / "mapa_casos.json", dict(mapa))
    _gravar_json(out / "privado" / "estratos.json", dict(estrato_por_row))
    _gravar_json(out / "amostra.json", amostra.model_dump(mode="json"))
    logger.info(
        "pacote_anotacao_gravado amostra=%s casos=%d treino=%d destino=%s",
        amostra.sample_id,
        len(amostra.casos),
        len(amostra.casos_treino),
        out,
    )


def carregar_mapa(out: Path) -> dict[str, str]:
    """Mapa privado caso_id → row_id gravado fora do pacote cego."""
    dados = json.loads((out / "privado" / "mapa_casos.json").read_text(encoding="utf-8"))
    return {str(caso): str(row_id) for caso, row_id in dados.items()}
