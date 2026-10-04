"""Registro temporal, regras e registros SINTETICO para os testes de seleção (T06)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import (
    ArtifactObservation,
    ArtifactVersion,
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    ResultadoTentativa,
    calcular_artifact_id,
)
from sustemporal.contracts.base import (
    CanalPublicacao,
    DocRef,
    EstadoDocumento,
    FamiliaFonte,
    Proveniencia,
    ValorNormalizado,
)
from sustemporal.contracts.records import ProductionRecord, RowLocator
from sustemporal.contracts.rules import (
    EstadoRegra,
    FamiliaRegra,
    RequisitoFonte,
    RuleSpec,
    UnidadeAvaliacao,
)

if TYPE_CHECKING:
    from sustemporal.contracts.temporal import CriterioTemporal

T0 = datetime(2026, 1, 1, tzinfo=UTC)
ARTEFATO_PA = f"art_{'9' * 64}"
_contador = itertools.count()
_SEM_CONTEUDO = {
    ResultadoTentativa.NAO_ENCONTRADO,
    ResultadoTentativa.FALHA_TRANSPORTE,
    ResultadoTentativa.INTERROMPIDO,
    ResultadoTentativa.RECUSADO_OFFLINE,
    ResultadoTentativa.FALHA_ARMAZENAMENTO,
}


def instante(dias: int) -> datetime:
    return T0 + timedelta(days=dias)


def _chave(
    fonte: FamiliaFonte, competencia: str, parte: str | None, uf: str | None
) -> ChaveArtefato:
    return ChaveArtefato(
        fonte=fonte,
        uf=uf,
        competencia_arquivo=competencia,
        parte=parte,
        canal=CanalPublicacao.ATUAL,
        nome_original=f"{fonte.value}_{competencia}{parte or ''}.dbc",
    )


def observar(
    fonte: FamiliaFonte,
    competencia: str,
    conteudo: str,
    dias: int,
    *,
    resultado: ResultadoTentativa = ResultadoTentativa.OBTIDO,
    integridade: EstadoIntegridade = EstadoIntegridade.OK,
    parte: str | None = None,
    uf: str | None = "SP",
    integridade_observada: EstadoIntegridade | None = None,
) -> tuple[ArtifactObservation, ArtifactVersion | None]:
    """Uma observação e, se houve bytes, a versão de conteúdo `conteudo` (sha sintético)."""
    chave = _chave(fonte, competencia, parte, uf)
    sha256 = conteudo.encode().hex().ljust(64, "0")[:64]
    versao = None
    campos: dict[str, object] = {}
    if resultado not in _SEM_CONTEUDO:
        artifact_id = calcular_artifact_id(chave, sha256)
        versao = ArtifactVersion(
            artifact_id=artifact_id,
            chave=chave,
            localizador=f"file:///sintetico/{chave.nome_original}",
            sha256=sha256,
            tamanho_bytes=10,
            formato=FormatoArquivo.DBC,
            caminho_conteudo=f"sha256/{sha256[:2]}/{sha256}.dbc",
            integridade=integridade,
        )
        campos = {"artifact_id": artifact_id, "sha256_obtido": sha256, "bytes_recebidos": 10}
        campos["integridade"] = integridade_observada
    observacao = ArtifactObservation(
        observation_id=f"obs_{next(_contador):032x}",
        chave=chave,
        request_sha256="c" * 64,
        observado_em=instante(dias),
        resultado=resultado,
        ferramenta="sintetico",
        **campos,
    )
    return observacao, versao


def docref(pendente: bool = True) -> DocRef:
    return DocRef(
        doc_id="W3",
        titulo="Manual do BPA (SINTETICO no teste)",
        estado=EstadoDocumento.PENDENTE if pendente else EstadoDocumento.PRESERVADO,
        sha256=None if pendente else "d" * 64,
        proveniencia=Proveniencia.OFICIAL_VISTO_EM_BUSCA,
    )


def regra(
    fonte: FamiliaFonte = FamiliaFonte.CNES_PF,
    rule_id: str = "ESTAB_CBO_CNES",
    *,
    criterios_temporais: tuple[CriterioTemporal, ...] = (),
) -> RuleSpec:
    return RuleSpec(
        rule_id=rule_id,
        familia=FamiliaRegra.ESTABELECIMENTO_CBO,
        versao="0.1.0",
        estado=EstadoRegra.CANDIDATA_PRE_G0,
        descricao="SINTETICO",
        instrumentos=("BPA_C",),
        condicao_aplicabilidade="instrumento_bpa_c",
        unidade_avaliacao=UnidadeAvaliacao.ESTABELECIMENTO_CBO,
        campos_necessarios=("cnes", "cbo"),
        requisitos_fonte=(
            RequisitoFonte(fonte=FamiliaFonte.SIA_PA, schema_id="sia_pa.v1", campos=("cbo",)),
            RequisitoFonte(fonte=fonte, schema_id="cnes_estab_cbo.v1", campos=("cbo",)),
        ),
        politica_id="B_ATEND",
        criterios_temporais=criterios_temporais,
        referencia=docref(),
    )


def registro_producao(
    atendimento: str | None, processamento: str | None, indice: int = 0
) -> ProductionRecord:
    origem = RowLocator(artifact_id=ARTEFATO_PA, indice=indice)
    return ProductionRecord(
        row_id=origem.row_id(),
        origem=origem,
        competencia_atendimento=atendimento,
        competencia_processamento=processamento,
        instrumento=ValorNormalizado(bruto="BPA_C", valor="BPA_C"),
    )
