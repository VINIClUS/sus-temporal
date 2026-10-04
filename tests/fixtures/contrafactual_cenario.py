"""Mundos SINTETICOS para a busca de contrafactuais: CNES PF reduzido, CNES ST e bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import (
    Confirmacao,
    DocRef,
    FamiliaFonte,
    OrigemDados,
    Proveniencia,
    ValorNormalizado,
)
from sustemporal.contracts.counterfactual import AlvoOperacao, OperationSpec
from sustemporal.contracts.explanation import (
    EstadoCobertura,
    Evidence,
    ExplanationBundle,
    Limitacao,
    TipoEvidencia,
)
from sustemporal.contracts.records import (
    DatasetRef,
    ProductionRecord,
    RowLocator,
    calcular_dataset_id,
)
from sustemporal.contracts.rules import (
    Aplicabilidade,
    EstadoAvaliacao,
    RuleEvaluation,
)
from sustemporal.contracts.temporal import BaseTemporal, EstadoSelecao, MetodoId, SelecaoVersao
from sustemporal.explanation.counterfactual_contexto import ContextoContrafactual
from sustemporal.hashing import hash_logico_linhas
from sustemporal.rules.catalog import carregar_esquema, carregar_regras
from tests.fixtures.regras_cenario import artefato, materializar, snapshot_vazio
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIA,
    COMPETENCIA,
    cenario_base,
    registro,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.rules import RuleSpec

__all__ = [
    "CBO_ALVO",
    "CBO_OUTRO",
    "CBO_TERCEIRO",
    "CNES",
    "Mundo",
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


def relogio() -> datetime:
    return _INSTANTE


@dataclass(frozen=True)
class Mundo:
    contexto: ContextoContrafactual
    bundle: ExplanationBundle
    arquivos: tuple[str, ...]


def _linhas_pf(pf: dict[str, int]) -> tuple[dict[str, object], ...]:
    base = {"artifact_id": ART_CNES, "competencia_arquivo": COMPETENCIA, "cnes": CNES}
    return tuple(base | {"cbo": cbo, "n_vinculos": n} for cbo, n in sorted(pf.items()) if n > 0)


def _gravar_st(raiz: Path, *, presente: bool) -> DatasetRef:
    colunas = [c.nome for c in carregar_esquema(_ST).colunas]
    cnes = ["7654321", CNES] if presente else ["7654321"]
    linhas = [{"competencia_arquivo": COMPETENCIA, "cnes": c, "artifact_id": ART_ST} for c in cnes]
    esquema = pa.schema([(c, pa.string()) for c in colunas])
    tabela = pa.Table.from_pylist([{c: linha.get(c) for c in colunas} for linha in linhas], esquema)
    caminho = raiz / "cnes_estabelecimento.parquet"
    pq.write_table(tabela, caminho)
    valores = [tuple(linha.get(c) for c in colunas) for linha in linhas]
    hash_logico = hash_logico_linhas(colunas, valores)
    return DatasetRef(
        dataset_id=calcular_dataset_id(_ST, hash_logico, (ART_ST,)),
        schema_id=_ST,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=(ART_ST,),
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture_contrafactual_sintetica",
    )


def _registro_contrato(indice: int, campos: dict[str, str | None]) -> ProductionRecord:
    return ProductionRecord(
        row_id=f"{ART_SIA}#{indice}",
        origem=RowLocator(artifact_id=ART_SIA, indice=indice),
        cnes=campos["cnes"],
        competencia_atendimento=campos["competencia_atendimento"],
        competencia_processamento=campos["competencia_processamento"],
        instrumento=ValorNormalizado(bruto=campos["instrumento"], valor=campos["instrumento"]),
        procedimento=campos["procedimento"],
        cbo=campos["cbo"],
    )


def _bundle(registro_alvo: ProductionRecord, pf: DatasetRef) -> ExplanationBundle:
    evidencia = Evidence(
        evidence_id="ev_ausencia_sintetica",
        tipo=TipoEvidencia.AUSENCIA_NA_FONTE,
        query_id="q_estab_cbo",
        sql_sha256="0" * 64,
        parametros={"cnes": CNES, "cbo": str(registro_alvo.cbo)},
        dataset_id=pf.dataset_id,
        hash_logico=pf.hash_logico,
        artifact_ids=(ART_CNES,),
        cobertura=EstadoCobertura.DISPONIVEL,
        integridade=EstadoIntegridade.OK,
        n_resultados=0,
    )
    selecao = SelecaoVersao(
        fonte=FamiliaFonte.CNES_PF,
        base=BaseTemporal.ATENDIMENTO,
        competencia_requerida=COMPETENCIA,
        estado=EstadoSelecao.SELECIONADA,
        artifact_ids=(ART_CNES,),
        motivo="selecao_sintetica",
    )
    avaliacao = RuleEvaluation(
        run_id="run_sintetico",
        row_id=registro_alvo.row_id,
        rule_id="ESTAB_CBO_CNES",
        versao="0.1.0",
        politica_id="b_atend_sintetica",
        metodo=MetodoId.B_ATEND,
        estado=EstadoAvaliacao.VIOLACAO,
        aplicabilidade=Aplicabilidade.APLICAVEL,
        insumos_completos=True,
        incompatibilidade_demonstrada=True,
        selecoes=(selecao,),
        evidence_ids=(evidencia.evidence_id,),
    )
    return ExplanationBundle(
        bundle_id="bundle_sintetico",
        run_id="run_sintetico",
        row_id=registro_alvo.row_id,
        registro=registro_alvo,
        avaliacoes=(avaliacao,),
        selecoes=(selecao,),
        evidencias=(evidencia,),
        prov_n="SINTETICO",
        prov_json_sha256="0" * 64,
        limitacoes=(
            Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA,
            Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL,
            Limitacao.DADOS_SINTETICOS,
        ),
    )


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
    pf: dict[str, int],
    st_presente: bool = True,
    outros: tuple[tuple[str, str], ...] = (),
    regras: tuple[RuleSpec, ...] | None = None,
    competencia_aberta: str | None = None,
) -> Mundo:
    """Registro 0 com o par (CNES, CBO_ALVO) ausente do PF; `outros` são (cbo, instrumento)."""
    demais = (
        registro(i, cbo=cbo, instrumento=instrumento)
        for i, (cbo, instrumento) in enumerate(outros, start=1)
    )
    registros = (registro(0, cbo=CBO_ALVO), *demais)
    regras = regras if regras is not None else tuple(carregar_regras())
    cenario = cenario_base(*registros)
    cenario = cenario.com(selecoes=cenario.selecoes + _selecoes_extras(cenario.selecoes, regras))
    auxiliares = dict(cenario.auxiliares) | {_PF: _linhas_pf(pf)}
    integridade = dict(cenario.integridade) | {ART_ST: EstadoIntegridade.OK}
    cenario = cenario.com(
        auxiliares=auxiliares,
        integridade=integridade,
        artefatos_auxiliar={_PF: (ART_CNES,)},
    )
    dataset, insumos = materializar(cenario, raiz / "entrada")
    st = _gravar_st(raiz / "entrada", presente=st_presente)
    contexto = ContextoContrafactual(
        dataset=dataset,
        snapshots=snapshot_vazio(),
        regras=regras,
        insumos=insumos,
        cadastros=(st,),
        competencia_aberta_cnes=competencia_aberta,
        relogio=relogio,
    )
    pf_ref = next(d for d in insumos.auxiliares if d.schema_id == _PF)
    alvo = _registro_contrato(0, registros[0])
    arquivos = tuple(sorted(str(p) for p in (raiz / "entrada").iterdir()))
    return Mundo(contexto=contexto, bundle=_bundle(alvo, pf_ref), arquivos=arquivos)


def _docref_sintetica(oficial: bool) -> DocRef:
    return DocRef(
        doc_id="SINTETICO_DOC_OPERACAO",
        titulo="Documento SINTETICO de teste; não é fonte",
        estado="PENDENTE",
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
