import hashlib
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
MANIFESTO_SPEC = RAIZ / "docs" / "spec" / "manifest.yaml"


def _documentos() -> list[dict[str, object]]:
    conteudo = yaml.safe_load(MANIFESTO_SPEC.read_text(encoding="utf-8"))
    return list(conteudo["documentos"])


def test_original_spec_hash_preserved() -> None:
    documentos = _documentos()
    assert {doc["id"] for doc in documentos} >= {"esboco_original", "plano_implementacao"}
    for doc in documentos:
        caminho = RAIZ / str(doc["caminho"])
        if doc["estado"] == "PENDENTE":
            assert doc["sha256"] is None
            assert not caminho.exists(), f"arquivo_sem_hash_registrado caminho={caminho}"
            continue
        assert doc["estado"] == "PRESERVADO"
        dados = caminho.read_bytes()
        assert hashlib.sha256(dados).hexdigest() == doc["sha256"]
        assert len(dados) == doc["tamanho_bytes"]


def _avaliacao(**campos: object) -> dict[str, object]:
    base: dict[str, object] = {
        "run_id": "run_teste",
        "row_id": "art_" + "a" * 64 + "#0",
        "rule_id": "PROC_CBO_001",
        "versao": "0.1.0",
        "politica_id": "M_TEMP_PADRAO",
        "metodo": "M_TEMP",
        "aplicabilidade": "APLICAVEL",
    }
    return {**base, **campos}


def test_missing_input_is_not_violation() -> None:
    from pydantic import ValidationError

    from sustemporal.contracts import (
        AgregadoRegistro,
        Aplicabilidade,
        EstadoAvaliacao,
        MotivoInconclusao,
        RuleEvaluation,
        decidir_estado,
    )

    faltante = [MotivoInconclusao.ARQUIVO_AUSENTE]
    assert decidir_estado(Aplicabilidade.APLICAVEL, False, True, faltante) == "INCONCLUSIVO"
    assert decidir_estado(Aplicabilidade.APLICAVEL, True, True, faltante) == "INCONCLUSIVO"
    assert decidir_estado(Aplicabilidade.DESCONHECIDA, True, True, []) == "INCONCLUSIVO"
    with pytest.raises(ValidationError):
        RuleEvaluation.model_validate(
            _avaliacao(
                estado="VIOLACAO",
                insumos_completos=False,
                incompatibilidade_demonstrada=True,
                motivos=["ARQUIVO_AUSENTE"],
            )
        )
    inconclusiva = RuleEvaluation.model_validate(
        _avaliacao(
            estado="INCONCLUSIVO",
            insumos_completos=False,
            incompatibilidade_demonstrada=None,
            motivos=["ARQUIVO_AUSENTE"],
        )
    )
    agregado = AgregadoRegistro.agregar(inconclusiva.row_id, [inconclusiva])
    assert agregado.resultado == "ABSTENCAO"
    assert agregado.violacoes == ()
    assert EstadoAvaliacao.VIOLACAO not in {inconclusiva.estado}


def test_observation_time_is_not_reference_period() -> None:
    from datetime import UTC, datetime, timedelta, timezone

    from pydantic import ValidationError

    from sustemporal.contracts import (
        ArtifactObservation,
        ArtifactVersion,
        ChaveArtefato,
        CompetenciaArquivo,
        CompetenciaAtendimento,
        CompetenciaProcessamento,
    )

    atendimento = CompetenciaAtendimento("202003")
    processamento = CompetenciaProcessamento("202003")
    assert atendimento != processamento
    with pytest.raises(TypeError):
        _ = atendimento < processamento
    coletado_em = datetime(2026, 10, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="competencia"):
        CompetenciaArquivo(coletado_em)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ChaveArtefato(
            fonte="SIA_PA",
            competencia_arquivo=coletado_em,
            canal="ATUAL",
            nome_original="PASP2003a.dbc",
        )
    assert not any("observ" in campo or "_em" in campo for campo in ArtifactVersion.model_fields)
    chave = ChaveArtefato(
        fonte="SIA_PA",
        competencia_arquivo="202003",
        canal="ATUAL",
        nome_original="PASP2003a.dbc",
    )
    ingenuo = datetime(2026, 10, 1, 12)  # noqa: DTZ001
    brasilia = datetime(2026, 10, 1, tzinfo=timezone(timedelta(hours=-3)))
    for instante in (ingenuo, brasilia):
        with pytest.raises(ValidationError):
            ArtifactObservation(
                observation_id="obs_" + "b" * 32,
                chave=chave,
                request_sha256="c" * 64,
                observado_em=instante,
                resultado="NAO_ENCONTRADO",
                ferramenta="teste",
            )


def test_diretorios_de_especificacao_so_contem_arquivos_registrados() -> None:
    registrados = {str(doc["caminho"]) for doc in _documentos()}
    permitidos = registrados | {"docs/spec/README.md", "docs/spec/manifest.yaml"}
    for diretorio in ("docs/spec", "docs/plan"):
        for arquivo in (RAIZ / diretorio).iterdir():
            relativo = arquivo.relative_to(RAIZ).as_posix()
            assert relativo in permitidos, f"arquivo_nao_registrado caminho={relativo}"


def test_vigilancia_tem_janela_padrao_de_seis_competencias() -> None:
    from sustemporal.contracts import RunConfig

    config = RunConfig.model_validate(
        {"versao": "1", "vigilancia": {"familias_fontes": ["SIA_PA"]}}
    )
    assert config.vigilancia is not None
    assert config.vigilancia.janela_competencias == 6
