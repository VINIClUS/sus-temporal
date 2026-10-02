from itertools import product

import pytest
from pydantic import ValidationError

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte, ValorNormalizado
from sustemporal.contracts.explanation import (
    Afirmacao,
    EstadoCobertura,
    Evidence,
    ExplanationBundle,
    Limitacao,
    TipoEvidencia,
)
from sustemporal.contracts.records import ProductionRecord, RowLocator
from sustemporal.contracts.rules import (
    Aplicabilidade,
    EstadoAvaliacao,
    MotivoInconclusao,
    RuleEvaluation,
)
from sustemporal.contracts.temporal import BaseTemporal, EstadoSelecao, MetodoId, SelecaoVersao

_ART = f"art_{'a' * 64}"
_ART_SELECIONADO = f"art_{'f' * 64}"
_ROW = f"{_ART}#0"
_OUTRA_ROW = f"{_ART}#1"
_PARAMETROS_POR_ESTADO: dict[EstadoAvaliacao, dict[str, object]] = {
    EstadoAvaliacao.VIOLACAO: {},
    EstadoAvaliacao.CONFORME: {"incompatibilidade_demonstrada": False},
    EstadoAvaliacao.INCONCLUSIVO: {
        "insumos_completos": False,
        "incompatibilidade_demonstrada": None,
        "motivos": (MotivoInconclusao.COBERTURA_INSUFICIENTE,),
    },
}
_AUSENCIAS_NAO_SUSTENTADAS = [
    {"cobertura": EstadoCobertura.INSUFICIENTE},
    {"cobertura": EstadoCobertura.AUSENTE},
    {"integridade": EstadoIntegridade.QUARENTENA_TRUNCADO},
    {"integridade": EstadoIntegridade.NAO_VERIFICADO},
]


def _evidencia(evidence_id: str = "ev_ausencia", **campos: object) -> Evidence:
    base = {
        "evidence_id": evidence_id,
        "tipo": TipoEvidencia.AUSENCIA_NA_FONTE,
        "query_id": "q_estabelecimento_cbo",
        "sql_sha256": "b" * 64,
        "parametros": {"cnes": "0012345", "cbo": "225125", "competencia": "201801"},
        "dataset_id": f"ds_{'c' * 64}",
        "hash_logico": f"lh1:{'d' * 64}",
        "artifact_ids": (_ART_SELECIONADO,),
        "cobertura": EstadoCobertura.DISPONIVEL,
        "integridade": EstadoIntegridade.OK,
        "n_resultados": 0,
    }
    return Evidence.model_validate(base | campos)


def _registro(indice: int = 0) -> ProductionRecord:
    origem = RowLocator(artifact_id=_ART, indice=indice)
    instrumento = ValorNormalizado(bruto="BPA_C", valor="BPA_C")
    return ProductionRecord(row_id=origem.row_id(), origem=origem, instrumento=instrumento)


def _selecao() -> SelecaoVersao:
    return SelecaoVersao(
        fonte=FamiliaFonte.CNES_PF,
        base=BaseTemporal.PROCESSAMENTO,
        competencia_requerida="201801",
        estado=EstadoSelecao.SELECIONADA,
        artifact_ids=(_ART_SELECIONADO,),
        motivo="criterio_documentado",
    )


def _avaliacao(
    estado: EstadoAvaliacao = EstadoAvaliacao.VIOLACAO, **campos: object
) -> RuleEvaluation:
    base = {
        "run_id": "run_1",
        "row_id": _ROW,
        "rule_id": "ESTAB_CBO_001",
        "versao": "0.1.0",
        "politica_id": "pol_1",
        "metodo": MetodoId.M_TEMP,
        "estado": estado,
        "aplicabilidade": Aplicabilidade.APLICAVEL,
        "insumos_completos": True,
        "incompatibilidade_demonstrada": True,
        "selecoes": (_selecao(),),
        "evidence_ids": ("ev_ausencia",),
    }
    return RuleEvaluation.model_validate(base | _PARAMETROS_POR_ESTADO[estado] | campos)


def _bundle(**campos: object) -> ExplanationBundle:
    base = {
        "bundle_id": "bundle_1",
        "run_id": "run_1",
        "row_id": _ROW,
        "registro": _registro(),
        "avaliacoes": (_avaliacao(),),
        "selecoes": (_selecao(),),
        "evidencias": (_evidencia(),),
        "prov_n": "document\nendDocument",
        "prov_json_sha256": "e" * 64,
        "limitacoes": (
            Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL,
            Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA,
        ),
    }
    return ExplanationBundle.model_validate(base | campos)


def _afirmacao(*referencias: str) -> Afirmacao:
    return Afirmacao(
        texto="Estabelecimento sem o CBO no CNES da competência.",
        template_id="tpl_ausencia_cbo",
        referencias=referencias,
    )


def test_evidencia_de_ausencia_exige_zero_resultados() -> None:
    with pytest.raises(ValidationError, match="ausencia_com_resultados"):
        _evidencia(n_resultados=1)


def test_evidencia_de_vinculo_exige_resultados() -> None:
    with pytest.raises(ValidationError, match="vinculo_sem_resultados"):
        _evidencia(tipo=TipoEvidencia.VINCULO_ENCONTRADO, n_resultados=0)


@pytest.mark.parametrize(
    ("cobertura", "integridade"), list(product(EstadoCobertura, EstadoIntegridade))
)
def test_ausencia_so_e_sustentada_com_cobertura_disponivel_e_integridade_ok(
    cobertura: EstadoCobertura, integridade: EstadoIntegridade
) -> None:
    evidencia = _evidencia(cobertura=cobertura, integridade=integridade)
    esperado = cobertura is EstadoCobertura.DISPONIVEL and integridade is EstadoIntegridade.OK
    assert evidencia.sustenta_ausencia is esperado


@pytest.mark.parametrize(
    ("tipo", "n_resultados"),
    [
        (TipoEvidencia.VINCULO_ENCONTRADO, 1),
        (TipoEvidencia.FONTE_INCOMPLETA, 0),
        (TipoEvidencia.APLICABILIDADE, 0),
        (TipoEvidencia.SELECAO_TEMPORAL, 0),
    ],
)
def test_apenas_evidencia_de_ausencia_sustenta_ausencia(
    tipo: TipoEvidencia, n_resultados: int
) -> None:
    assert _evidencia(tipo=tipo, n_resultados=n_resultados).sustenta_ausencia is False


def test_evidencia_limita_amostra_de_chaves() -> None:
    assert len(_evidencia(chaves_amostra=tuple(f"k{i}" for i in range(20))).chaves_amostra) == 20
    with pytest.raises(ValidationError):
        _evidencia(chaves_amostra=tuple(f"k{i}" for i in range(21)))


def test_explicacao_com_ausencia_sustentada_e_aceita() -> None:
    bundle = _bundle(afirmacoes=(_afirmacao("ev_ausencia", "ESTAB_CBO_001"),))
    assert bundle.causa_oficial_atribuida is False


@pytest.mark.parametrize(
    "limitacoes",
    [(), (Limitacao.AUSENCIA_NAO_PROVA_INEXISTENCIA, Limitacao.RETROSPECTIVO)],
)
def test_explicacao_exige_limitacao_resultado_nao_e_causa_oficial(
    limitacoes: tuple[Limitacao, ...],
) -> None:
    with pytest.raises(ValidationError, match="explicacao_sem_limitacao_de_causa"):
        _bundle(limitacoes=limitacoes)


@pytest.mark.parametrize("valor", [True, "true"])
def test_explicacao_nunca_atribui_causa_oficial(valor: object) -> None:
    with pytest.raises(ValidationError):
        _bundle(causa_oficial_atribuida=valor)


def test_explicacao_rejeita_registro_de_outra_linha() -> None:
    with pytest.raises(ValidationError, match="explicacao_registro_incoerente"):
        _bundle(registro=_registro(indice=1))


@pytest.mark.parametrize("referencia", ["ev_ausencia", "ESTAB_CBO_001", _ART_SELECIONADO])
def test_afirmacao_pode_citar_evidencia_regra_ou_artefato_selecionado(referencia: str) -> None:
    assert _bundle(afirmacoes=(_afirmacao(referencia),)).afirmacoes[0].referencias == (referencia,)


@pytest.mark.parametrize("referencias", [("ev_inexistente",), ("ev_ausencia", "REGRA_FANTASMA")])
def test_afirmacao_com_referencia_que_nao_resolve_e_rejeitada(
    referencias: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="afirmacao_sem_referencia_valida"):
        _bundle(afirmacoes=(_afirmacao(*referencias),))


def test_afirmacao_exige_ao_menos_uma_referencia() -> None:
    with pytest.raises(ValidationError):
        _afirmacao()


def test_violacao_citando_fonte_incompleta_e_rejeitada() -> None:
    incompleta = _evidencia(tipo=TipoEvidencia.FONTE_INCOMPLETA)
    with pytest.raises(ValidationError, match="violacao_sem_ausencia_sustentada"):
        _bundle(evidencias=(incompleta,))


@pytest.mark.parametrize("campos", _AUSENCIAS_NAO_SUSTENTADAS)
def test_violacao_citando_ausencia_nao_sustentada_e_rejeitada(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="violacao_sem_ausencia_sustentada"):
        _bundle(evidencias=(_evidencia(**campos),))


def test_violacao_citando_evidencia_inexistente_e_rejeitada() -> None:
    with pytest.raises(ValidationError, match="violacao_cita_evidencia_ausente"):
        _bundle(evidencias=(_evidencia("ev_outra"),))


def test_violacao_com_uma_evidencia_sustentada_e_outra_incompleta_e_rejeitada() -> None:
    avaliacao = _avaliacao(evidence_ids=("ev_ausencia", "ev_incompleta"))
    incompleta = _evidencia("ev_incompleta", tipo=TipoEvidencia.FONTE_INCOMPLETA)
    with pytest.raises(ValidationError, match="violacao_sem_ausencia_sustentada"):
        _bundle(avaliacoes=(avaliacao,), evidencias=(_evidencia(), incompleta))


@pytest.mark.parametrize(
    "campos", [{"tipo": TipoEvidencia.FONTE_INCOMPLETA}, *_AUSENCIAS_NAO_SUSTENTADAS]
)
def test_conjunto_vazio_sem_cobertura_sustenta_apenas_inconclusao(
    campos: dict[str, object],
) -> None:
    inconclusiva = _avaliacao(EstadoAvaliacao.INCONCLUSIVO)
    bundle = _bundle(avaliacoes=(inconclusiva,), evidencias=(_evidencia(**campos),))
    assert bundle.avaliacoes[0].estado is EstadoAvaliacao.INCONCLUSIVO


def test_explicacao_rejeita_avaliacao_de_outro_registro() -> None:
    with pytest.raises(ValidationError):
        _bundle(avaliacoes=(_avaliacao(row_id=_OUTRA_ROW),))


def test_bundle_rejeita_avaliacao_de_outra_execucao() -> None:
    with pytest.raises(ValidationError, match="explicacao_mistura_execucoes"):
        _bundle(avaliacoes=(_avaliacao(run_id="run_2"),))


def test_evidencia_de_ausencia_exige_limitacao_de_que_ausencia_nao_prova_inexistencia() -> None:
    so_causa = (Limitacao.RESULTADO_NAO_E_CAUSA_OFICIAL,)
    vinculo = _evidencia(tipo=TipoEvidencia.VINCULO_ENCONTRADO, n_resultados=1)
    conforme = _avaliacao(EstadoAvaliacao.CONFORME)
    assert _bundle(avaliacoes=(conforme,), evidencias=(vinculo,), limitacoes=so_causa).limitacoes
    with pytest.raises(ValidationError, match="explicacao_ausencia_sem_limitacao"):
        _bundle(limitacoes=so_causa)


@pytest.mark.parametrize("estado", [EstadoAvaliacao.VIOLACAO, EstadoAvaliacao.INCONCLUSIVO])
def test_evidencia_citada_usa_so_artefatos_das_selecoes_da_avaliacao(
    estado: EstadoAvaliacao,
) -> None:
    de_outra_versao = _evidencia(artifact_ids=(_ART_SELECIONADO, _ART))
    assert _bundle(avaliacoes=(_avaliacao(estado),)).evidencias[0].artifact_ids == (
        _ART_SELECIONADO,
    )
    with pytest.raises(ValidationError, match="evidencia_fora_das_selecoes"):
        _bundle(avaliacoes=(_avaliacao(estado),), evidencias=(de_outra_versao,))


def test_bundle_rejeita_evidencia_repetida() -> None:
    with pytest.raises(ValidationError, match="evidencia_repetida"):
        _bundle(evidencias=(_evidencia(), _evidencia()))
