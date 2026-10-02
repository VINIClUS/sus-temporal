"""Comportamento transversal SINTETICO do motor: seleção, falhas, agregação, saídas e portões."""

import json
from pathlib import Path

import duckdb
import pytest

from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.contracts.explanation import Evidence
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    EstadoSelecao,
    MetodoId,
    SelecaoVersao,
    SnapshotSet,
)
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema, carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.saidas import (
    COLUNAS_AGREGADOS,
    COLUNAS_AVALIACOES,
    COLUNAS_EVIDENCIAS,
    COLUNAS_FALHAS,
    COLUNAS_SELECOES,
)
from tests.fixtures.regras_cenario import (
    CenarioRegras,
    coerente,
    materializar,
    politica,
    snapshot_vazio,
)
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, saida, tabela
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIGTAP,
    REGRAS,
    cenario_base,
    registro,
    selecao,
)

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"
_MOTIVO_DA_SELECAO = {
    "AUSENTE": ("", "ARQUIVO_AUSENTE"),
    "AMBIGUA": (f"{ART_SIGTAP};{'art_' + 'f' * 64}", "VERSAO_AMBIGUA"),
    "INCOMPLETA": (ART_SIGTAP, "COBERTURA_INSUFICIENTE"),
    "EM_QUARENTENA": (ART_SIGTAP, "ARQUIVO_EM_QUARENTENA"),
    "FORA_DO_CORTE": (ART_SIGTAP, "FORA_DO_CORTE"),
    "NAO_RESOLVIDA": ("", "VIGENCIA_NAO_RESOLVIDA"),
}


def _trocar_selecao(
    cenario: CenarioRegras, regra: str, nova: dict[str, str | None] | None
) -> CenarioRegras:
    selecoes = tuple(s for s in cenario.selecoes if s["rule_id"] != regra)
    return cenario.com(selecoes=selecoes + ((nova,) if nova else ()))


@pytest.mark.parametrize("estado", sorted(_MOTIVO_DA_SELECAO))
def test_selecao_nao_selecionada_vira_motivo_de_inconclusao(tmp_path: Path, estado: str) -> None:
    artefatos, motivo = _MOTIVO_DA_SELECAO[estado]
    competencia = None if estado == "NAO_RESOLVIDA" else "202001"
    base = None if estado == "NAO_RESOLVIDA" else "ATENDIMENTO"
    nova = selecao(LINHA, PROC, estado, artefatos=artefatos, competencia=competencia, base=base)
    cenario = _trocar_selecao(cenario_base(registro(cbo="999999")), PROC, nova)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", motivo)


def test_sem_linha_de_selecao_a_vigencia_fica_nao_resolvida(tmp_path: Path) -> None:
    cenario = _trocar_selecao(cenario_base(), PROC, None)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "VIGENCIA_NAO_RESOLVIDA")


def test_mes_requerido_ausente_nunca_usa_o_mes_vizinho(tmp_path: Path) -> None:
    linha = registro(cbo="999999", competencia_atendimento="202002")
    nova = selecao(LINHA, PROC, "AUSENTE", artefatos="", competencia="202002")
    cenario = _trocar_selecao(cenario_base(linha), PROC, nova)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "ARQUIVO_AUSENTE")


def test_auxiliar_nao_fornecido_e_arquivo_ausente(tmp_path: Path) -> None:
    cenario = cenario_base().com(auxiliares_omitidos=frozenset({"sigtap_proc_ocupacao.v1"}))
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "ARQUIVO_AUSENTE")


def test_auxiliar_sem_coluna_do_requisito_e_leiaute_incompativel(tmp_path: Path) -> None:
    ausentes = {"sigtap_proc_ocupacao.v1": frozenset({"co_ocupacao"})}
    cenario = cenario_base().com(colunas_ausentes_auxiliar=ausentes)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "LEIAUTE_INCOMPATIVEL")


def test_versao_selecionada_fora_do_conjunto_carregado_e_arquivo_ausente(tmp_path: Path) -> None:
    nova = selecao(LINHA, PROC, artefatos="art_" + "e" * 64)
    cenario = _trocar_selecao(cenario_base(), PROC, nova)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, PROC)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "ARQUIVO_AUSENTE")


def test_politica_nao_resolvida_se_abstem_sem_violacao(tmp_path: Path) -> None:
    cenario = coerente(cenario_base(registro(cbo="999999")).com(politica=politica(MetodoId.M_TEMP)))
    avaliacoes = avaliacoes_por_chave(executar(tmp_path, cenario))
    assert {a["estado"] for a in avaliacoes.values()} == {"INCONCLUSIVO"}
    assert all("POLITICA_NAO_RESOLVIDA" in a["motivos"] for a in avaliacoes.values())


def _snapshot(*selecoes: SelecaoVersao) -> SnapshotSet:
    artefatos = tuple(sorted({a for s in selecoes for a in s.artifact_ids}))
    return SnapshotSet.criar(
        artifact_ids=artefatos, observation_ids=(), dataset_hashes=(), selecoes=selecoes
    )


def _selecao_snapshot(fonte: FamiliaFonte, artefato: str, competencia: str) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=fonte,
        base=BaseTemporal.ATENDIMENTO,
        competencia_requerida=CompetenciaArquivo(competencia),
        estado=EstadoSelecao.SELECIONADA,
        artifact_ids=(artefato,),
        motivo="selecao_sintetica",
    )


def test_selecao_derivada_do_snapshot_por_correspondencia_exata(tmp_path: Path) -> None:
    snapshot = _snapshot(
        _selecao_snapshot(FamiliaFonte.SIGTAP, ART_SIGTAP, "202001"),
        _selecao_snapshot(FamiliaFonte.CNES_PF, ART_CNES, "202001"),
    )
    vizinho = registro(1, competencia_atendimento="202002")
    resultado = executar(
        tmp_path, cenario_base(registro(), vizinho), snapshot=snapshot, derivar_selecao=True
    )
    avaliacoes = avaliacoes_por_chave(resultado)
    assert {avaliacoes[(LINHA, r)]["estado"] for r in REGRAS} == {"CONFORME"}
    assert {avaliacoes[(vizinho["row_id"], r)]["motivos"] for r in REGRAS} == {"ARQUIVO_AUSENTE"}


def test_snapshot_com_selecao_repetida_e_falha_operacional(tmp_path: Path) -> None:
    repetida = _selecao_snapshot(FamiliaFonte.SIGTAP, ART_SIGTAP, "202001")
    outra = _selecao_snapshot(FamiliaFonte.SIGTAP, "art_" + "c" * 64, "202001")
    resultado = executar(
        tmp_path, cenario_base(), snapshot=_snapshot(repetida, outra), derivar_selecao=True
    )
    assert resultado.estado is EstadoExecucao.FALHOU
    assert tabela(resultado, "avaliacoes.v1") == []
    assert tabela(resultado, "falhas.v1")[0]["etapa"] == "carregar_insumos"


def test_selecao_com_chave_repetida_e_falha_operacional(tmp_path: Path) -> None:
    cenario = cenario_base()
    cenario = cenario.com(selecoes=(*cenario.selecoes, cenario.selecoes[0]))
    resultado = executar(tmp_path, cenario)
    assert resultado.estado is EstadoExecucao.FALHOU
    assert resultado.falhas == 1


def test_falha_de_programa_nao_vira_inconclusivo(tmp_path: Path) -> None:
    cenario = cenario_base()
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    corrompido = next(r for r in insumos.auxiliares if r.schema_id == "sigtap_procedimento.v1")
    Path(corrompido.caminho).write_bytes(b"isto nao e parquet")
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.PARCIAL
    falhas = tabela(resultado, "falhas.v1")
    assert [(f["etapa"], f["rule_id"]) for f in falhas] == [
        ("avaliar_regra", "VIGENCIA_PROCEDIMENTO_SIGTAP")
    ]
    regras = {a["rule_id"] for a in tabela(resultado, "avaliacoes.v1")}
    assert "VIGENCIA_PROCEDIMENTO_SIGTAP" not in regras
    assert tabela(resultado, "agregados_registro.v1") == []


def test_violacao_permanece_alerta_mesmo_com_outra_regra_inconclusiva(tmp_path: Path) -> None:
    vigencia = "VIGENCIA_PROCEDIMENTO_SIGTAP"
    nova = selecao(LINHA, vigencia, "AUSENTE", artefatos="")
    cenario = _trocar_selecao(cenario_base(registro(cbo="999999")), vigencia, nova)
    agregado = tabela(executar(tmp_path, cenario), "agregados_registro.v1")[0]
    assert agregado["resultado"] == "ALERTA"
    assert agregado["violacoes"] == "ESTAB_CBO_CNES;PROC_CBO_SIGTAP"
    assert agregado["inconclusivas"] == vigencia


@pytest.mark.parametrize(
    ("linha", "esperado"),
    [
        (registro(), "SEM_VIOLACAO_VERIFICADA"),
        (registro(cnes="7654321"), "ABSTENCAO"),
        (registro(instrumento="Z"), "ABSTENCAO"),
    ],
)
def test_agregacao_sem_violacao_nunca_e_aprovado(
    tmp_path: Path, linha: dict[str, str | None], esperado: str
) -> None:
    agregado = tabela(executar(tmp_path, cenario_base(linha)), "agregados_registro.v1")[0]
    assert agregado["resultado"] == esperado


def test_juncoes_n_para_n_e_linhas_repetidas_nao_multiplicam_avaliacoes(tmp_path: Path) -> None:
    cenario = cenario_base(registro(0), registro(1), registro(2, cbo="999999"))
    repetidos = {nome: linhas * 5 for nome, linhas in cenario.auxiliares.items()}
    resultado = executar(tmp_path, cenario.com(auxiliares=repetidos))
    avaliacoes = tabela(resultado, "avaliacoes.v1")
    assert len(avaliacoes) == 3 * len(REGRAS)
    assert len({(a["row_id"], a["rule_id"]) for a in avaliacoes}) == len(avaliacoes)
    assert avaliacoes_por_chave(resultado)[(registro(2)["row_id"], PROC)]["estado"] == "VIOLACAO"


def test_saidas_seguem_os_esquemas_e_tem_hash_logico_conferivel(tmp_path: Path) -> None:
    resultado = executar(tmp_path, cenario_base(registro(0), registro(1, cbo="999999")))
    colunas = {
        "avaliacoes.v1": COLUNAS_AVALIACOES,
        "evidencias.v1": COLUNAS_EVIDENCIAS,
        "agregados_registro.v1": COLUNAS_AGREGADOS,
        "selecao_versoes.v1": COLUNAS_SELECOES,
        "falhas.v1": COLUNAS_FALHAS,
    }
    assert {ref.schema_id for ref in resultado.saidas} == set(colunas)
    con = duckdb.connect()
    for ref in resultado.saidas:
        esquema = carregar_esquema(ref.schema_id)
        assert tuple(c.nome for c in esquema.colunas) == colunas[ref.schema_id]
        con.execute(
            "CREATE OR REPLACE TABLE t AS SELECT * FROM read_parquet($c)", {"c": ref.caminho}
        )
        assert hash_logico_relacao(con, "t", colunas[ref.schema_id]) == ref.hash_logico
    assert resultado.origem_dados is OrigemDados.SINTETICO
    gravado = Path(saida(resultado, "avaliacoes.v1")).parent / "run_result.json"
    assert RunResult.model_validate_json(gravado.read_text(encoding="utf-8")) == resultado


def test_evidencia_de_violacao_sustenta_ausencia(tmp_path: Path) -> None:
    resultado = executar(tmp_path, cenario_base(registro(cbo="999999")))
    evidencias = {e["evidence_id"]: e for e in tabela(resultado, "evidencias.v1")}
    violacoes = [a for a in tabela(resultado, "avaliacoes.v1") if a["estado"] == "VIOLACAO"]
    assert violacoes
    for avaliacao in violacoes:
        linha = evidencias[avaliacao["evidence_ids"]]
        evidencia = Evidence.model_validate(
            linha
            | {
                "parametros": json.loads(linha["parametros"]),
                "artifact_ids": tuple(linha["artifact_ids"].split(";")),
                "chaves_amostra": (),
            }
        )
        assert evidencia.sustenta_ausencia
