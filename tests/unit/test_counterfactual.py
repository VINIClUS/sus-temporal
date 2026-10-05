"""Busca de contrafactuais (T09) sobre mundos SINTETICOS; nada aqui é resultado empírico."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pytest
from hypothesis import HealthCheck, given, settings

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.config import OrcamentoContrafactual, RunConfig
from sustemporal.contracts.counterfactual import (
    AlvoOperacao,
    Executabilidade,
    Governanca,
    Minimalidade,
    MotivoParada,
)
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.explanation import counterfactual_sobreposicao
from sustemporal.explanation.counterfactual import pioras, search_counterfactuals
from sustemporal.explanation.counterfactual_operacoes import (
    CatalogoOperacoesInvalido,
    Instancia,
    carregar_operacoes,
    ordem_de_aplicacao,
    validar_operacoes,
)
from sustemporal.explanation.counterfactual_sobreposicao import (
    InsumoCadastralInvalido,
    RevalidacaoFalhou,
)
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.contrafactual_cenario import (
    CBO_ALVO,
    CBO_OUTRO,
    CBO_TERCEIRO,
    OpcoesST,
    montar,
    operacao,
)
from tests.fixtures.contrafactual_oraculo import (
    Sorteio,
    mundos_pequenos,
    n_instancias,
    solucoes_minimas,
)
from tests.fixtures.contrafactual_texto import afirmacoes_proibidas
from tests.fixtures.regras_cenario import artefato
from tests.fixtures.regras_exemplos import COMPETENCIA

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts.counterfactual import CounterfactualSearchResult, OperationSpec
    from sustemporal.contracts.experiment import RunResult
    from sustemporal.contracts.rules import RuleSpec
    from tests.fixtures.contrafactual_cenario import Mundo

_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"
_RECLASSIFICAR = "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO"
_CADASTRAR = "CADASTRAR_ESTABELECIMENTO_NO_CNES"
_RAIZ = Path(__file__).resolve().parents[2]
_POTENCIAL = Executabilidade.POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES


def _em(ano: int, mes: int) -> Callable[[], datetime]:
    return lambda: datetime(ano, mes, 15, 12, 0, tzinfo=UTC)


def _config(max_operacoes: int = 3, max_candidatos: int = 1000) -> RunConfig:
    orcamento = OrcamentoContrafactual(max_operacoes=max_operacoes, max_candidatos=max_candidatos)
    return RunConfig(versao="1", contrafactual=orcamento)


def _buscar(
    mundo: Mundo,
    config: RunConfig | None = None,
    *,
    operacoes: tuple[OperationSpec, ...] | None = None,
) -> CounterfactualSearchResult:
    return search_counterfactuals(
        mundo.bundle, config or _config(), contexto=mundo.contexto, operacoes=operacoes
    )


def _documentada(autoridade: str = "ESTABELECIMENTO") -> OperationSpec:
    return operacao(_INCLUIR, 1, autoridade=autoridade, governanca="MUNICIPAL_DOCUMENTADA")


Passo = tuple[str, tuple[tuple[str, str], ...]]


def _ops(resultado: CounterfactualSearchResult) -> list[list[Passo]]:
    return [
        [(o.op_id, tuple(sorted(o.parametros.items()))) for o in s.operacoes]
        for s in resultado.solucoes
    ]


def _nomes(resultado: CounterfactualSearchResult) -> list[list[str]]:
    return [[op for op, _ in s] for s in _ops(resultado)]


def test_solucao_de_uma_operacao(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    resultado = _buscar(mundo)
    assert _nomes(resultado) == [[_INCLUIR]]
    solucao = resultado.solucoes[0]
    assert solucao.custo == 1
    assert str(solucao.operacoes[0].competencia) == "202001"
    assert "ESTAB_CBO_CNES" in solucao.regras_revalidadas
    restrita = f"revalidacao_restrita dataset={mundo.contexto.dataset.dataset_id}"
    assert restrita in solucao.condicoes_pendentes
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO
    assert resultado.motivo_parada is MotivoParada.MINIMO_ENCONTRADO
    assert resultado.custo_max_explorado_completo == 1
    assert resultado.aprovacao_garantida is False


def test_dependencia_entre_operacoes(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    resultado = _buscar(mundo)
    assert _nomes(resultado) == [[_CADASTRAR, _INCLUIR]]
    assert resultado.solucoes[0].custo == 4
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO


def test_dependencia_nunca_vem_depois_de_quem_depende(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    catalogo = (operacao(_INCLUIR, 1), operacao(_CADASTRAR, 1))
    assert _nomes(_buscar(mundo, operacoes=catalogo)) == [[_CADASTRAR, _INCLUIR]]


def test_ordem_de_aplicacao_segue_dependencias_e_nao_o_alfabeto() -> None:
    incluir = Instancia(_INCLUIR, (("cbo", CBO_ALVO),))
    reclassificar = Instancia(_RECLASSIFICAR, (("cbo_origem", CBO_OUTRO),))
    nivel = {_RECLASSIFICAR: 0, _INCLUIR: 1}
    assert ordem_de_aplicacao([incluir, reclassificar], nivel) == [reclassificar, incluir]


def test_violacao_nova(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, outros=((CBO_OUTRO, "C"),))
    resultado = _buscar(mundo, operacoes=(operacao(_RECLASSIFICAR, 1),))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 1
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA
    assert resultado.motivo_parada is MotivoParada.ESPACO_ESGOTADO


def test_reclassificacao_sem_violacao_nova_e_solucao(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, outros=((CBO_OUTRO, "C"),))
    resultado = _buscar(mundo, operacoes=(operacao(_RECLASSIFICAR, 1),))
    parametros = (("cbo", CBO_ALVO), ("cbo_origem", CBO_OUTRO), ("cnes", "1234567"))
    assert _ops(resultado) == [[(_RECLASSIFICAR, parametros)]]


def test_reclassificacao_usa_o_total_do_par_em_linhas_repetidas(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: (1, 1)}, outros=((CBO_OUTRO, "C"),))
    resultado = _buscar(mundo, operacoes=(operacao(_RECLASSIFICAR, 1),))
    assert _nomes(resultado) == [[_RECLASSIFICAR]]
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO


def test_revalida_regra_nao_alvo_afetada(tmp_path: Path) -> None:
    regras = carregar_regras()
    alvo = next(r for r in regras if r.rule_id == "ESTAB_CBO_CNES")
    so_c = alvo.model_copy(update={"instrumentos": ("C",)})
    so_i = alvo.model_copy(update={"rule_id": "ESTAB_CBO_CNES_I", "instrumentos": ("I",)})
    outras = [r for r in regras if r.rule_id != "ESTAB_CBO_CNES"]
    mundo = montar(
        tmp_path, pf={CBO_OUTRO: 1}, outros=((CBO_OUTRO, "I"),), regras=(so_c, so_i, *outras)
    )
    resultado = _buscar(mundo, operacoes=(operacao(_RECLASSIFICAR, 1),))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 1


def _com_irma() -> tuple[RuleSpec, ...]:
    regras = carregar_regras()
    alvo = next(r for r in regras if r.rule_id == "ESTAB_CBO_CNES")
    return (*regras, alvo.model_copy(update={"rule_id": "ESTAB_CBO_CNES_IRMA"}))


def test_regras_revalidadas_incluem_todas_as_afetadas(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, regras=_com_irma())
    revalidadas = set(_buscar(mundo).solucoes[0].regras_revalidadas)
    assert {"ESTAB_CBO_CNES", "ESTAB_CBO_CNES_IRMA"} <= revalidadas
    assert "VIGENCIA_PROCEDIMENTO_SIGTAP" not in revalidadas


def test_regras_alvo_em_competencias_diferentes_nao_tem_operacao_admissivel(
    tmp_path: Path,
) -> None:
    alvos = (("ESTAB_CBO_CNES", COMPETENCIA), ("ESTAB_CBO_CNES_IRMA", "202002"))
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, regras=_com_irma(), alvos=alvos)
    resultado = _buscar(mundo)
    assert resultado.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA


def test_competencia_fechada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202610")
    solucao = _buscar(mundo, operacoes=(_documentada(),)).solucoes[0]
    assert solucao.executabilidade is Executabilidade.HIPOTESE_PASSADA
    assert f"verdade_factual op={_INCLUIR}" in solucao.condicoes_pendentes
    assert not any(c.startswith("competencia_aberta") for c in solucao.condicoes_pendentes)


def test_competencia_fechada_sem_evidencia_atual_continua_hipotese_passada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    assert _buscar(mundo).solucoes[0].executabilidade is Executabilidade.HIPOTESE_PASSADA


def test_mes_anterior_sem_evidencia_atual_fica_indeterminado(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, agora=_em(2020, 2))
    solucao = _buscar(mundo, operacoes=(_documentada(),)).solucoes[0]
    assert solucao.executabilidade is Executabilidade.INDETERMINADO


def test_operacao_so_em_competencia_aberta_nao_se_aplica_a_fechada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202610")
    resultado = _buscar(mundo, operacoes=(operacao(_INCLUIR, 1, competencias="ABERTAS"),))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 0
    assert resultado.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA


@pytest.mark.parametrize(("ano", "mes"), [(2020, 1), (2020, 2)])
def test_competencia_aberta_documentada_e_potencialmente_executavel_sob_condicoes(
    tmp_path: Path, ano: int, mes: int
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001", agora=_em(ano, mes))
    solucao = _buscar(mundo, operacoes=(_documentada(),)).solucoes[0]
    assert solucao.executabilidade is _POTENCIAL
    assert f"verdade_factual op={_INCLUIR}" in solucao.condicoes_pendentes
    assert "competencia_aberta competencia=202001" in solucao.condicoes_pendentes


@pytest.mark.parametrize(("ano", "mes"), [(2026, 10), (2020, 4), (2019, 12)])
def test_competencia_aberta_obsoleta_nunca_e_potencialmente_executavel(
    tmp_path: Path, ano: int, mes: int
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001", agora=_em(ano, mes))
    solucao = _buscar(mundo, operacoes=(_documentada(),)).solucoes[0]
    assert solucao.executabilidade is not _POTENCIAL
    assert any(
        c.startswith("competencia_aberta_inconsistente") for c in solucao.condicoes_pendentes
    )


@pytest.mark.parametrize(
    ("autoridade", "governanca", "esperado"),
    [
        ("DESCONHECIDA", "DESCONHECIDA", Executabilidade.INDETERMINADO),
        ("ESTABELECIMENTO", "DESCONHECIDA", Executabilidade.INDETERMINADO),
        ("GESTOR_ESTADUAL", "FORA_DA_GOVERNANCA_MUNICIPAL", Executabilidade.FORA_DA_GOVERNANCA),
        ("MINISTERIO_SAUDE", "FORA_DA_GOVERNANCA_MUNICIPAL", Executabilidade.FORA_DA_GOVERNANCA),
        ("GESTOR_ESTADUAL", "MUNICIPAL_DOCUMENTADA", Executabilidade.INDETERMINADO),
        ("MINISTERIO_SAUDE", "MUNICIPAL_DOCUMENTADA", Executabilidade.INDETERMINADO),
    ],
)
def test_autoridade_desconhecida(
    tmp_path: Path, autoridade: str, governanca: str, esperado: Executabilidade
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001", agora=_em(2020, 1))
    catalogo = (operacao(_INCLUIR, 1, autoridade=autoridade, governanca=governanca),)
    assert _buscar(mundo, operacoes=catalogo).solucoes[0].executabilidade is esperado


def test_fonte_so_historica_deixa_indeterminado(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, agora=_em(2020, 1))
    solucao = _buscar(mundo, operacoes=(_documentada(),)).solucoes[0]
    assert solucao.executabilidade is Executabilidade.INDETERMINADO


def test_orcamento_esgotado(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    resultado = _buscar(mundo, _config(max_candidatos=1))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 1
    assert resultado.motivo_parada is MotivoParada.ORCAMENTO_ESGOTADO
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA
    assert resultado.custo_max_explorado_completo == 2


def test_busca_interrompida_com_solucao_nunca_declara_minimo(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1, CBO_TERCEIRO: 1})
    catalogo = (operacao(_INCLUIR, 1), operacao(_RECLASSIFICAR, 1))
    resultado = _buscar(mundo, _config(max_candidatos=1), operacoes=catalogo)
    assert len(resultado.solucoes) == 1
    assert resultado.motivo_parada is MotivoParada.ORCAMENTO_ESGOTADO
    assert resultado.minimalidade is Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE
    assert resultado.custo_max_explorado_completo == 0


def test_limite_de_operacoes_impede_prova_de_minimo(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    resultado = _buscar(mundo, _config(max_operacoes=2))
    assert resultado.solucoes[0].custo == 4
    assert resultado.minimalidade is Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE


def test_minimo_lista_todas_as_solucoes_de_menor_custo(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1, CBO_TERCEIRO: 1})
    catalogo = (operacao(_INCLUIR, 1), operacao(_RECLASSIFICAR, 1))
    resultado = _buscar(mundo, operacoes=catalogo)
    assert len(resultado.solucoes) == 3
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO


def test_pioras_declaram_conforme_que_vira_inconclusivo() -> None:
    base = {("r0", "A"): "CONFORME", ("r1", "A"): "CONFORME", ("r2", "A"): "INCONCLUSIVO"}
    estados = {("r0", "A"): "INCONCLUSIVO", ("r1", "A"): "CONFORME", ("r2", "A"): "INCONCLUSIVO"}
    assert pioras(base, estados) == ("inconclusao_nova row=r0 regra=A estado=INCONCLUSIVO",)


def test_falha_do_motor_na_revalidacao_interrompe_a_busca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    real = counterfactual_sobreposicao.evaluate_rules
    chamadas: list[int] = []

    def parcial_no_candidato(*args: Any, **kwargs: Any) -> RunResult:
        resultado = real(*args, **kwargs)
        chamadas.append(1)
        if len(chamadas) == 1:
            return resultado
        return resultado.model_copy(update={"estado": EstadoExecucao.PARCIAL})

    monkeypatch.setattr(counterfactual_sobreposicao, "evaluate_rules", parcial_no_candidato)
    with pytest.raises(RevalidacaoFalhou, match="contrafactual_revalidacao_falhou"):
        _buscar(mundo)


def test_pf_com_inteiro_de_32_bits_e_editavel_como_no_motor(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, pf_int32=True)
    assert _nomes(_buscar(mundo)) == [[_INCLUIR]]


def _reescrever_st(mundo: Mundo, conteudo: bytes) -> None:
    Path(mundo.contexto.cadastros[0].caminho).write_bytes(conteudo)


def test_st_truncado_e_falha_operacional_nunca_ausencia(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    original = Path(mundo.contexto.cadastros[0].caminho).read_bytes()
    _reescrever_st(mundo, original[: len(original) // 2])
    with pytest.raises(InsumoCadastralInvalido, match="contrafactual_cadastro_invalido"):
        _buscar(mundo)


def test_st_divergente_do_datasetref_e_falha_operacional(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    outro = montar(tmp_path / "outro", pf={CBO_OUTRO: 1}, st_presente=True)
    _reescrever_st(mundo, Path(outro.contexto.cadastros[0].caminho).read_bytes())
    with pytest.raises(InsumoCadastralInvalido, match="contrafactual_cadastro_invalido"):
        _buscar(mundo)


_OUTRA_VERSAO = {"competencia_arquivo": COMPETENCIA, "cnes": "1111111", "artifact_id": artefato(5)}


@pytest.mark.parametrize(
    "opcoes",
    [
        OpcoesST(tipos={"municipio_estabelecimento": pa.int64()}),
        OpcoesST(extras=(_OUTRA_VERSAO,)),
        OpcoesST(integridade=EstadoIntegridade.QUARENTENA_TRUNCADO),
        OpcoesST(presente=False, integridade=EstadoIntegridade.NAO_VERIFICADO),
        OpcoesST(presente=False, integridade=None),
    ],
    ids=["leiaute", "sem_versao_unica", "quarentena", "ausencia_nao_verificada", "sem_integridade"],
)
def test_st_inutilizavel_deixa_operacoes_inadmissiveis(tmp_path: Path, opcoes: OpcoesST) -> None:
    resultado = _buscar(montar(tmp_path, pf={CBO_OUTRO: 1}, st=opcoes))
    assert resultado.solucoes == ()
    assert resultado.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL


def test_st_nao_verificado_sustenta_presenca(tmp_path: Path) -> None:
    opcoes = OpcoesST(integridade=EstadoIntegridade.NAO_VERIFICADO)
    assert _nomes(_buscar(montar(tmp_path, pf={CBO_OUTRO: 2}, st=opcoes))) == [[_INCLUIR]]


def _sha256(caminhos: tuple[str, ...]) -> dict[str, str]:
    return {c: hashlib.sha256(Path(c).read_bytes()).hexdigest() for c in caminhos}


def test_originais_intactos(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1, CBO_TERCEIRO: 1}, st_presente=False)
    antes = _sha256(mundo.arquivos)
    _buscar(mundo)
    assert _sha256(mundo.arquivos) == antes
    assert sorted(str(p) for p in (tmp_path / "entrada").iterdir()) == list(mundo.arquivos)


def test_recusa_bundle_sem_violacao(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2, CBO_ALVO: 1})
    with pytest.raises(ValueError, match="contrafactual_baseline_incoerente"):
        _buscar(mundo)


def test_recusa_busca_sem_contexto(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    with pytest.raises(ValueError, match="contrafactual_sem_contexto"):
        search_counterfactuals(mundo.bundle, _config())


def test_catalogo_de_operacoes_e_fechado_e_conservador() -> None:
    operacoes = carregar_operacoes()
    assert {o.op_id for o in operacoes} == {_INCLUIR, _RECLASSIFICAR, _CADASTRAR}
    assert all(o.governanca is not Governanca.MUNICIPAL_DOCUMENTADA for o in operacoes)
    assert all(o.alvo.schema_id.startswith("cnes_") for o in operacoes)
    assert all(o.altera_vinculo_individual is False for o in operacoes)


def _invalidos() -> list[tuple[tuple[OperationSpec, ...], str]]:
    incluir, cadastrar = operacao(_INCLUIR, 1), operacao(_CADASTRAR, 1)
    alvo_st = AlvoOperacao(schema_id="cnes_estabelecimento.v1", colunas=("cnes",))
    trocar = incluir.model_copy
    return [
        ((incluir, incluir), "operacao_repetida"),
        ((trocar(update={"op_id": "OUTRA_OPERACAO"}),), "operacao_sem_efeito"),
        ((trocar(update={"alvo": alvo_st}),), "operacao_alvo_incoerente"),
        (
            (trocar(update={"precondicoes": ("ESTABELECIMENTO_NO_CNES_ST", "X")}),),
            "precondicao_desc",
        ),
        ((trocar(update={"depende_de": (_CADASTRAR, "X")}),), "dependencia_desconhecida"),
        ((incluir, cadastrar.model_copy(update={"depende_de": (_INCLUIR,)})), "dependencia_circ"),
        ((trocar(update={"precondicoes": ()}),), "precondicao_obrigatoria_ausente"),
        ((trocar(update={"depende_de": ()}),), "dependencia_obrigatoria_ausente"),
        (
            (trocar(update={"precondicoes": (*incluir.precondicoes, "CBO_ORIGEM_COM_VINCULO")}),),
            "precondicao_incompativel_com_operacao",
        ),
    ]


@pytest.mark.parametrize(("operacoes", "mensagem"), _invalidos())
def test_catalogo_invalido_e_recusado(operacoes: tuple[OperationSpec, ...], mensagem: str) -> None:
    with pytest.raises(CatalogoOperacoesInvalido, match=mensagem):
        validar_operacoes(operacoes)


def test_catalogo_sem_versao_e_recusado(tmp_path: Path) -> None:
    caminho = tmp_path / "operations.yaml"
    caminho.write_text("operacoes: []\n", encoding="utf-8")
    with pytest.raises(CatalogoOperacoesInvalido, match="catalogo_operacoes_sem_versao"):
        carregar_operacoes(caminho)


def test_hipotese_executabilidade_e_aprovacao_nao_sao_sinonimos(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001", agora=_em(2020, 1))
    resultado = _buscar(mundo, operacoes=(_documentada(),))
    texto = resultado.model_dump_json()
    assert resultado.aprovacao_garantida is False
    assert '"aprovacao_garantida":false' in texto
    assert texto.count("aprova") == 1
    condicoes = [c.lower() for s in resultado.solucoes for c in s.condicoes_pendentes]
    assert not any("aprova" in c for c in condicoes)
    assert len({e.value for e in Executabilidade}) == 4
    assert afirmacoes_proibidas("o registro será aprovado") != []
    assert afirmacoes_proibidas("não implica aprovação nem é garantia") == []
    for caminho in ("catalog/operations.yaml", "docs/method/contrafactuais.md"):
        texto_doc = (_RAIZ / caminho).read_text(encoding="utf-8")
        assert afirmacoes_proibidas(texto_doc) == [], caminho


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(sorteio=mundos_pequenos(CBO_ALVO))
def test_minimalidade_igual_a_enumeracao_completa(
    tmp_path_factory: pytest.TempPathFactory, sorteio: Sorteio
) -> None:
    mundo_oraculo = sorteio.mundo
    mundo = montar(
        tmp_path_factory.mktemp("mundo"),
        pf=sorteio.pf_materializado(),
        st_presente=mundo_oraculo.st_presente,
        outros=tuple((cbo, "C") for cbo in mundo_oraculo.outros_cbos),
    )
    catalogo = tuple(operacao(op, c) for op, c in mundo_oraculo.custos.items())
    config = _config(mundo_oraculo.max_operacoes, sorteio.max_candidatos)
    resultado = _buscar(mundo, config, operacoes=catalogo)
    menor, esperadas = solucoes_minimas(mundo_oraculo)
    obtidas = {
        frozenset((o.op_id, o.parametros.get("cbo_origem", "")) for o in s.operacoes)
        for s in resultado.solucoes
    }
    if resultado.motivo_parada is MotivoParada.ORCAMENTO_ESGOTADO:
        assert resultado.minimalidade is not Minimalidade.MINIMO_NO_CATALOGO
        assert obtidas <= esperadas
        return
    if menor is None:
        assert resultado.solucoes == ()
        assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA
        return
    assert obtidas == esperadas
    assert {s.custo for s in resultado.solucoes} == {menor}
    assert resultado.custo_max_explorado_completo == menor
    if resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO:
        irrestrito = replace(mundo_oraculo, max_operacoes=n_instancias(mundo_oraculo))
        assert solucoes_minimas(irrestrito) == (menor, esperadas)
    else:
        assert resultado.minimalidade is Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE
        assert n_instancias(mundo_oraculo) > mundo_oraculo.max_operacoes
