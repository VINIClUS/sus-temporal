"""Busca de contrafactuais (T09) sobre mundos SINTETICOS; nada aqui é resultado empírico."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sustemporal.contracts.config import OrcamentoContrafactual, RunConfig
from sustemporal.contracts.counterfactual import (
    Executabilidade,
    Governanca,
    Minimalidade,
    MotivoParada,
)
from sustemporal.explanation.counterfactual import search_counterfactuals
from sustemporal.explanation.counterfactual_operacoes import carregar_operacoes
from sustemporal.rules.catalog import carregar_regras
from tests.fixtures.contrafactual_cenario import (
    CBO_ALVO,
    CBO_OUTRO,
    CBO_TERCEIRO,
    montar,
    operacao,
)
from tests.fixtures.contrafactual_oraculo import MundoOraculo, solucoes_minimas

if TYPE_CHECKING:
    from sustemporal.contracts.counterfactual import CounterfactualSearchResult, OperationSpec
    from tests.fixtures.contrafactual_cenario import Mundo

_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"
_RECLASSIFICAR = "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO"
_CADASTRAR = "CADASTRAR_ESTABELECIMENTO_NO_CNES"
_RAIZ = Path(__file__).resolve().parents[2]


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


Passo = tuple[str, tuple[tuple[str, str], ...]]


def _ops(resultado: CounterfactualSearchResult) -> list[list[Passo]]:
    return [
        [(o.op_id, tuple(sorted(o.parametros.items()))) for o in s.operacoes]
        for s in resultado.solucoes
    ]


def test_solucao_de_uma_operacao(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    resultado = _buscar(mundo)
    assert [[op for op, _ in s] for s in _ops(resultado)] == [[_INCLUIR]]
    solucao = resultado.solucoes[0]
    assert solucao.custo == 1
    assert str(solucao.operacoes[0].competencia) == "202001"
    assert "ESTAB_CBO_CNES" in solucao.regras_revalidadas
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO
    assert resultado.motivo_parada is MotivoParada("MINIMO_ENCONTRADO")
    assert resultado.custo_max_explorado_completo == 1
    assert resultado.aprovacao_garantida is False


def test_dependencia_entre_operacoes(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    resultado = _buscar(mundo)
    assert [[op for op, _ in s] for s in _ops(resultado)] == [[_CADASTRAR, _INCLUIR]]
    assert resultado.solucoes[0].custo == 4
    assert resultado.minimalidade is Minimalidade.MINIMO_NO_CATALOGO


def test_dependencia_nunca_vem_depois_de_quem_depende(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    catalogo = (operacao(_INCLUIR, 1), operacao(_CADASTRAR, 1))
    resultado = _buscar(mundo, operacoes=catalogo)
    assert [[op for op, _ in s] for s in _ops(resultado)] == [[_CADASTRAR, _INCLUIR]]


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


def test_revalida_regra_nao_alvo_afetada(tmp_path: Path) -> None:
    regras = carregar_regras()
    alvo = next(r for r in regras if r.rule_id == "ESTAB_CBO_CNES")
    so_c = alvo.model_copy(update={"instrumentos": ("C",)})
    so_i = alvo.model_copy(update={"rule_id": "ESTAB_CBO_CNES_I", "instrumentos": ("I",)})
    outras = [r for r in regras if r.rule_id != "ESTAB_CBO_CNES"]
    mundo = montar(
        tmp_path,
        pf={CBO_OUTRO: 1},
        outros=((CBO_OUTRO, "I"),),
        regras=(so_c, so_i, *outras),
    )
    resultado = _buscar(mundo, operacoes=(operacao(_RECLASSIFICAR, 1),))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 1


def test_regras_revalidadas_incluem_todas_as_afetadas(tmp_path: Path) -> None:
    regras = carregar_regras()
    alvo = next(r for r in regras if r.rule_id == "ESTAB_CBO_CNES")
    irma = alvo.model_copy(update={"rule_id": "ESTAB_CBO_CNES_IRMA"})
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, regras=(*regras, irma))
    resultado = _buscar(mundo)
    revalidadas = set(resultado.solucoes[0].regras_revalidadas)
    assert {"ESTAB_CBO_CNES", "ESTAB_CBO_CNES_IRMA"} <= revalidadas
    assert "VIGENCIA_PROCEDIMENTO_SIGTAP" not in revalidadas


def test_competencia_fechada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202610")
    documentada = operacao(
        _INCLUIR, 1, autoridade="ESTABELECIMENTO", governanca="MUNICIPAL_DOCUMENTADA"
    )
    resultado = _buscar(mundo, operacoes=(documentada,))
    solucao = resultado.solucoes[0]
    assert solucao.executabilidade is Executabilidade.HIPOTESE_PASSADA
    assert f"verdade_factual op={_INCLUIR}" in solucao.condicoes_pendentes
    assert not any(c.startswith("competencia_aberta") for c in solucao.condicoes_pendentes)


def test_competencia_fechada_sem_evidencia_atual_continua_hipotese_passada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2})
    resultado = _buscar(mundo)
    assert resultado.solucoes[0].executabilidade is Executabilidade.HIPOTESE_PASSADA


def test_operacao_so_em_competencia_aberta_nao_se_aplica_a_fechada(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202610")
    resultado = _buscar(mundo, operacoes=(operacao(_INCLUIR, 1, competencias="ABERTAS"),))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 0
    assert resultado.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA


def test_competencia_aberta_documentada_e_potencialmente_executavel_sob_condicoes(
    tmp_path: Path,
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001")
    documentada = operacao(
        _INCLUIR, 1, autoridade="ESTABELECIMENTO", governanca="MUNICIPAL_DOCUMENTADA"
    )
    solucao = _buscar(mundo, operacoes=(documentada,)).solucoes[0]
    assert solucao.executabilidade is Executabilidade.POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES
    assert f"verdade_factual op={_INCLUIR}" in solucao.condicoes_pendentes
    assert "competencia_aberta competencia=202001" in solucao.condicoes_pendentes


@pytest.mark.parametrize(
    ("autoridade", "governanca", "esperado"),
    [
        ("DESCONHECIDA", "DESCONHECIDA", Executabilidade.INDETERMINADO),
        ("ESTABELECIMENTO", "DESCONHECIDA", Executabilidade.INDETERMINADO),
        ("GESTOR_ESTADUAL", "FORA_DA_GOVERNANCA_MUNICIPAL", Executabilidade.FORA_DA_GOVERNANCA),
        ("MINISTERIO_SAUDE", "FORA_DA_GOVERNANCA_MUNICIPAL", Executabilidade.FORA_DA_GOVERNANCA),
    ],
)
def test_autoridade_desconhecida(
    tmp_path: Path, autoridade: str, governanca: str, esperado: Executabilidade
) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001")
    catalogo = (operacao(_INCLUIR, 1, autoridade=autoridade, governanca=governanca),)
    solucao = _buscar(mundo, operacoes=catalogo).solucoes[0]
    assert solucao.executabilidade is esperado


def test_fonte_so_historica_deixa_indeterminado(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta=None)
    documentada = operacao(
        _INCLUIR, 1, autoridade="ESTABELECIMENTO", governanca="MUNICIPAL_DOCUMENTADA"
    )
    no_mes = replace(mundo.contexto, relogio=lambda: datetime(2020, 1, 15, tzinfo=UTC))
    resultado = search_counterfactuals(
        mundo.bundle, _config(), contexto=no_mes, operacoes=(documentada,)
    )
    assert resultado.solucoes[0].executabilidade is Executabilidade.INDETERMINADO


def test_orcamento_esgotado(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1}, st_presente=False)
    resultado = _buscar(mundo, _config(max_candidatos=1))
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 1
    assert resultado.motivo_parada is MotivoParada.ORCAMENTO_ESGOTADO
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA


def test_busca_interrompida_com_solucao_nunca_declara_minimo(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 1, CBO_TERCEIRO: 1})
    catalogo = (operacao(_INCLUIR, 1), operacao(_RECLASSIFICAR, 1))
    resultado = _buscar(mundo, _config(max_candidatos=1), operacoes=catalogo)
    assert len(resultado.solucoes) == 1
    assert resultado.motivo_parada is MotivoParada.ORCAMENTO_ESGOTADO
    assert resultado.minimalidade is Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE


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


_PROIBIDOS = re.compile(
    r"aprova[çc][ãa]o garantida|garant\w* (a )?aprova|ser[áa] aprovad|assegura (a )?aprova"
    r"|executável com certeza|recomenda-se",
    re.IGNORECASE,
)


def test_hipotese_executabilidade_e_aprovacao_nao_sao_sinonimos(tmp_path: Path) -> None:
    mundo = montar(tmp_path, pf={CBO_OUTRO: 2}, competencia_aberta="202001")
    documentada = operacao(
        _INCLUIR, 1, autoridade="ESTABELECIMENTO", governanca="MUNICIPAL_DOCUMENTADA"
    )
    resultado = _buscar(mundo, operacoes=(documentada,))
    texto = resultado.model_dump_json()
    assert resultado.aprovacao_garantida is False
    assert '"aprovacao_garantida":false' in texto
    assert texto.count("aprova") == 1
    condicoes = [c.lower() for s in resultado.solucoes for c in s.condicoes_pendentes]
    assert not any("aprova" in c for c in condicoes)
    valores = {e.value for e in Executabilidade}
    assert len(valores) == 4
    assert "HIPOTESE_PASSADA" in valores
    for caminho in ("catalog/operations.yaml", "docs/method/contrafactuais.md"):
        assert not _PROIBIDOS.search((_RAIZ / caminho).read_text(encoding="utf-8")), caminho


_CBOS = (CBO_OUTRO, CBO_TERCEIRO, "515105")


@st.composite
def _mundos_pequenos(desenhar: st.DrawFn) -> MundoOraculo:
    contagens = desenhar(st.lists(st.integers(0, 2), min_size=3, max_size=3))
    if not any(contagens):
        contagens[0] = 1
    pf = {cbo: n for cbo, n in zip(_CBOS, contagens, strict=True) if n > 0}
    ops = desenhar(st.sets(st.sampled_from((_INCLUIR, _RECLASSIFICAR, _CADASTRAR)), min_size=1))
    return MundoOraculo(
        pf=pf,
        st_presente=desenhar(st.booleans()),
        cbo_alvo=CBO_ALVO,
        outros_cbos=tuple(desenhar(st.lists(st.sampled_from(_CBOS), max_size=2, unique=True))),
        custos={op: desenhar(st.integers(1, 3)) for op in sorted(ops)},
        max_operacoes=desenhar(st.integers(1, 3)),
    )


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(mundo_oraculo=_mundos_pequenos())
def test_minimalidade_igual_a_enumeracao_completa(
    tmp_path_factory: pytest.TempPathFactory, mundo_oraculo: MundoOraculo
) -> None:
    raiz = tmp_path_factory.mktemp("mundo")
    mundo = montar(
        raiz,
        pf=mundo_oraculo.pf,
        st_presente=mundo_oraculo.st_presente,
        outros=tuple((cbo, "C") for cbo in mundo_oraculo.outros_cbos),
    )
    catalogo = tuple(operacao(op, c) for op, c in mundo_oraculo.custos.items())
    config = _config(max_operacoes=mundo_oraculo.max_operacoes)
    resultado = _buscar(mundo, config, operacoes=catalogo)
    menor, esperadas = solucoes_minimas(mundo_oraculo)
    if menor is None:
        assert resultado.solucoes == ()
        assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA
        return
    obtidas = {
        frozenset((o.op_id, o.parametros.get("cbo_origem", "")) for o in s.operacoes)
        for s in resultado.solucoes
    }
    assert obtidas == esperadas
    assert {s.custo for s in resultado.solucoes} == {menor}
    limite = (mundo_oraculo.max_operacoes + 1) * min(mundo_oraculo.custos.values())
    esperado = (
        Minimalidade.MINIMO_NO_CATALOGO
        if menor <= limite
        else Minimalidade.SOLUCAO_SEM_PROVA_DE_MINIMALIDADE
    )
    assert resultado.minimalidade is esperado
