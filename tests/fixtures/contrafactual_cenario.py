"""Mundos SINTETICOS para a busca de contrafactuais: CNES PF reduzido, CNES ST e bundle."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import (
    Confirmacao,
    DocRef,
    EstadoDocumento,
    OrigemDados,
    Proveniencia,
)
from sustemporal.contracts.counterfactual import AlvoOperacao, OperationSpec
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.explanation.counterfactual_contexto import ContextoContrafactual
from sustemporal.hashing import hash_logico_linhas
from sustemporal.rules.catalog import carregar_esquema, carregar_regras
from tests.fixtures.contrafactual_bundle import bundle_sintetico, registro_contrato
from tests.fixtures.regras_cenario import artefato, materializar, reemitir, snapshot_vazio
from tests.fixtures.regras_exemplos import ART_CNES, COMPETENCIA, cenario_base, registro

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sustemporal.contracts import ExplanationBundle
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.rules.insumos import InsumosAvaliacao

__all__ = [
    "ART_ST",
    "CBO_ALVO",
    "CBO_OUTRO",
    "CBO_TERCEIRO",
    "CNES",
    "Mundo",
    "OpcoesST",
    "gravar_st",
    "montar",
    "operacao",
    "relogio",
]

CNES = "1234567"
CBO_ALVO = "223505"
CBO_OUTRO = "225125"
CBO_TERCEIRO = "322205"
ART_ST = artefato(4)
_ST = "cnes_estabelecimento.v1"
_PF = "cnes_estab_cbo.v1"
_INSTANTE = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
_SHA256_SINTETICO = hashlib.sha256(b"documento SINTETICO de teste").hexdigest()


def relogio() -> datetime:
    return _INSTANTE


@dataclass(frozen=True)
class Mundo:
    contexto: ContextoContrafactual
    bundle: ExplanationBundle
    arquivos: tuple[str, ...]


@dataclass(frozen=True)
class OpcoesST:
    """CNES ST SINTETICO: presença do CNES do registro, linhas extras, tipos e integridade."""

    presente: bool = True
    extras: tuple[dict[str, str], ...] = ()
    tipos: dict[str, pa.DataType] | None = None
    integridade: EstadoIntegridade | None = EstadoIntegridade.OK


def _linhas_pf(pf: dict[str, int | tuple[int, ...]]) -> tuple[dict[str, object], ...]:
    """Contagens por CBO; uma tupla distribui o total do par em linhas repetidas."""
    base = {"artifact_id": ART_CNES, "competencia_arquivo": COMPETENCIA, "cnes": CNES}
    linhas = []
    for cbo, valor in sorted(pf.items()):
        partes = valor if isinstance(valor, tuple) else (valor,)
        linhas += [base | {"cbo": cbo, "n_vinculos": n} for n in partes if n > 0]
    return tuple(linhas)


def gravar_st(raiz: Path, opcoes: OpcoesST) -> DatasetRef:
    colunas = [c.nome for c in carregar_esquema(_ST).colunas]
    cnes = ["7654321", CNES] if opcoes.presente else ["7654321"]
    linhas = [{"competencia_arquivo": COMPETENCIA, "cnes": c, "artifact_id": ART_ST} for c in cnes]
    linhas += [dict(extra) for extra in opcoes.extras]
    tipos = opcoes.tipos or {}
    esquema = pa.schema([(c, tipos.get(c, pa.string())) for c in colunas])
    tabela = pa.Table.from_pylist([{c: linha.get(c) for c in colunas} for linha in linhas], esquema)
    caminho = raiz / "cnes_estabelecimento.parquet"
    pq.write_table(tabela, caminho)
    lidas = pq.read_table(caminho)
    valores = [tuple(lidas.column(c)[i].as_py() for c in colunas) for i in range(lidas.num_rows)]
    hash_logico = hash_logico_linhas(colunas, valores)
    artefatos = tuple(sorted({str(linha["artifact_id"]) for linha in linhas}))
    return DatasetRef(
        dataset_id=calcular_dataset_id(_ST, hash_logico, artefatos),
        schema_id=_ST,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture_contrafactual_sintetica",
    )


def _pf_int32(insumos: InsumosAvaliacao) -> InsumosAvaliacao:
    """Regrava o CNES PF com `n_vinculos` INTEGER (inteiro aceito pelo motor)."""
    pf = next(d for d in insumos.auxiliares if d.schema_id == _PF)
    tabela = pq.read_table(pf.caminho)
    indice = tabela.schema.get_field_index("n_vinculos")
    tabela = tabela.set_column(indice, "n_vinculos", tabela.column(indice).cast(pa.int32()))
    pq.write_table(tabela, pf.caminho)
    novo = reemitir(pf)
    auxiliares = tuple(novo if d.schema_id == _PF else d for d in insumos.auxiliares)
    return replace(insumos, auxiliares=auxiliares)


def _selecoes_extras(
    selecoes: tuple[dict[str, str | None], ...], regras: tuple[RuleSpec, ...]
) -> tuple[dict[str, str | None], ...]:
    """Regras derivadas de ESTAB_CBO_CNES nos testes recebem a mesma seleção do CNES PF."""
    conhecidas = {str(s["rule_id"]) for s in selecoes}
    novas = [r.rule_id for r in regras if r.rule_id not in conhecidas]
    modelo = [s for s in selecoes if s["rule_id"] == "ESTAB_CBO_CNES"]
    return tuple(s | {"rule_id": rule_id} for rule_id in novas for s in modelo)


def montar(
    raiz: Path,
    *,
    pf: dict[str, int | tuple[int, ...]],
    st_presente: bool = True,
    st: OpcoesST | None = None,
    outros: tuple[tuple[str, str], ...] = (),
    regras: tuple[RuleSpec, ...] | None = None,
    competencia_aberta: str | None = None,
    agora: Callable[[], datetime] = relogio,
    pf_int32: bool = False,
    alvos: tuple[tuple[str, str], ...] = (("ESTAB_CBO_CNES", COMPETENCIA),),
) -> Mundo:
    """Registro 0 com o par (CNES, CBO_ALVO) ausente do PF; `outros` são (cbo, instrumento)."""
    opcoes_st = st or OpcoesST(presente=st_presente)
    demais = (
        registro(i, cbo=cbo, instrumento=instrumento)
        for i, (cbo, instrumento) in enumerate(outros, start=1)
    )
    registros = (registro(0, cbo=CBO_ALVO), *demais)
    regras = regras if regras is not None else tuple(carregar_regras())
    cenario = cenario_base(*registros)
    integridade = dict(cenario.integridade)
    if opcoes_st.integridade is not None:
        integridade[ART_ST] = opcoes_st.integridade
    cenario = cenario.com(
        selecoes=cenario.selecoes + _selecoes_extras(cenario.selecoes, regras),
        auxiliares=dict(cenario.auxiliares) | {_PF: _linhas_pf(pf)},
        integridade=integridade,
        artefatos_auxiliar={_PF: (ART_CNES,)},
    )
    dataset, insumos = materializar(cenario, raiz / "entrada")
    if pf_int32:
        insumos = _pf_int32(insumos)
    contexto = ContextoContrafactual(
        dataset=dataset,
        snapshots=snapshot_vazio(),
        regras=regras,
        insumos=insumos,
        cadastros=(gravar_st(raiz / "entrada", opcoes_st),),
        competencia_aberta_cnes=competencia_aberta,
        relogio=agora,
    )
    pf_ref = next(d for d in insumos.auxiliares if d.schema_id == _PF)
    bundle = bundle_sintetico(registro_contrato(0, registros[0]), pf_ref, alvos)
    arquivos = tuple(sorted(str(p) for p in (raiz / "entrada").iterdir()))
    return Mundo(contexto=contexto, bundle=bundle, arquivos=arquivos)


def _docref_sintetica(oficial: bool) -> DocRef:
    """Oficial: documento SINTETICO tratado como lido e preservado (cópia + SHA-256)."""
    return DocRef(
        doc_id="SINTETICO_DOC_OPERACAO",
        titulo="Documento SINTETICO de teste; não é fonte",
        estado=EstadoDocumento.PRESERVADO if oficial else EstadoDocumento.PENDENTE,
        sha256=_SHA256_SINTETICO if oficial else None,
        proveniencia=Proveniencia.OFICIAL_DOCUMENTO if oficial else Proveniencia.SECUNDARIA,
        confirmacao=Confirmacao.CONFIRMADO if oficial else Confirmacao.A_CONFIRMAR,
    )


_ALVOS = {
    "INCLUIR_CBO_NO_ESTABELECIMENTO": (_PF, ("cnes", "cbo", "n_vinculos")),
    "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO": (_PF, ("cnes", "cbo", "n_vinculos")),
    "CADASTRAR_ESTABELECIMENTO_NO_CNES": (_ST, ("cnes",)),
}
_PRECONDICOES = {
    "INCLUIR_CBO_NO_ESTABELECIMENTO": ("ESTABELECIMENTO_NO_CNES_ST",),
    "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO": (
        "ESTABELECIMENTO_NO_CNES_ST",
        "CBO_ORIGEM_COM_VINCULO",
    ),
    "CADASTRAR_ESTABELECIMENTO_NO_CNES": ("ESTABELECIMENTO_AUSENTE_NO_CNES_ST",),
}
_DEPENDENCIAS = {
    "INCLUIR_CBO_NO_ESTABELECIMENTO": ("CADASTRAR_ESTABELECIMENTO_NO_CNES",),
    "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO": ("CADASTRAR_ESTABELECIMENTO_NO_CNES",),
}


def operacao(
    op_id: str,
    custo: int,
    *,
    autoridade: str = "DESCONHECIDA",
    governanca: str = "DESCONHECIDA",
    competencias: str = "QUALQUER_HIPOTETICA",
) -> OperationSpec:
    """Operação SINTETICA do catálogo fechado com custo e governança escolhidos pelo teste."""
    schema_id, colunas = _ALVOS[op_id]
    return OperationSpec(
        op_id=op_id,
        descricao="operação SINTETICA de teste",
        autoridade=autoridade,
        governanca=governanca,
        verdade_factual_exigida="fato SINTETICO exigido",
        alvo=AlvoOperacao(schema_id=schema_id, colunas=colunas),
        competencias_permitidas=competencias,
        alcance="SINTETICO",
        custo=custo,
        precondicoes=_PRECONDICOES[op_id],
        depende_de=_DEPENDENCIAS.get(op_id, ()),
        referencia=_docref_sintetica(governanca == "MUNICIPAL_DOCUMENTADA"),
    )
