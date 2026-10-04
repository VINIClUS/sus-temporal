"""Explicações, evidências reexecutáveis e PROV (T08) sobre execuções SINTETICAS do motor."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from prov.model import ProvDocument
from pydantic import ValidationError

from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.contracts.explanation import (
    Afirmacao,
    EstadoCobertura,
    ExplanationBundle,
    Limitacao,
    TipoEvidencia,
)
from sustemporal.contracts.rules import EstadoAvaliacao, FalhaOperacional
from sustemporal.errors import ExitCode
from sustemporal.explanation.cli import diretorio_explicacao, executar_explain
from sustemporal.explanation.evidence import (
    EvidenciaDivergente,
    ler_evidencia,
    reexecutar_evidencia,
    sql_reexecucao,
)
from sustemporal.explanation.explain import ExplicacaoIndisponivel, explain, montar_explicacao
from sustemporal.explanation.explain_texto import TemplateInvalido, afirmar, carregar_templates
from sustemporal.explanation.prov import ProvIncompleto, exigir_relacoes
from sustemporal.rules.catalog import carregar_esquema
from tests.fixtures.explicacao_cenario import (
    LINHA_CONFORME,
    LINHA_INCONCLUSIVA,
    LINHA_NAO_APLICAVEL,
    LINHA_VIOLACAO,
    executar_cenario,
)
from tests.fixtures.regras_cenario import reemitir
from tests.fixtures.regras_execucao import regras_so_de_c, saida

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleEvaluation

LINHAS = (LINHA_CONFORME, LINHA_VIOLACAO, LINHA_INCONCLUSIVA, LINHA_NAO_APLICAVEL)


@pytest.fixture
def execucao(tmp_path: Path) -> RunResult:
    return executar_cenario(tmp_path)


def _avaliacao(bundle: ExplanationBundle, rule_id: str) -> RuleEvaluation:
    return next(a for a in bundle.avaliacoes if a.rule_id == rule_id)


def _ids(bundle: ExplanationBundle) -> set[str]:
    conhecidos = {e.evidence_id for e in bundle.evidencias} | {a.rule_id for a in bundle.avaliacoes}
    return conhecidos | {aid for s in bundle.selecoes for aid in s.artifact_ids}


def _trocar_saida(run: RunResult, alvo: str, /, **campos: object) -> RunResult:
    saidas = tuple(
        ref.model_copy(update=campos) if ref.schema_id == alvo else ref for ref in run.saidas
    )
    return run.model_copy(update={"saidas": saidas})


def _reescrever(caminho: str, alterar: Callable[[dict[str, object]], dict[str, object]]) -> None:
    linhas = pq.read_table(caminho).to_pylist()
    esquema = pq.read_schema(caminho)
    alteradas = [alterar(dict(linha)) for linha in linhas]
    pq.write_table(pa.Table.from_pylist(alteradas, esquema), caminho)


def test_ausencia_documentada_guarda_consulta_fonte_cobertura_e_integridade(
    execucao: RunResult,
) -> None:
    bundle = explain(execucao, LINHA_VIOLACAO)
    violacao = _avaliacao(bundle, "ESTAB_CBO_CNES")
    assert violacao.estado is EstadoAvaliacao.VIOLACAO
    (evidencia,) = [e for e in bundle.evidencias if e.evidence_id in violacao.evidence_ids]
    assert evidencia.tipo is TipoEvidencia.AUSENCIA_NA_FONTE
    assert evidencia.query_id == "estabelecimento_cbo.existencia"
    assert evidencia.parametros == {"cbo": "223505", "cnes": "1234567"}
    assert evidencia.n_resultados == 0
    assert evidencia.sustenta_ausencia
    cnes = next(d for d in execucao.entradas if d.schema_id == "cnes_estab_cbo.v1")
    assert (evidencia.dataset_id, evidencia.hash_logico) == (cnes.dataset_id, cnes.hash_logico)
    assert Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA in bundle.limitacoes
    texto = montar_explicacao(execucao, LINHA_VIOLACAO).texto
    assert "não prova inexistência" in texto
    assert evidencia.sql_sha256 in texto


def test_fonte_incompleta_nao_sustenta_violacao(execucao: RunResult) -> None:
    bundle = explain(execucao, LINHA_INCONCLUSIVA)
    inconclusiva = _avaliacao(bundle, "ESTAB_CBO_CNES")
    assert inconclusiva.estado is EstadoAvaliacao.INCONCLUSIVO
    assert not any(a.estado is EstadoAvaliacao.VIOLACAO for a in bundle.avaliacoes)
    assert not any(a.template_id == "regra.violacao" for a in bundle.afirmacoes)
    assert Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA in bundle.limitacoes
    violacao = explain(execucao, LINHA_VIOLACAO)
    ausencia = next(e for e in violacao.evidencias if e.tipo is TipoEvidencia.AUSENCIA_NA_FONTE)
    for troca in (
        {"tipo": TipoEvidencia.FONTE_INCOMPLETA},
        {"cobertura": EstadoCobertura.INSUFICIENTE},
    ):
        evidencias = tuple(
            e.model_copy(update=troca) if e is ausencia else e for e in violacao.evidencias
        )
        with pytest.raises(ValidationError, match="violacao_sem_ausencia_sustentada"):
            ExplanationBundle.model_validate(
                violacao.model_dump() | {"evidencias": [e.model_dump() for e in evidencias]}
            )


def test_evidencia_de_fonte_incompleta_gravada_como_ausencia_e_recusada(
    execucao: RunResult,
) -> None:
    caminho = saida(execucao, "evidencias.v1")

    def incompleta(linha: dict[str, object]) -> dict[str, object]:
        if linha["tipo"] == "AUSENCIA_NA_FONTE":
            linha["cobertura"] = "INSUFICIENTE"
        return linha

    _reescrever(caminho, incompleta)
    ref = reemitir(next(r for r in execucao.saidas if r.schema_id == "evidencias.v1"))
    adulterada = _trocar_saida(execucao, "evidencias.v1", **ref.model_dump(exclude={"caminho"}))
    with pytest.raises(ExplicacaoIndisponivel, match="violacao_sem_ausencia_sustentada"):
        explain(adulterada, LINHA_VIOLACAO)


def test_vinculo_encontrado_cita_chave_e_resultados(execucao: RunResult) -> None:
    bundle = explain(execucao, LINHA_CONFORME)
    assert {a.estado for a in bundle.avaliacoes} == {EstadoAvaliacao.CONFORME}
    estab = _avaliacao(bundle, "ESTAB_CBO_CNES")
    (evidencia,) = [e for e in bundle.evidencias if e.evidence_id in estab.evidence_ids]
    assert evidencia.tipo is TipoEvidencia.VINCULO_ENCONTRADO
    assert evidencia.n_resultados == 1
    assert evidencia.chaves_amostra == ("1234567|225125",)
    assert Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA not in bundle.limitacoes


@pytest.mark.parametrize("linha", LINHAS)
def test_cada_afirmacao_aponta_para_elemento_do_bundle(execucao: RunResult, linha: str) -> None:
    explicacao = montar_explicacao(execucao, linha)
    bundle = explicacao.bundle
    templates = carregar_templates()
    assert bundle.afirmacoes
    for afirmacao in bundle.afirmacoes:
        assert afirmacao.template_id in templates
        assert set(afirmacao.referencias) <= _ids(bundle)
        assert afirmacao.texto in explicacao.texto
    regras_afirmadas = {r for a in bundle.afirmacoes for r in a.referencias}
    assert {a.rule_id for a in bundle.avaliacoes} <= regras_afirmadas


def test_afirmacao_sem_referencia_resolvivel_e_recusada(execucao: RunResult) -> None:
    bundle = explain(execucao, LINHA_CONFORME)
    estab = _avaliacao(bundle, "ESTAB_CBO_CNES")
    sem_evidencia = estab.model_copy(update={"evidence_ids": ()})
    with pytest.raises(TemplateInvalido, match="template_sem_referencia"):
        afirmar("regra.conforme", sem_evidencia, evidencias={})
    with pytest.raises(TemplateInvalido, match="template_desconhecido"):
        afirmar("regra.inventada", estab, evidencias={})
    falsa = Afirmacao(texto="x", template_id="regra.conforme", referencias=("ev_inexistente",))
    with pytest.raises(ValidationError, match="afirmacao_sem_referencia_valida"):
        ExplanationBundle.model_validate(bundle.model_dump() | {"afirmacoes": [falsa.model_dump()]})


def test_prov_json_e_prov_n_validos_com_relacoes_exigidas(execucao: RunResult) -> None:
    explicacao = montar_explicacao(execucao, LINHA_VIOLACAO)
    bundle = explicacao.bundle
    assert hashlib.sha256(explicacao.prov_json.encode()).hexdigest() == bundle.prov_json_sha256
    documento = ProvDocument.deserialize(content=explicacao.prov_json, format="json")
    conteudo = json.loads(explicacao.prov_json)
    for relacao in ("used", "wasGeneratedBy", "wasDerivedFrom", "wasAssociatedWith"):
        assert conteudo.get(relacao), relacao
        assert f"{relacao}(" in bundle.prov_n
    assert {"entity", "activity", "agent"} <= set(conteudo)
    assert bundle.prov_n.startswith("document")
    assert bundle.prov_n.rstrip().endswith("endDocument")
    exigir_relacoes(documento)
    assert "inexistência" in json.dumps(conteudo["entity"], ensure_ascii=False)


def test_prov_sem_derivacao_e_recusado(execucao: RunResult) -> None:
    conteudo = json.loads(montar_explicacao(execucao, LINHA_VIOLACAO).prov_json)
    conteudo.pop("wasDerivedFrom")
    documento = ProvDocument.deserialize(content=json.dumps(conteudo), format="json")
    with pytest.raises(ProvIncompleto, match="prov_sem_relacao relacao=wasDerivedFrom"):
        exigir_relacoes(documento)


@pytest.mark.parametrize(
    ("gerada", "usada"),
    [
        ("sus:avaliacao_", "sus:ev_"),
        ("sus:avaliacao_", "sus:regra_"),
        ("sus:avaliacao_", "sus:registro_"),
        ("sus:ev_", "sus:ds_"),
    ],
)
def test_prov_sem_uma_derivacao_exigida_e_recusado(
    execucao: RunResult, gerada: str, usada: str
) -> None:
    conteudo = json.loads(montar_explicacao(execucao, LINHA_VIOLACAO).prov_json)
    conteudo["wasDerivedFrom"] = {
        chave: aresta
        for chave, aresta in conteudo["wasDerivedFrom"].items()
        if not (
            aresta["prov:generatedEntity"].startswith(gerada)
            and aresta["prov:usedEntity"].startswith(usada)
        )
    }
    documento = ProvDocument.deserialize(content=json.dumps(conteudo), format="json")
    with pytest.raises(ProvIncompleto, match="prov_derivacao_ausente"):
        exigir_relacoes(documento)


def test_reexecucao_da_evidencia_reproduz_resultado_e_hash(execucao: RunResult) -> None:
    explicacao = montar_explicacao(execucao, LINHA_VIOLACAO)
    assert explicacao.reexecucoes
    assert all(r.reproduzida for r in explicacao.reexecucoes)
    conjuntos = {d.dataset_id: d for d in execucao.entradas}
    for evidencia in explicacao.bundle.evidencias:
        reexecucao = reexecutar_evidencia(evidencia, conjuntos)
        assert reexecucao.hash_logico == evidencia.hash_logico
        assert reexecucao.n_resultados == evidencia.n_resultados
        assert (
            reexecucao.sql_sha256
            == hashlib.sha256(sql_reexecucao(evidencia.query_id).encode()).hexdigest()
        )


def test_divergencia_na_reexecucao_e_falha_nunca_troca_evidencia(execucao: RunResult) -> None:
    cnes = next(d for d in execucao.entradas if d.schema_id == "cnes_estab_cbo.v1")

    def com_vinculo(linha: dict[str, object]) -> dict[str, object]:
        return linha | {"cbo": "223505"}

    _reescrever(cnes.caminho, com_vinculo)
    with pytest.raises(EvidenciaDivergente, match="evidencia_divergente"):
        explain(execucao, LINHA_VIOLACAO)
    conjuntos = {d.dataset_id: d for d in execucao.entradas}
    colunas = [c.nome for c in carregar_esquema("evidencias.v1").colunas]
    linhas = pq.read_table(saida(execucao, "evidencias.v1")).to_pylist()
    ausencia = next(
        linha
        for linha in linhas
        if (linha["tipo"], linha["query_id"])
        == ("AUSENCIA_NA_FONTE", "estabelecimento_cbo.existencia")
    )
    assert set(ausencia) == set(colunas)
    reexecucao = reexecutar_evidencia(ler_evidencia(ausencia), conjuntos)
    assert not reexecucao.reproduzida
    assert any(d.startswith("hash_logico") for d in reexecucao.divergencias)
    assert any(d.startswith("n_resultados") for d in reexecucao.divergencias)


def test_bundle_deterministico_para_a_mesma_execucao(tmp_path: Path) -> None:
    primeira = executar_cenario(tmp_path, nome="a")
    segunda = executar_cenario(tmp_path, nome="b")
    assert primeira.run_id == segunda.run_id
    instantes = {"iniciado_em": primeira.iniciado_em, "concluido_em": primeira.concluido_em}
    segunda = segunda.model_copy(update=instantes)
    for linha in LINHAS:
        a = montar_explicacao(primeira, linha)
        assert a.bundle == explain(primeira, linha)
        b = montar_explicacao(segunda, linha)
        assert a.bundle.model_dump_json() == b.bundle.model_dump_json()
        assert (a.prov_json, a.texto) == (b.prov_json, b.texto)


@pytest.mark.parametrize("linha", LINHAS)
def test_nenhuma_afirmacao_de_causa_oficial(execucao: RunResult, linha: str) -> None:
    explicacao = montar_explicacao(execucao, linha)
    bundle = explicacao.bundle
    assert bundle.causa_oficial_atribuida is False
    assert Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL in bundle.limitacoes
    assert Limitacao.DADOS_SINTETICOS in bundle.limitacoes
    texto = explicacao.texto.lower().replace("resultado_nao_e_causa_oficial", "")
    for trecho in re.findall(r".{0,25}causa.{0,25}", texto):
        assert "não é causa oficial" in trecho or "não atribui causa" in trecho, trecho
    assert "glosa" not in texto
    assert "motivo oficial" not in texto


def test_registro_sem_violacao_nunca_vira_aprovado(execucao: RunResult) -> None:
    conforme = montar_explicacao(execucao, LINHA_CONFORME)
    abstencao = montar_explicacao(execucao, LINHA_INCONCLUSIVA)
    assert {a.template_id for a in conforme.bundle.afirmacoes} >= {"registro.sem_violacao"}
    assert {a.template_id for a in abstencao.bundle.afirmacoes} >= {"registro.abstencao"}
    for explicacao in (conforme, abstencao):
        texto = explicacao.texto.lower()
        assert "aprovado" not in texto
        assert "aprovada" not in texto
        assert "não equivale a aprovação" in texto


def test_nao_aplicavel_cita_evidencia_de_aplicabilidade(tmp_path: Path) -> None:
    regras = regras_so_de_c()
    execucao = executar_cenario(tmp_path, regras=regras)
    with pytest.raises(ExplicacaoIndisponivel, match="catalogo_diverge_da_execucao"):
        explain(execucao, LINHA_NAO_APLICAVEL)
    bundle = explain(execucao, LINHA_NAO_APLICAVEL, regras=regras)
    assert {a.estado for a in bundle.avaliacoes} == {EstadoAvaliacao.NAO_APLICAVEL}
    assert {e.tipo for e in bundle.evidencias} == {TipoEvidencia.APLICABILIDADE}
    assert {a.template_id for a in bundle.afirmacoes} >= {"regra.nao_aplicavel"}


def test_saida_de_outra_execucao_e_recusada(tmp_path: Path) -> None:
    primeira = executar_cenario(tmp_path, nome="a")
    outra = executar_cenario(tmp_path, nome="b", regras=regras_so_de_c())
    alheia = next(r for r in outra.saidas if r.schema_id == "avaliacoes.v1")
    misturada = _trocar_saida(primeira, "avaliacoes.v1", **alheia.model_dump())
    with pytest.raises(ExplicacaoIndisponivel, match="saida_de_outra_execucao"):
        explain(misturada, LINHA_CONFORME)
    renomeada = alheia.model_copy(update={"produzido_por": primeira.run_id})
    misturada = _trocar_saida(primeira, "avaliacoes.v1", **renomeada.model_dump())
    with pytest.raises(ExplicacaoIndisponivel, match="saida_mistura_execucoes"):
        explain(misturada, LINHA_CONFORME)
    bundle = explain(primeira, LINHA_CONFORME)
    estranha = explain(outra, LINHA_CONFORME, regras=regras_so_de_c()).avaliacoes[0]
    with pytest.raises(ValidationError, match="explicacao_mistura_execucoes"):
        ExplanationBundle.model_validate(
            bundle.model_dump()
            | {"avaliacoes": [*[a.model_dump() for a in bundle.avaliacoes], estranha.model_dump()]}
        )


def test_saida_com_conteudo_divergente_e_recusada(execucao: RunResult) -> None:
    _reescrever(saida(execucao, "avaliacoes.v1"), lambda linha: linha)
    adulterada = _trocar_saida(execucao, "avaliacoes.v1", linhas=0)
    with pytest.raises(ExplicacaoIndisponivel, match="conteudo_divergente"):
        explain(adulterada, LINHA_CONFORME)


@pytest.mark.parametrize("linha_da_falha", [LINHA_CONFORME, None])
def test_registro_ou_execucao_com_falha_operacional_e_recusado(
    execucao: RunResult, linha_da_falha: str | None
) -> None:
    caminho = saida(execucao, "falhas.v1")
    falha = {
        "run_id": execucao.run_id,
        "sequencia": 1,
        "etapa": "avaliar_regra",
        "row_id": linha_da_falha,
        "rule_id": "ESTAB_CBO_CNES",
        "erro": "falha_sintetica",
        "ocorrida_em": "2026-01-01T00:00:00+00:00",
    }
    pq.write_table(pa.Table.from_pylist([falha], pq.read_schema(caminho)), caminho)
    ref = reemitir(next(r for r in execucao.saidas if r.schema_id == "falhas.v1"))
    adulterada = _trocar_saida(execucao, "falhas.v1", **ref.model_dump(exclude={"caminho"}))
    with pytest.raises(ExplicacaoIndisponivel, match="registro_com_falha_operacional"):
        explain(adulterada, LINHA_CONFORME)
    falhou = execucao.model_copy(update={"estado": EstadoExecucao.FALHOU, "falhas": 1})
    with pytest.raises(ExplicacaoIndisponivel, match="execucao_falhou"):
        explain(falhou, LINHA_CONFORME)


def test_linha_inexistente_e_recusada(execucao: RunResult) -> None:
    with pytest.raises(ExplicacaoIndisponivel, match="registro_sem_avaliacao"):
        explain(execucao, LINHA_CONFORME.replace("#0", "#99"))


def _args(run_id: str, row_id: str) -> argparse.Namespace:
    return argparse.Namespace(comando="explain", run=run_id, row=row_id)


def _config(raiz: Path) -> RunConfig:
    return RunConfig(versao="1", runtime=RuntimeConfig(raiz_saidas=str(raiz)))


def test_cli_grava_json_prov_e_texto_no_diretorio_da_execucao(tmp_path: Path) -> None:
    execucao = executar_cenario(tmp_path, nome="validacao")
    raiz = tmp_path
    gravada = raiz / "validacao" / "saida" / execucao.run_id
    assert (gravada / "run_result.json").exists()
    (raiz / "validacao" / execucao.run_id).symlink_to(gravada)
    codigo = executar_explain(_args(execucao.run_id, LINHA_VIOLACAO), _config(raiz))
    assert codigo == ExitCode.OK
    destino = diretorio_explicacao(raiz, execucao.run_id, LINHA_VIOLACAO)
    assert execucao.run_id in str(destino)
    nomes = {p.name for p in destino.iterdir()}
    assert {"bundle.json", "prov.provn", "prov.json", "explicacao.txt"} <= nomes
    bundle = ExplanationBundle.model_validate_json((destino / "bundle.json").read_text("utf-8"))
    assert bundle == explain(execucao, LINHA_VIOLACAO)
    prov_json = (destino / "prov.json").read_bytes()
    assert hashlib.sha256(prov_json).hexdigest() == bundle.prov_json_sha256


@pytest.mark.parametrize(
    ("run_id", "row_id"),
    [
        ("val_inexistente", LINHA_CONFORME),
        (None, LINHA_CONFORME.replace("#0", "#99")),
        (None, "linha-sem-formato"),
    ],
)
def test_cli_execucao_ou_linha_inexistente_sai_com_2(
    tmp_path: Path, run_id: str | None, row_id: str
) -> None:
    execucao = executar_cenario(tmp_path, nome="validacao")
    (tmp_path / "validacao" / execucao.run_id).symlink_to(
        tmp_path / "validacao" / "saida" / execucao.run_id
    )
    codigo = executar_explain(_args(run_id or execucao.run_id, row_id), _config(tmp_path))
    assert codigo == ExitCode.CONFIG_INVALIDA


def test_cli_recusa_run_fora_da_raiz(tmp_path: Path) -> None:
    for run_id in ("..", "../x", "/etc"):
        codigo = executar_explain(_args(run_id, LINHA_CONFORME), _config(tmp_path))
        assert codigo == ExitCode.CONFIG_INVALIDA


def test_cli_com_evidencia_divergente_grava_so_a_falha(tmp_path: Path) -> None:
    execucao = executar_cenario(tmp_path, nome="validacao")
    (tmp_path / "validacao" / execucao.run_id).symlink_to(
        tmp_path / "validacao" / "saida" / execucao.run_id
    )
    args, config = _args(execucao.run_id, LINHA_VIOLACAO), _config(tmp_path)
    assert executar_explain(args, config) == ExitCode.OK
    cnes = next(d for d in execucao.entradas if d.schema_id == "cnes_estab_cbo.v1")
    _reescrever(cnes.caminho, lambda linha: linha | {"cbo": "223505"})
    instante = datetime(2026, 1, 1, tzinfo=UTC)
    codigo = executar_explain(args, config, relogio=lambda: instante)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    destino = diretorio_explicacao(tmp_path, execucao.run_id, LINHA_VIOLACAO)
    assert {p.name for p in destino.iterdir()} == {"falha.json"}
    falha = FalhaOperacional.model_validate_json((destino / "falha.json").read_text("utf-8"))
    assert falha.ocorrida_em == instante
    assert "evidencia_divergente" in falha.erro
