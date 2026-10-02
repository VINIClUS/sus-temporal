import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sustemporal.contracts.base import DocRef
from sustemporal.contracts.counterfactual import (
    AlvoOperacao,
    Autoridade,
    Candidato,
    CounterfactualSearchResult,
    Executabilidade,
    Governanca,
    Minimalidade,
    MotivoParada,
    OperacaoAplicada,
    OperationSpec,
    Orcamento,
)

_IMUTAVEIS = ["cid", "cid_principal", "cid_secundario", "idade", "sexo", "data_atendimento"]


def _docref() -> DocRef:
    return DocRef(
        doc_id="manual_cnes", titulo="Manual CNES", estado="PENDENTE", proveniencia="SECUNDARIA"
    )


def _operacao(schema_id: str = "cnes_pf.v1", *colunas: str, **campos: object) -> OperationSpec:
    base = {
        "op_id": "op_incluir_cbo",
        "descricao": "incluir CBO no cadastro do estabelecimento",
        "autoridade": Autoridade.ESTABELECIMENTO,
        "governanca": Governanca.MUNICIPAL_DOCUMENTADA,
        "verdade_factual_exigida": "profissional atua com o CBO no estabelecimento",
        "alvo": AlvoOperacao(schema_id=schema_id, colunas=colunas or ("cbo",)),
        "competencias_permitidas": "ABERTAS",
        "alcance": "estabelecimento",
        "custo": 1,
        "referencia": _docref(),
    }
    return OperationSpec.model_validate(base | campos)


def _candidato(custo: int = 1, n_operacoes: int = 1, **campos: object) -> Candidato:
    operacoes = tuple(OperacaoAplicada(op_id=f"op_{i}") for i in range(n_operacoes))
    base = {
        "operacoes": operacoes,
        "custo": custo,
        "resolve_alvo": True,
        "executabilidade": Executabilidade.HIPOTESE_PASSADA,
    }
    return Candidato.model_validate(base | campos)


def _resultado(**campos: object) -> CounterfactualSearchResult:
    base = {
        "bundle_id": "bundle_1",
        "regras_alvo": ("ESTAB_CBO_001",),
        "solucoes": (_candidato(),),
        "minimalidade": Minimalidade.MINIMO_NO_CATALOGO,
        "orcamento": Orcamento(),
        "candidatos_avaliados": 10,
        "custo_max_explorado_completo": 0,
        "motivo_parada": MotivoParada.ESPACO_ESGOTADO,
    }
    return CounterfactualSearchResult.model_validate(base | campos)


@pytest.mark.parametrize("schema_id", ["sia_pa.v1", "sia_pa_bruto.v2", "sia_pa_canonico.v1"])
def test_operacao_nao_altera_fatos_do_atendimento_no_sia_pa(schema_id: str) -> None:
    with pytest.raises(ValidationError, match="operacao_altera_fato_do_atendimento"):
        _operacao(schema_id)


@pytest.mark.parametrize("coluna", _IMUTAVEIS)
def test_operacao_nao_altera_coluna_imutavel(coluna: str) -> None:
    with pytest.raises(ValidationError, match="operacao_altera_coluna_imutavel"):
        _operacao("cnes_pf.v1", coluna)
    with pytest.raises(ValidationError, match="operacao_altera_coluna_imutavel"):
        _operacao("cnes_pf.v1", "cbo", coluna)


@pytest.mark.parametrize(
    ("schema_id", "colunas"),
    [("cnes_pf.v1", ("cbo",)), ("cnes_st.v1", ("tipo_unidade",)), ("cnes_sr.v1", ("servico",))],
)
def test_operacao_cadastral_admissivel_e_aceita(schema_id: str, colunas: tuple[str, ...]) -> None:
    assert _operacao(schema_id, *colunas).alvo.colunas == colunas


@pytest.mark.parametrize("custo", [0, -1])
def test_operacao_exige_custo_positivo(custo: int) -> None:
    with pytest.raises(ValidationError, match="operacao_custo_invalido"):
        _operacao(custo=custo)


@pytest.mark.parametrize("valor", [True, "true"])
def test_operacao_nunca_altera_vinculo_individual(valor: object) -> None:
    with pytest.raises(ValidationError):
        _operacao(altera_vinculo_individual=valor)


def test_operacao_exige_coluna_alvo() -> None:
    with pytest.raises(ValidationError):
        AlvoOperacao(schema_id="cnes_pf.v1", colunas=())


@pytest.mark.parametrize("coluna", ["CID", "Idade", "SEXO"])
def test_operacao_nao_contorna_coluna_imutavel_com_maiusculas(coluna: str) -> None:
    with pytest.raises(ValidationError):
        _operacao("cnes_pf.v1", coluna)


@pytest.mark.parametrize("valor", [True, "true"])
def test_busca_nunca_garante_aprovacao(valor: object) -> None:
    with pytest.raises(ValidationError):
        _resultado(aprovacao_garantida=valor)


def test_busca_valida_declara_aprovacao_nao_garantida() -> None:
    assert _resultado().aprovacao_garantida is False


def test_solucao_deve_resolver_a_regra_alvo() -> None:
    with pytest.raises(ValidationError, match="solucao_nao_revalidada"):
        _resultado(solucoes=(_candidato(resolve_alvo=False),))


def test_solucao_nao_pode_criar_nova_violacao() -> None:
    with pytest.raises(ValidationError, match="solucao_nao_revalidada"):
        _resultado(solucoes=(_candidato(novas_violacoes=("PROC_CBO_002",)),))


def test_candidato_que_cria_violacao_pode_existir_fora_das_solucoes() -> None:
    candidato = _candidato(novas_violacoes=("PROC_CBO_002",), condicoes_pendentes=("local",))
    assert candidato.novas_violacoes == ("PROC_CBO_002",)


def test_minimo_no_catalogo_exige_solucao() -> None:
    with pytest.raises(ValidationError, match="minimo_sem_solucao"):
        _resultado(solucoes=())


@pytest.mark.parametrize(
    ("custos", "explorado", "aceito"),
    [
        ((1,), 0, True),
        ((2,), 1, True),
        ((2,), 0, False),
        ((3,), 1, False),
        ((3,), 2, True),
        ((3, 2), 1, True),
        ((3, 2), 0, False),
    ],
)
def test_minimo_no_catalogo_exige_exploracao_completa_abaixo_do_custo(
    custos: tuple[int, ...], explorado: int, aceito: bool
) -> None:
    solucoes = tuple(_candidato(custo=custo) for custo in custos)
    if aceito:
        assert _resultado(solucoes=solucoes, custo_max_explorado_completo=explorado).solucoes
        return
    with pytest.raises(ValidationError, match="minimo_sem_exploracao_completa"):
        _resultado(solucoes=solucoes, custo_max_explorado_completo=explorado)


@given(custos=st.lists(st.integers(1, 10), min_size=1, max_size=4), explorado=st.integers(0, 10))
def test_minimo_no_catalogo_sse_custos_menores_foram_esgotados(
    custos: list[int], explorado: int
) -> None:
    solucoes = tuple(_candidato(custo=custo) for custo in custos)
    campos = {"solucoes": solucoes, "custo_max_explorado_completo": explorado}
    if explorado >= min(custos) - 1:
        assert _resultado(**campos).minimalidade is Minimalidade.MINIMO_NO_CATALOGO
        return
    with pytest.raises(ValidationError, match="minimo_sem_exploracao_completa"):
        _resultado(**campos)


def test_solucao_sem_prova_de_minimalidade_aceita_exploracao_parcial() -> None:
    resultado = _resultado(
        minimalidade=Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE,
        solucoes=(_candidato(custo=3),),
        motivo_parada=MotivoParada.ORCAMENTO_ESGOTADO,
    )
    assert resultado.custo_max_explorado_completo == 0


def test_busca_rejeita_estouro_de_orcamento_de_candidatos() -> None:
    assert _resultado(candidatos_avaliados=1000).candidatos_avaliados == 1000
    with pytest.raises(ValidationError, match="busca_excedeu_orcamento"):
        _resultado(candidatos_avaliados=1001)
    with pytest.raises(ValidationError, match="busca_excedeu_orcamento"):
        _resultado(orcamento=Orcamento(max_candidatos=5), candidatos_avaliados=6)


def test_busca_inconclusiva_nao_carrega_solucoes() -> None:
    inconclusiva = {"minimalidade": Minimalidade.BUSCA_INCONCLUSIVA}
    with pytest.raises(ValidationError, match="busca_inconclusiva_com_solucao"):
        _resultado(**inconclusiva)
    assert _resultado(solucoes=(), **inconclusiva).solucoes == ()


def test_busca_exige_regra_alvo_e_candidato_exige_operacao() -> None:
    with pytest.raises(ValidationError):
        _resultado(regras_alvo=())
    with pytest.raises(ValidationError):
        _candidato(n_operacoes=0)


def test_solucao_nao_excede_o_maximo_de_operacoes_do_orcamento() -> None:
    with pytest.raises(ValidationError):
        _resultado(solucoes=(_candidato(custo=4, n_operacoes=4),), custo_max_explorado_completo=3)


def test_solucao_sem_prova_de_minimalidade_exige_solucao() -> None:
    with pytest.raises(ValidationError):
        _resultado(minimalidade=Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE, solucoes=())
