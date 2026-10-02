from collections import Counter
from itertools import product

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sustemporal.contracts.base import DocRef, FamiliaFonte
from sustemporal.contracts.rules import (
    AgregadoRegistro,
    Aplicabilidade,
    CatalogoFamilias,
    EstadoAvaliacao,
    EstadoRegra,
    FamiliaCandidata,
    FamiliaRegra,
    MotivoInconclusao,
    RequisitoFonte,
    ResultadoRegistro,
    RuleEvaluation,
    RuleSpec,
    UnidadeAvaliacao,
    decidir_estado,
)
from sustemporal.contracts.temporal import BaseTemporal, EstadoSelecao, MetodoId, SelecaoVersao

_A = f"art_{'a' * 64}"
_B = f"art_{'b' * 64}"
_ROW = f"{_A}#0"
_COMBINACOES = list(
    product(
        Aplicabilidade,
        (True, False),
        (True, False, None),
        ((), (MotivoInconclusao.ARQUIVO_AUSENTE,)),
    )
)
_NOMES_COMBINACAO = ("aplicabilidade", "completos", "incompatibilidade", "motivos")
_ARTEFATOS_POR_ESTADO = {
    EstadoSelecao.SELECIONADA: (_A,),
    EstadoSelecao.AMBIGUA: (_A, _B),
    EstadoSelecao.AUSENTE: (),
    EstadoSelecao.INCOMPLETA: (_A,),
    EstadoSelecao.EM_QUARENTENA: (_A,),
    EstadoSelecao.FORA_DO_CORTE: (),
    EstadoSelecao.NAO_RESOLVIDA: (),
}
_PARAMETROS_POR_ESTADO: dict[EstadoAvaliacao, dict[str, object]] = {
    EstadoAvaliacao.VIOLACAO: {},
    EstadoAvaliacao.CONFORME: {"incompatibilidade_demonstrada": False},
    EstadoAvaliacao.INCONCLUSIVO: {
        "aplicabilidade": Aplicabilidade.DESCONHECIDA,
        "motivos": (MotivoInconclusao.APLICABILIDADE_DESCONHECIDA,),
    },
    EstadoAvaliacao.NAO_APLICAVEL: {"aplicabilidade": Aplicabilidade.NAO_APLICAVEL_DEMONSTRADA},
}


def _esperado(
    aplicabilidade: Aplicabilidade,
    completos: bool,
    incompatibilidade: bool | None,
    motivos: tuple[MotivoInconclusao, ...],
) -> EstadoAvaliacao:
    if aplicabilidade is Aplicabilidade.NAO_APLICAVEL_DEMONSTRADA:
        return EstadoAvaliacao.NAO_APLICAVEL
    verificavel = aplicabilidade is Aplicabilidade.APLICAVEL and completos and not motivos
    if verificavel and incompatibilidade is True:
        return EstadoAvaliacao.VIOLACAO
    if verificavel and incompatibilidade is False:
        return EstadoAvaliacao.CONFORME
    return EstadoAvaliacao.INCONCLUSIVO


def _selecao(estado: EstadoSelecao = EstadoSelecao.SELECIONADA) -> SelecaoVersao:
    return SelecaoVersao(
        fonte=FamiliaFonte.CNES_PF,
        base=BaseTemporal.PROCESSAMENTO,
        competencia_requerida="201801",
        estado=estado,
        artifact_ids=_ARTEFATOS_POR_ESTADO[estado],
        motivo="criterio_documentado",
    )


def _avaliacao(estado: EstadoAvaliacao, **campos: object) -> RuleEvaluation:
    base = {
        "run_id": "run_1",
        "row_id": _ROW,
        "rule_id": "REGRA_A",
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
    return RuleEvaluation.model_validate(base | campos)


def _avaliacao_no_estado(estado: EstadoAvaliacao, rule_id: str = "REGRA_A") -> RuleEvaluation:
    return _avaliacao(estado, rule_id=rule_id, **_PARAMETROS_POR_ESTADO[estado])


def _construivel(estado: EstadoAvaliacao, combinacao: tuple) -> bool:
    aplicabilidade, completos, incompatibilidade, motivos = combinacao
    try:
        _avaliacao(
            estado,
            aplicabilidade=aplicabilidade,
            insumos_completos=completos,
            incompatibilidade_demonstrada=incompatibilidade,
            motivos=motivos,
        )
    except ValidationError:
        return False
    return True


def _docref() -> DocRef:
    return DocRef(
        doc_id="sigtap_cbo", titulo="SIGTAP", estado="PENDENTE", proveniencia="SECUNDARIA"
    )


def _requisito() -> RequisitoFonte:
    return RequisitoFonte(fonte=FamiliaFonte.CNES_PF, schema_id="cnes_pf.v1", campos=("cbo",))


def _regra(**campos: object) -> RuleSpec:
    base = {
        "rule_id": "ESTAB_CBO_001",
        "familia": FamiliaRegra.ESTABELECIMENTO_CBO,
        "versao": "0.1.0",
        "estado": EstadoRegra.CANDIDATA_PRE_G0,
        "descricao": "estabelecimento possui CBO",
        "instrumentos": ("BPA_C",),
        "condicao_aplicabilidade": "instrumento_bpa_c",
        "unidade_avaliacao": UnidadeAvaliacao.ESTABELECIMENTO_CBO,
        "campos_necessarios": ("cnes", "cbo"),
        "requisitos_fonte": (_requisito(),),
        "politica_id": "pol_1",
        "referencia": _docref(),
    }
    return RuleSpec.model_validate(base | campos)


def _familia(familia: FamiliaRegra, **campos: object) -> FamiliaCandidata:
    base = {
        "familia": familia,
        "estado": EstadoRegra.CANDIDATA_PRE_G0,
        "descricao": "familia",
        "instrumentos": ("BPA_I",),
        "unidade_avaliacao": UnidadeAvaliacao.OCORRENCIA,
        "requisitos_fonte": (_requisito(),),
        "referencia": _docref(),
    }
    return FamiliaCandidata.model_validate(base | campos)


def _resultado_esperado(estados: list[EstadoAvaliacao]) -> ResultadoRegistro:
    if EstadoAvaliacao.VIOLACAO in estados:
        return ResultadoRegistro.ALERTA
    if EstadoAvaliacao.INCONCLUSIVO in estados or EstadoAvaliacao.CONFORME not in estados:
        return ResultadoRegistro.ABSTENCAO
    return ResultadoRegistro.SEM_VIOLACAO_VERIFICADA


@pytest.mark.parametrize(_NOMES_COMBINACAO, _COMBINACOES)
def test_decidir_estado_segue_a_tabela_verdade(
    aplicabilidade: Aplicabilidade,
    completos: bool,
    incompatibilidade: bool | None,
    motivos: tuple[MotivoInconclusao, ...],
) -> None:
    esperado = _esperado(aplicabilidade, completos, incompatibilidade, motivos)
    assert decidir_estado(aplicabilidade, completos, incompatibilidade, motivos) is esperado


def test_tabela_verdade_tem_uma_unica_celula_de_violacao() -> None:
    contagem = Counter(decidir_estado(*combinacao) for combinacao in _COMBINACOES)
    assert contagem == {
        EstadoAvaliacao.VIOLACAO: 1,
        EstadoAvaliacao.CONFORME: 1,
        EstadoAvaliacao.NAO_APLICAVEL: 12,
        EstadoAvaliacao.INCONCLUSIVO: 22,
    }


@pytest.mark.parametrize("motivo", list(MotivoInconclusao))
def test_qualquer_motivo_de_inconclusao_impede_violacao(motivo: MotivoInconclusao) -> None:
    estado = decidir_estado(Aplicabilidade.APLICAVEL, True, True, iter([motivo]))
    assert estado is EstadoAvaliacao.INCONCLUSIVO


@pytest.mark.parametrize(_NOMES_COMBINACAO, _COMBINACOES)
def test_avaliacao_so_aceita_o_estado_da_tabela(
    aplicabilidade: Aplicabilidade,
    completos: bool,
    incompatibilidade: bool | None,
    motivos: tuple[MotivoInconclusao, ...],
) -> None:
    combinacao = (aplicabilidade, completos, incompatibilidade, motivos)
    aceitos = {estado for estado in EstadoAvaliacao if _construivel(estado, combinacao)}
    esperado = _esperado(*combinacao)
    sem_motivo = esperado is EstadoAvaliacao.INCONCLUSIVO and not motivos
    assert aceitos == (set() if sem_motivo else {esperado})


@pytest.mark.parametrize(
    "campos",
    [
        {"insumos_completos": False},
        {"aplicabilidade": Aplicabilidade.DESCONHECIDA},
        {"incompatibilidade_demonstrada": None},
        {"motivos": (MotivoInconclusao.CAMPO_INSUFICIENTE,)},
    ],
)
def test_violacao_exige_insumos_completos_e_incompatibilidade_demonstrada(
    campos: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="estado_incoerente"):
        _avaliacao(EstadoAvaliacao.VIOLACAO, **campos)


@pytest.mark.parametrize("estado", [e for e in EstadoSelecao if e is not EstadoSelecao.SELECIONADA])
def test_violacao_exige_todas_as_selecoes_selecionadas(estado: EstadoSelecao) -> None:
    with pytest.raises(ValidationError, match="violacao_sem_insumos_ou_evidencia"):
        _avaliacao(EstadoAvaliacao.VIOLACAO, selecoes=(_selecao(), _selecao(estado)))


@pytest.mark.parametrize("campos", [{"selecoes": ()}, {"evidence_ids": ()}])
def test_violacao_exige_selecao_e_evidencia(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="violacao_sem_insumos_ou_evidencia"):
        _avaliacao(EstadoAvaliacao.VIOLACAO, **campos)


def test_inconclusivo_exige_motivo() -> None:
    with pytest.raises(ValidationError, match="inconclusivo_sem_motivo"):
        _avaliacao(EstadoAvaliacao.INCONCLUSIVO, aplicabilidade=Aplicabilidade.DESCONHECIDA)


def test_falta_de_campo_resulta_em_inconclusivo_e_nunca_em_violacao() -> None:
    campos = {"insumos_completos": False, "motivos": (MotivoInconclusao.CAMPO_INSUFICIENTE,)}
    assert _avaliacao(EstadoAvaliacao.INCONCLUSIVO, **campos).estado is EstadoAvaliacao.INCONCLUSIVO
    with pytest.raises(ValidationError, match="estado_incoerente"):
        _avaliacao(EstadoAvaliacao.VIOLACAO, **campos)


def test_violacao_permanece_alerta_mesmo_com_outra_regra_inconclusiva() -> None:
    avaliacoes = [
        _avaliacao_no_estado(EstadoAvaliacao.INCONCLUSIVO, "REGRA_B"),
        _avaliacao_no_estado(EstadoAvaliacao.VIOLACAO, "REGRA_A"),
    ]
    agregado = AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)
    assert agregado.resultado is ResultadoRegistro.ALERTA
    assert agregado.violacoes == ("REGRA_A",)
    assert agregado.inconclusivas == ("REGRA_B",)


def test_sem_violacao_e_com_inconclusiva_resulta_em_abstencao() -> None:
    avaliacoes = [
        _avaliacao_no_estado(EstadoAvaliacao.CONFORME, "REGRA_A"),
        _avaliacao_no_estado(EstadoAvaliacao.INCONCLUSIVO, "REGRA_B"),
    ]
    agregado = AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)
    assert agregado.resultado is ResultadoRegistro.ABSTENCAO
    assert agregado.conformes == ("REGRA_A",)


@given(st.lists(st.sampled_from(EstadoAvaliacao), max_size=8))
def test_agregacao_prioriza_alerta_depois_abstencao(estados: list[EstadoAvaliacao]) -> None:
    avaliacoes = [_avaliacao_no_estado(e, f"R{i:03d}") for i, e in enumerate(estados)]
    agregado = AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)
    assert agregado.resultado is _resultado_esperado(estados)
    assert len(agregado.violacoes) == estados.count(EstadoAvaliacao.VIOLACAO)
    assert len(agregado.inconclusivas) == estados.count(EstadoAvaliacao.INCONCLUSIVO)
    assert len(agregado.conformes) == estados.count(EstadoAvaliacao.CONFORME)
    assert len(agregado.nao_aplicaveis) == estados.count(EstadoAvaliacao.NAO_APLICAVEL)


@pytest.mark.parametrize(
    "campos",
    [
        {"violacoes": ("REGRA_A",), "resultado": ResultadoRegistro.SEM_VIOLACAO_VERIFICADA},
        {"violacoes": ("REGRA_A",), "inconclusivas": ("R2",), "resultado": "ABSTENCAO"},
        {"inconclusivas": ("REGRA_B",), "resultado": ResultadoRegistro.SEM_VIOLACAO_VERIFICADA},
        {"conformes": ("REGRA_A",), "resultado": ResultadoRegistro.ALERTA},
    ],
)
def test_agregado_rejeita_resultado_incoerente(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="agregado_incoerente"):
        AgregadoRegistro.model_validate({"run_id": "run_1", "row_id": _ROW} | campos)


def test_agregar_rejeita_avaliacao_de_outro_registro() -> None:
    with pytest.raises(ValueError, match="avaliacao_de_outro_registro"):
        AgregadoRegistro.agregar(
            "run_1", f"{_A}#1", [_avaliacao_no_estado(EstadoAvaliacao.CONFORME)]
        )


def test_resultado_do_registro_nunca_e_aprovado() -> None:
    assert {r.value for r in ResultadoRegistro} == {
        "ALERTA",
        "SEM_VIOLACAO_VERIFICADA",
        "ABSTENCAO",
    }
    assert {e.value for e in EstadoAvaliacao} == {
        "CONFORME",
        "VIOLACAO",
        "INCONCLUSIVO",
        "NAO_APLICAVEL",
    }
    with pytest.raises(ValidationError):
        AgregadoRegistro(row_id=_ROW, conformes=("REGRA_A",), resultado="APROVADO")


def test_regra_estabelecimento_cbo_exige_unidade_estabelecimento_cbo() -> None:
    with pytest.raises(ValidationError, match="regra_cadastral_exige_estabelecimento_cbo"):
        _regra(unidade_avaliacao=UnidadeAvaliacao.OCORRENCIA)


def test_regra_de_ocorrencia_e_aceita_fora_da_familia_cadastral() -> None:
    regra = _regra(
        familia=FamiliaRegra.PROCEDIMENTO_CBO, unidade_avaliacao=UnidadeAvaliacao.OCORRENCIA
    )
    assert regra.unidade_avaliacao is UnidadeAvaliacao.OCORRENCIA


@pytest.mark.parametrize("estado", [EstadoRegra.APROVADA_G0, EstadoRegra.CONGELADA])
def test_regra_decidida_exige_decisao_g0(estado: EstadoRegra) -> None:
    with pytest.raises(ValidationError, match="regra_sem_decisao_g0"):
        _regra(estado=estado)


def test_regra_aprovada_g0_aceita_decisao_registrada() -> None:
    aprovada = _regra(estado=EstadoRegra.APROVADA_G0, decisao_g0="experiments/decisions/G0.yaml")
    assert aprovada.decisao_g0 == "experiments/decisions/G0.yaml"


def test_regra_exige_requisito_de_fonte() -> None:
    with pytest.raises(ValidationError, match="regra_sem_requisito_de_fonte"):
        _regra(requisitos_fonte=())


@pytest.mark.parametrize("campos", [{"rule_id": "regra_minuscula"}, {"versao": "1.0"}])
def test_regra_rejeita_identificador_ou_versao_fora_do_padrao(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _regra(**campos)


def test_catalogo_rejeita_familia_repetida() -> None:
    familias = (_familia(FamiliaRegra.PROCEDIMENTO_CBO), _familia(FamiliaRegra.PROCEDIMENTO_CBO))
    with pytest.raises(ValidationError, match="catalogo_familias_repetidas_ou_reservadas"):
        CatalogoFamilias(versao="1", familias=familias)


def test_catalogo_rejeita_familia_ativa_e_reservada() -> None:
    familias = (_familia(FamiliaRegra.PROCEDIMENTO_CBO),)
    with pytest.raises(ValidationError, match="catalogo_familias_repetidas_ou_reservadas"):
        CatalogoFamilias(versao="1", familias=familias, reservadas=(FamiliaRegra.PROCEDIMENTO_CBO,))


def test_catalogo_aceita_familias_distintas_e_reservas_disjuntas() -> None:
    familias = (
        _familia(FamiliaRegra.PROCEDIMENTO_CBO),
        _familia(FamiliaRegra.INSTRUMENTO_REGISTRO),
    )
    catalogo = CatalogoFamilias(versao="1", familias=familias, reservadas=(FamiliaRegra.CID,))
    assert len(catalogo.familias) == 2


def test_familia_candidata_exige_requisito_de_fonte() -> None:
    with pytest.raises(ValidationError):
        _familia(FamiliaRegra.PROCEDIMENTO_CBO, requisitos_fonte=())


def test_familia_candidata_estabelecimento_cbo_exige_unidade_estabelecimento_cbo() -> None:
    with pytest.raises(ValidationError):
        _familia(FamiliaRegra.ESTABELECIMENTO_CBO, unidade_avaliacao=UnidadeAvaliacao.OCORRENCIA)


def test_registro_sem_regra_conforme_e_abstencao() -> None:
    assert AgregadoRegistro.agregar("run_1", _ROW, []).resultado is ResultadoRegistro.ABSTENCAO
    so_nao_aplicavel = [_avaliacao_no_estado(EstadoAvaliacao.NAO_APLICAVEL, "REGRA_A")]
    agregado = AgregadoRegistro.agregar("run_1", _ROW, so_nao_aplicavel)
    assert agregado.resultado is ResultadoRegistro.ABSTENCAO


def test_agregado_registra_a_execucao() -> None:
    assert "run_id" in AgregadoRegistro.model_fields
    violacao = _avaliacao_no_estado(EstadoAvaliacao.VIOLACAO)
    assert AgregadoRegistro.agregar("run_1", _ROW, [violacao]).run_id == "run_1"


def test_agregar_rejeita_avaliacao_de_outra_execucao() -> None:
    assert "run_id" in AgregadoRegistro.model_fields
    conforme = _PARAMETROS_POR_ESTADO[EstadoAvaliacao.CONFORME]
    avaliacoes = [
        _avaliacao_no_estado(EstadoAvaliacao.VIOLACAO, "REGRA_A"),
        _avaliacao(EstadoAvaliacao.CONFORME, rule_id="REGRA_B", run_id="run_2", **conforme),
    ]
    with pytest.raises(ValueError, match="avaliacao_de_outra_execucao"):
        AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)


def test_agregar_rejeita_metodos_ou_politicas_distintos() -> None:
    assert "run_id" in AgregadoRegistro.model_fields
    conforme = _PARAMETROS_POR_ESTADO[EstadoAvaliacao.CONFORME]
    for campo in ({"metodo": MetodoId.B_ATEND}, {"politica_id": "pol_2"}):
        avaliacoes = [
            _avaliacao_no_estado(EstadoAvaliacao.VIOLACAO, "REGRA_A"),
            _avaliacao(EstadoAvaliacao.CONFORME, rule_id="REGRA_B", **conforme, **campo),
        ]
        with pytest.raises(ValueError, match="avaliacoes_de_metodos_distintos"):
            AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)


def test_agregar_rejeita_regra_avaliada_duas_vezes() -> None:
    assert "run_id" in AgregadoRegistro.model_fields
    avaliacoes = [
        _avaliacao_no_estado(EstadoAvaliacao.VIOLACAO, "REGRA_A"),
        _avaliacao_no_estado(EstadoAvaliacao.CONFORME, "REGRA_A"),
    ]
    with pytest.raises(ValueError, match="avaliacao_repetida"):
        AgregadoRegistro.agregar("run_1", _ROW, avaliacoes)
