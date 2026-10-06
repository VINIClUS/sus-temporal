"""Revisão independente do orquestrador no PR #8 (cenários SINTETICOS)."""

from dataclasses import replace
from pathlib import Path

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import DocRef, FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.rules import RuleSpec
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
    MetodoId,
    PoliticaTemporal,
    SelecaoVersao,
    SnapshotSet,
    TipoPolitica,
)
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import (
    CenarioRegras,
    artefato,
    coerente,
    materializar,
    snapshot_vazio,
)
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar, tabela
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIA,
    ART_SIGTAP,
    COMPETENCIA,
    REGRAS,
    cenario_base,
    registro,
    selecao,
)

LINHA = registro()["row_id"]
PROC = "PROC_CBO_SIGTAP"
VIGENCIA = "VIGENCIA_PROCEDIMENTO_SIGTAP"
_SIGTAP = {"artifact_id": ART_SIGTAP, "dt_competencia": COMPETENCIA}
_DOCUMENTO = DocRef(
    doc_id="politica_sintetica", titulo="SINTETICO", estado="PENDENTE", proveniencia="INFERIDA"
)


def _estado(resultado: RunResult, regra: str, linha: str = LINHA) -> tuple[str, str]:
    avaliacao = avaliacoes_por_chave(resultado)[(linha, regra)]
    return avaliacao["estado"], avaliacao["motivos"]


@pytest.mark.parametrize("valor", ["301010072", "0301010072 "])
def test_b1_codigo_auxiliar_fora_do_dominio_e_leiaute_incompativel(
    tmp_path: Path, valor: str
) -> None:
    cenario = cenario_base()
    auxiliares = cenario.auxiliares | {
        "sigtap_procedimento.v1": (_SIGTAP | {"co_procedimento": valor},)
    }
    resultado = executar(tmp_path, cenario.com(auxiliares=auxiliares))
    assert _estado(resultado, VIGENCIA) == ("INCONCLUSIVO", "LEIAUTE_INCOMPATIVEL")


@pytest.mark.parametrize("instrumento", ["C", "Z"])
def test_b2_registro_em_quarentena_tem_aplicabilidade_desconhecida(
    tmp_path: Path, instrumento: str
) -> None:
    cenario = cenario_base(registro(instrumento=instrumento))
    cenario = cenario.com(
        integridade=cenario.integridade | {ART_SIA: EstadoIntegridade.QUARENTENA_LEIAUTE}
    )
    avaliacoes = avaliacoes_por_chave(executar(tmp_path, cenario))
    for regra in REGRAS:
        avaliacao = avaliacoes[(LINHA, regra)]
        assert (avaliacao["estado"], avaliacao["aplicabilidade"]) == (
            "INCONCLUSIVO",
            "DESCONHECIDA",
        )
        assert avaliacao["motivos"] == "APLICABILIDADE_DESCONHECIDA;ARQUIVO_EM_QUARENTENA"


def _snapshot(
    competencia: str = COMPETENCIA, *, base: BaseTemporal = BaseTemporal.ATENDIMENTO
) -> SnapshotSet:
    selecoes = tuple(
        SelecaoVersao(
            fonte=fonte,
            base=base,
            competencia_requerida=CompetenciaArquivo(competencia),
            estado=EstadoSelecao.SELECIONADA,
            artifact_ids=(artefato_,),
            motivo="selecao_sintetica",
        )
        for fonte, artefato_ in (
            (FamiliaFonte.SIGTAP, ART_SIGTAP),
            (FamiliaFonte.CNES_PF, ART_CNES),
        )
    )
    return SnapshotSet.criar(
        artifact_ids=tuple(sorted({ART_SIGTAP, ART_CNES})),
        observation_ids=(),
        dataset_hashes=(),
        selecoes=selecoes,
    )


def _politica_m_temp(
    deslocamento: int = 0,
    tipo: TipoPolitica = TipoPolitica.DOCUMENTADA,
    *,
    base: BaseTemporal = BaseTemporal.ATENDIMENTO,
) -> PoliticaTemporal:
    return PoliticaTemporal(
        politica_id="m_temp_sintetica",
        tipo=tipo,
        metodo=MetodoId.M_TEMP,
        criterios=tuple(
            CriterioTemporal(fonte=f, base=base, deslocamento_meses=deslocamento)
            for f in (FamiliaFonte.CNES_PF, FamiliaFonte.SIGTAP)
        ),
        documento=_DOCUMENTO if tipo is TipoPolitica.DOCUMENTADA else None,
    )


def _regras_com_criterio(
    deslocamento: int, *, base: BaseTemporal = BaseTemporal.ATENDIMENTO
) -> list[RuleSpec]:
    regras = []
    for regra in carregar_regras():
        fonte = next(r.fonte for r in regra.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)
        criterio = CriterioTemporal(fonte=fonte, base=base, deslocamento_meses=deslocamento)
        regras.append(regra.model_copy(update={"criterios_temporais": (criterio,)}))
    return regras


def test_i1_m_temp_sem_criterio_da_regra_se_abstem(tmp_path: Path) -> None:
    cenario = cenario_base(registro(cbo="999999")).com(politica=_politica_m_temp())
    resultado = executar(tmp_path, cenario, snapshot=_snapshot(), derivar_selecao=True)
    avaliacoes = avaliacoes_por_chave(resultado)
    assert {a["estado"] for a in avaliacoes.values()} == {"INCONCLUSIVO"}
    assert {a["motivos"] for a in avaliacoes.values()} == {"VIGENCIA_NAO_RESOLVIDA"}


def test_i1_m_temp_com_criterio_igual_ao_da_regra_avalia(tmp_path: Path) -> None:
    cenario = cenario_base(registro(cbo="999999")).com(politica=_politica_m_temp())
    resultado = executar(
        tmp_path,
        cenario,
        regras=_regras_com_criterio(0),
        snapshot=_snapshot(),
        derivar_selecao=True,
    )
    assert _estado(resultado, PROC) == ("VIOLACAO", "")


def test_i2_competencia_do_conteudo_diferente_da_selecao_e_vigencia_nao_resolvida(
    tmp_path: Path,
) -> None:
    cenario = coerente(cenario_base(registro(competencia_atendimento="201912")))
    resultado = executar(tmp_path, cenario)
    for regra in REGRAS:
        assert _estado(resultado, regra) == ("INCONCLUSIVO", "VIGENCIA_NAO_RESOLVIDA")


def test_i3_deslocamento_escolhe_o_mes_certo(tmp_path: Path) -> None:
    politica = _politica_m_temp(-1, TipoPolitica.ALTERNATIVA_EXPLORATORIA)
    cenario = cenario_base(registro(competencia_atendimento="202002")).com(politica=politica)
    resultado = executar(
        tmp_path,
        cenario,
        regras=_regras_com_criterio(-1),
        snapshot=_snapshot(),
        derivar_selecao=True,
    )
    assert {s["competencia_requerida"] for s in tabela(resultado, "selecao_versoes.v1")} == {
        COMPETENCIA
    }
    assert {_estado(resultado, regra)[0] for regra in REGRAS} == {"CONFORME"}


@pytest.mark.parametrize(
    ("base", "atendimento", "processamento"),
    [
        (BaseTemporal.ATENDIMENTO, "202002", COMPETENCIA),
        (BaseTemporal.PROCESSAMENTO, COMPETENCIA, "202002"),
    ],
)
def test_c1_ausencia_no_mes_deslocado_nao_vira_violacao_pela_cobertura_de_q(
    tmp_path: Path, base: BaseTemporal, atendimento: str, processamento: str
) -> None:
    """Deslocamento -1 consulta 202001; a matriz só tem a chave Q(r) e não certifica esse mês."""
    linha = registro(
        cbo="999999", competencia_atendimento=atendimento, competencia_processamento=processamento
    )
    cenario = cenario_base(linha)
    cobertura = tuple(
        dict(c) | {"competencia": processamento, "base_temporal": str(base)}
        for c in cenario.cobertura or ()
    )
    cenario = cenario.com(politica=_politica_m_temp(-1, base=base), cobertura=cobertura)
    resultado = executar(
        tmp_path,
        cenario,
        regras=_regras_com_criterio(-1, base=base),
        snapshot=_snapshot(base=base),
        derivar_selecao=True,
    )
    assert {s["competencia_requerida"] for s in tabela(resultado, "selecao_versoes.v1")} == {
        COMPETENCIA
    }
    for regra in (PROC, "ESTAB_CBO_CNES"):
        assert _estado(resultado, regra) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_i3_cobertura_e_consultada_pela_competencia_de_processamento(tmp_path: Path) -> None:
    linha = registro(cbo="999999", competencia_processamento="202002")
    cenario = cenario_base(linha)
    cobertura = tuple(dict(c) | {"competencia": "202002"} for c in cenario.cobertura or ())
    resultado = executar(tmp_path, cenario.com(cobertura=cobertura))
    assert _estado(resultado, PROC) == ("VIOLACAO", "")


def test_i3_quarentena_de_uma_de_duas_versoes_selecionadas(tmp_path: Path) -> None:
    segunda = artefato(4)
    cenario = cenario_base()
    ocupacoes = cenario.auxiliares["sigtap_proc_ocupacao.v1"]
    extra = tuple(dict(o) | {"artifact_id": segunda} for o in ocupacoes)
    selecoes = tuple(
        selecao(str(s["row_id"]), PROC, artefatos=f"{ART_SIGTAP};{segunda}")
        if s["rule_id"] == PROC
        else s
        for s in cenario.selecoes
    )
    cenario = cenario.com(
        auxiliares=cenario.auxiliares | {"sigtap_proc_ocupacao.v1": ocupacoes + extra},
        selecoes=selecoes,
        integridade=cenario.integridade | {segunda: EstadoIntegridade.QUARENTENA_CHECKSUM},
    )
    assert _estado(executar(tmp_path, cenario), PROC) == ("INCONCLUSIVO", "ARQUIVO_EM_QUARENTENA")


def test_i3_m_temp_padrao_nunca_cai_para_atendimento(tmp_path: Path) -> None:
    cenario: CenarioRegras = cenario_base(registro(cbo="999999"))
    config = RunConfig(versao="1", metodos=(MetodoId.M_TEMP,))
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    insumos = replace(insumos, selecoes=None, politica=None)
    resultado = evaluate_rules(
        dataset, _snapshot(), carregar_regras(), config, tmp_path / "s", insumos=insumos
    )
    avaliacoes = avaliacoes_por_chave(resultado)
    assert resultado.metodo is MetodoId.M_TEMP
    assert "VIOLACAO" not in {a["estado"] for a in avaliacoes.values()}
    assert all("POLITICA_NAO_RESOLVIDA" in a["motivos"] for a in avaliacoes.values())


def test_i3_procedimento_do_registro_com_nove_digitos_e_campo_insuficiente(tmp_path: Path) -> None:
    resultado = executar(tmp_path, cenario_base(registro(procedimento="301010072")))
    for regra in ("PROC_CBO_SIGTAP", "INSTRUMENTO_REGISTRO_SIGTAP", VIGENCIA):
        assert _estado(resultado, regra) == ("INCONCLUSIVO", "CAMPO_INSUFICIENTE")


@pytest.mark.parametrize("instrumento", ["", "c", "CC"])
def test_i5_instrumento_fora_do_dominio_conta_como_nulo(tmp_path: Path, instrumento: str) -> None:
    resultado = executar(tmp_path, cenario_base(registro(instrumento=instrumento)))
    for regra in REGRAS:
        assert _estado(resultado, regra) == (
            "INCONCLUSIVO",
            "APLICABILIDADE_DESCONHECIDA;CAMPO_INSUFICIENTE",
        )


def test_s1_estado_de_selecao_fora_do_dominio_e_falha_de_conferencia(tmp_path: Path) -> None:
    cenario = cenario_base()
    selecoes = tuple(dict(s) | {"estado": "SELECIONADO"} for s in cenario.selecoes)
    resultado = executar(tmp_path, cenario.com(selecoes=selecoes))
    assert resultado.estado is EstadoExecucao.FALHOU
    assert tabela(resultado, "falhas.v1")[0]["etapa"] == "conferir_selecao"


@pytest.mark.parametrize(
    ("schema_id", "linha"),
    [
        (
            "sigtap_proc_ocupacao.v1",
            _SIGTAP | {"co_procedimento": "0301010072", "co_ocupacao": "225125 "},
        ),
        (
            "cnes_estab_cbo.v1",
            {
                "artifact_id": ART_CNES,
                "competencia_arquivo": COMPETENCIA,
                "cnes": "1234567",
                "cbo": "225125 ",
                "n_vinculos": 1,
            },
        ),
    ],
)
def test_b1_cbo_auxiliar_com_espaco_e_leiaute_incompativel(
    tmp_path: Path, schema_id: str, linha: dict[str, object]
) -> None:
    cenario = cenario_base()
    cenario = cenario.com(auxiliares=cenario.auxiliares | {schema_id: (linha,)})
    regra = PROC if schema_id.startswith("sigtap") else "ESTAB_CBO_CNES"
    assert _estado(executar(tmp_path, cenario), regra) == ("INCONCLUSIVO", "LEIAUTE_INCOMPATIVEL")


def _rotular(ref: DatasetRef, schema_id: str) -> DatasetRef:
    return ref.model_copy(
        update={
            "schema_id": schema_id,
            "dataset_id": calcular_dataset_id(schema_id, ref.hash_logico, ref.artifact_ids),
        }
    )


@pytest.mark.parametrize("insumo", ["cobertura", "selecoes"])
def test_insumo_com_schema_inesperado_e_falha_de_carga(tmp_path: Path, insumo: str) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    original = getattr(insumos, insumo)
    insumos = replace(insumos, **{insumo: _rotular(original, "sia_pa.v1")})
    resultado = evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        tmp_path / "s",
        insumos=insumos,
    )
    assert resultado.estado is EstadoExecucao.FALHOU
    falha = tabela(resultado, "falhas.v1")[0]
    assert (falha["etapa"], "schema_inesperado" in falha["erro"]) == ("carregar_insumos", True)


@pytest.mark.parametrize("artefato_linha", [None, "outro"])
def test_linhagem_do_registro_nula_ou_incoerente_e_falha_de_carga(
    tmp_path: Path, artefato_linha: str | None
) -> None:
    valor = artefato(5) if artefato_linha == "outro" else None
    resultado = executar(tmp_path, cenario_base(registro(artifact_id=valor)))
    assert resultado.estado is EstadoExecucao.FALHOU
    falha = tabela(resultado, "falhas.v1")[0]
    assert (falha["etapa"], "linhagem_incoerente" in falha["erro"]) == ("carregar_insumos", True)
