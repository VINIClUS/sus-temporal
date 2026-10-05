"""Documento PROV da explicação: entidades, atividades e agente (T08).

Arquivos (versões de conteúdo), conjuntos, regras, registro, evidências e avaliações são
entidades; aquisição, transformação e avaliação são atividades; o software é o agente. O PROV
representa as relações; não transforma resultado vazio em prova de inexistência no mundo real.
Sem caminhos de arquivo nem relógio: o documento depende só do conteúdo da execução.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prov.model import (
    PROV,
    ProvAssociation,
    ProvDerivation,
    ProvDocument,
    ProvGeneration,
    ProvUsage,
)

from sustemporal.contracts.base import json_canonico
from sustemporal.contracts.explanation import TipoEvidencia

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from prov.identifier import QualifiedName

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.explanation import Evidence
    from sustemporal.contracts.records import DatasetRef, ProductionRecord
    from sustemporal.contracts.rules import RuleEvaluation, RuleSpec

__all__ = [
    "AVISO_AUSENCIA",
    "DocumentoProv",
    "ElementosProv",
    "ProvIncompleto",
    "arestas_exigidas",
    "exigir_relacoes",
    "exportar",
    "montar_documento",
]

NAMESPACE = "urn:sustemporal:"
AVISO_AUSENCIA = (
    "resultado vazio na fonte consultada não prova inexistência no mundo real; "
    "a relação PROV só registra a consulta e o conjunto consultado"
)
_SOFTWARE = "sus:software_sustemporal"
_RELACOES = (
    ("used", ProvUsage),
    ("wasGeneratedBy", ProvGeneration),
    ("wasDerivedFrom", ProvDerivation),
    ("wasAssociatedWith", ProvAssociation),
)
_SEM_PROVA = {TipoEvidencia.AUSENCIA_NA_FONTE, TipoEvidencia.FONTE_INCOMPLETA}


class ProvIncompleto(ValueError):
    """Documento PROV sem as relações exigidas."""


@dataclass(frozen=True)
class ElementosProv:
    run: RunResult
    registro: ProductionRecord
    avaliacoes: tuple[RuleEvaluation, ...]
    evidencias: tuple[Evidence, ...]
    regras: Mapping[str, RuleSpec]
    reexecucoes_sql: Mapping[str, str | None]


@dataclass(frozen=True)
class DocumentoProv:
    provn: str
    json: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.json.encode("utf-8")).hexdigest()


def _curto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:32]


def _id_regra(regra: RuleSpec) -> str:
    return f"sus:regra_{regra.rule_id}_{regra.versao.replace('.', '_')}"


def _id_registro(row_id: str) -> str:
    return f"sus:registro_{_curto(row_id)}"


def _id_avaliacao(avaliacao: RuleEvaluation) -> str:
    return f"sus:avaliacao_{_curto(f'{avaliacao.run_id}|{avaliacao.row_id}')}_{avaliacao.rule_id}"


def _software(doc: ProvDocument, run: RunResult) -> None:
    atributos: dict[str, QualifiedName | str] = {
        "prov:type": PROV["SoftwareAgent"],
        "sus:versao_pacote": run.codigo.versao_pacote,
        "sus:commit": run.codigo.commit,
        "sus:sujo": str(run.codigo.sujo).lower(),
    }
    if run.codigo.diff_sha256 is not None:
        atributos["sus:diff_sha256"] = run.codigo.diff_sha256
    doc.agent(_SOFTWARE, atributos)


def _conjunto(doc: ProvDocument, dataset: DatasetRef, artefatos_vistos: set[str]) -> None:
    ds = f"sus:{dataset.dataset_id}"
    transformacao = f"sus:transformacao_{dataset.dataset_id}"
    doc.entity(
        ds,
        {
            "sus:schema_id": dataset.schema_id,
            "sus:hash_logico": dataset.hash_logico,
            "sus:linhas": dataset.linhas,
            "sus:origem_dados": str(dataset.origem_dados),
        },
    )
    doc.activity(transformacao, other_attributes={"sus:etapa": "transformacao"})
    doc.wasAssociatedWith(transformacao, _SOFTWARE)
    for artifact_id in sorted(dataset.artifact_ids):
        art = f"sus:{artifact_id}"
        if artifact_id not in artefatos_vistos:
            artefatos_vistos.add(artifact_id)
            aquisicao = f"sus:aquisicao_{artifact_id}"
            doc.entity(art, {"sus:tipo": "versao_de_conteudo"})
            doc.activity(aquisicao, other_attributes={"sus:etapa": "aquisicao"})
            doc.wasGeneratedBy(art, aquisicao)
            doc.wasAssociatedWith(aquisicao, _SOFTWARE)
        doc.used(transformacao, art)
        doc.wasDerivedFrom(ds, art)
    doc.wasGeneratedBy(ds, transformacao)


def _execucao(doc: ProvDocument, elementos: ElementosProv) -> str:
    run = elementos.run
    execucao = f"sus:execucao_{run.run_id}"
    doc.activity(
        execucao,
        run.iniciado_em,
        run.concluido_em,
        {
            "sus:etapa": "avaliacao",
            "sus:metodo": str(run.metodo),
            "sus:politica_id": str(run.politica_id),
            "sus:config_hash": run.config_hash,
            "sus:estado": str(run.estado),
        },
    )
    doc.wasAssociatedWith(execucao, _SOFTWARE)
    for dataset in sorted(run.entradas, key=lambda d: d.dataset_id):
        doc.used(execucao, f"sus:{dataset.dataset_id}")
    for rule_id in sorted(elementos.regras):
        regra = elementos.regras[rule_id]
        doc.entity(
            _id_regra(regra),
            {
                "sus:rule_id": regra.rule_id,
                "sus:versao": regra.versao,
                "sus:estado": str(regra.estado),
                "sus:referencia": regra.referencia.doc_id,
                "sus:proveniencia": str(regra.referencia.proveniencia),
                "sus:confirmacao": str(regra.referencia.confirmacao),
            },
        )
        doc.used(execucao, _id_regra(regra))
    for saida in sorted(run.saidas, key=lambda d: d.schema_id):
        doc.entity(
            f"sus:{saida.dataset_id}",
            {"sus:schema_id": saida.schema_id, "sus:hash_logico": saida.hash_logico},
        )
        doc.wasGeneratedBy(f"sus:{saida.dataset_id}", execucao)
    return execucao


def _conjuntos_do_registro(elementos: ElementosProv) -> list[DatasetRef]:
    """Conjuntos SIA-PA de entrada: a derivação registro → SIA-PA é sempre exigida.

    Raises:
        ProvIncompleto: execução sem `sia_pa.v1` de entrada.
    """
    conjuntos = [d for d in elementos.run.entradas if d.schema_id == "sia_pa.v1"]
    if not conjuntos:
        raise ProvIncompleto(f"prov_sem_conjunto_do_registro run={elementos.run.run_id}")
    return sorted(conjuntos, key=lambda d: d.dataset_id)


def _registro(doc: ProvDocument, elementos: ElementosProv) -> str:
    registro = elementos.registro
    identificador = _id_registro(registro.row_id)
    doc.entity(identificador, {"sus:row_id": registro.row_id, "sus:tipo": "registro"})
    for dataset in _conjuntos_do_registro(elementos):
        doc.wasDerivedFrom(identificador, f"sus:{dataset.dataset_id}")
    return identificador


def _evidencias(doc: ProvDocument, elementos: ElementosProv, execucao: str) -> None:
    for evidencia in sorted(elementos.evidencias, key=lambda e: e.evidence_id):
        atributos: dict[str, str | int] = {
            "sus:tipo": str(evidencia.tipo),
            "sus:query_id": evidencia.query_id,
            "sus:sql_sha256": evidencia.sql_sha256,
            "sus:parametros": json_canonico(dict(evidencia.parametros)),
            "sus:hash_logico": evidencia.hash_logico,
            "sus:cobertura": str(evidencia.cobertura),
            "sus:integridade": str(evidencia.integridade),
            "sus:n_resultados": evidencia.n_resultados,
        }
        sql = elementos.reexecucoes_sql.get(evidencia.evidence_id)
        if sql is not None:
            atributos["sus:sql_reexecucao_sha256"] = sql
        if evidencia.tipo in _SEM_PROVA:
            atributos["sus:limitacao"] = AVISO_AUSENCIA
        origens = _origens_da_evidencia(evidencia)
        atributos["sus:versoes_consultadas"] = ";".join(evidencia.artifact_ids)
        atributos["sus:derivada_de"] = ";".join(origens)
        doc.entity(f"sus:{evidencia.evidence_id}", atributos)
        doc.wasGeneratedBy(f"sus:{evidencia.evidence_id}", execucao)
        for origem in origens:
            doc.wasDerivedFrom(f"sus:{evidencia.evidence_id}", origem)


def _origens_da_evidencia(evidencia: Evidence) -> list[str]:
    return [f"sus:{evidencia.dataset_id}", *(f"sus:{a}" for a in sorted(evidencia.artifact_ids))]


def _origens_da_avaliacao(
    avaliacao: RuleEvaluation, elementos: ElementosProv, registro: str
) -> list[str]:
    regra = _id_regra(elementos.regras[avaliacao.rule_id])
    return [registro, regra, *(f"sus:{e}" for e in avaliacao.evidence_ids)]


def arestas_exigidas(elementos: ElementosProv) -> list[tuple[str, str]]:
    """`wasDerivedFrom` que o documento precisa ter, derivadas dos elementos (não do documento)."""
    registro = _id_registro(elementos.registro.row_id)
    arestas = [
        (f"sus:{d.dataset_id}", f"sus:{a}") for d in elementos.run.entradas for a in d.artifact_ids
    ]
    arestas += [(registro, f"sus:{d.dataset_id}") for d in _conjuntos_do_registro(elementos)]
    for evidencia in elementos.evidencias:
        arestas += [(f"sus:{evidencia.evidence_id}", o) for o in _origens_da_evidencia(evidencia)]
    for avaliacao in elementos.avaliacoes:
        origens = _origens_da_avaliacao(avaliacao, elementos, registro)
        arestas += [(_id_avaliacao(avaliacao), o) for o in origens]
    return arestas


def _avaliacoes(doc: ProvDocument, elementos: ElementosProv, execucao: str, registro: str) -> None:
    for avaliacao in elementos.avaliacoes:
        identificador = _id_avaliacao(avaliacao)
        origens = _origens_da_avaliacao(avaliacao, elementos, registro)
        doc.entity(
            identificador,
            {
                "sus:tipo": "avaliacao",
                "sus:rule_id": avaliacao.rule_id,
                "sus:estado": str(avaliacao.estado),
                "sus:motivos": ";".join(avaliacao.motivos),
                "sus:causa_oficial_atribuida": "false",
                "sus:derivada_de": ";".join(origens),
            },
        )
        doc.wasGeneratedBy(identificador, execucao)
        for origem in origens:
            doc.wasDerivedFrom(identificador, origem)
    selecionados = {
        a for avaliacao in elementos.avaliacoes for s in avaliacao.selecoes for a in s.artifact_ids
    }
    for artifact_id in sorted(selecionados):
        doc.used(execucao, f"sus:{artifact_id}")


def montar_documento(elementos: ElementosProv) -> ProvDocument:
    """Documento PROV determinístico de uma explicação (ordem de inserção fixa)."""
    doc = ProvDocument()
    doc.add_namespace("sus", NAMESPACE)
    _software(doc, elementos.run)
    vistos: set[str] = set()
    for dataset in sorted(elementos.run.entradas, key=lambda d: d.dataset_id):
        _conjunto(doc, dataset, vistos)
    execucao = _execucao(doc, elementos)
    registro = _registro(doc, elementos)
    _evidencias(doc, elementos, execucao)
    _avaliacoes(doc, elementos, execucao, registro)
    exigir_relacoes(doc, elementos)
    return doc


def _arestas(doc: ProvDocument) -> set[tuple[str, str]]:
    return {
        (str(r.formal_attributes[0][1]), str(r.formal_attributes[1][1]))
        for r in doc.get_records(ProvDerivation)
    }


def _derivacoes_ausentes(doc: ProvDocument) -> Iterable[str]:
    """Entidade que declara `sus:derivada_de` sem a aresta `wasDerivedFrom` correspondente."""
    arestas = _arestas(doc)
    for registro in doc.get_records():
        atributos = {str(c): str(v) for c, v in registro.attributes}
        exigidas = [o for o in atributos.get("sus:derivada_de", "").split(";") if o]
        if atributos.get("sus:tipo") == "avaliacao" and not exigidas:
            yield f"{registro.identifier} origem=nenhuma"
        for origem in exigidas:
            if (str(registro.identifier), origem) not in arestas:
                yield f"{registro.identifier} origem={origem}"


def exigir_relacoes(documento: ProvDocument, elementos: ElementosProv | None = None) -> None:
    """Exige as quatro relações, as derivações dos `elementos` e as declaradas no documento.

    Avaliação deriva do registro, da regra e de cada evidência; evidência, do conjunto e das
    versões consultadas; conjunto, das versões; registro, do `sia_pa.v1`. Com `elementos`, as
    arestas exigidas vêm deles e não do que o documento declara.

    Raises:
        ProvIncompleto: relação ausente ou derivação declarada sem aresta.
    """
    for nome, classe in _RELACOES:
        if not list(documento.get_records(classe)):
            raise ProvIncompleto(f"prov_sem_relacao relacao={nome}")
    if elementos is not None:
        presentes = _arestas(documento)
        for gerada, usada in arestas_exigidas(elementos):
            if (gerada, usada) not in presentes:
                raise ProvIncompleto(f"prov_derivacao_ausente entidade={gerada} origem={usada}")
    for ausente in _derivacoes_ausentes(documento):
        raise ProvIncompleto(f"prov_derivacao_ausente entidade={ausente}")


def exportar(documento: ProvDocument) -> DocumentoProv:
    """PROV-N e PROV-JSON canônico (chaves ordenadas) do documento."""
    serializado = documento.serialize(format="json")
    if serializado is None:
        raise ProvIncompleto("prov_sem_serializacao")
    conteudo = json.loads(serializado)
    return DocumentoProv(provn=documento.get_provn(), json=json_canonico(conteudo))
