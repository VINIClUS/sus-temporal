"""Revisão adversarial do T06: UF, deslocamento, canal, borda do corte, motor e lote; SINTETICO."""

from __future__ import annotations

import duckdb
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
    PoliticaTemporal,
    SelecaoVersao,
    TipoPolitica,
)
from sustemporal.temporal import selector as modulo_seletor
from sustemporal.temporal.lote import selecionar_lote
from sustemporal.temporal.registry import registro_de
from sustemporal.temporal.selector import selecionar_versao, select_snapshots, unir_snapshots
from tests.fixtures.temporal_registro import docref, instante, observar, registro_producao, regra

PF = FamiliaFonte.CNES_PF
_ATEND = CriterioTemporal(fonte=PF, base=BaseTemporal.ATENDIMENTO)


def _registro(*itens):
    return registro_de([o for o, _ in itens], [v for _, v in itens if v is not None])


def _config(
    politica: str = "B_ATEND", *, uf: str | None = "SP", corte: str | None = None
) -> RunConfig:
    campos: dict[str, object] = {"versao": "1", "politica_id": politica}
    if uf is not None:
        campos["piloto"] = {
            "uf": uf,
            "competencias_processamento": ["201801"],
            "territorio": "catalog/territorio/drs_xi.yaml",
            "familias_fontes": ["SIA_PA", "CNES_PF"],
        }
    if corte is not None:
        campos["corte_observacao"] = corte
    return RunConfig.model_validate(campos)


def _politica(
    deslocamento: int = 0, canal: CanalPublicacao | None = None, *, pendente: bool = False
) -> PoliticaTemporal:
    criterio = CriterioTemporal(
        fonte=PF, base=BaseTemporal.ATENDIMENTO, deslocamento_meses=deslocamento, canal=canal
    )
    return PoliticaTemporal(
        politica_id="EXP_DESLOCADA",
        tipo=TipoPolitica.DOCUMENTADA if pendente else TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo="M_TEMP",
        criterios=(criterio,),
        documento=docref(pendente=True) if pendente else None,
    )


def test_conteudo_de_outra_uf_nunca_e_selecionado() -> None:
    registro = _registro(observar(PF, "201801", "MG", 1, uf="MG"))
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(linha, regra(), _config(), registro=registro).selecoes
    assert sel.estado is EstadoSelecao.AUSENTE


def test_sem_uf_na_config_so_fonte_nacional_e_consultada() -> None:
    registro = _registro(observar(PF, "201801", "SP", 1, uf="SP"))
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(linha, regra(), _config(uf=None), registro=registro).selecoes
    assert sel.estado is EstadoSelecao.AUSENTE


def test_politica_com_deslocamento_explicito_usa_o_mes_declarado() -> None:
    registro = _registro(observar(PF, "201712", "dez", 1), observar(PF, "201801", "jan", 1))
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(
        linha, regra(), _config(), registro=registro, politica=_politica(-1)
    ).selecoes
    assert str(sel.competencia_requerida) == "201712"
    assert sel.estado is EstadoSelecao.SELECIONADA


def test_criterio_com_canal_ignora_os_outros_canais() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    criterio = CriterioTemporal(
        fonte=PF, base=BaseTemporal.ATENDIMENTO, canal=CanalPublicacao.HISTORICO
    )
    sel = selecionar_versao(registro, criterio, CompetenciaArquivo("201801"), uf="SP")
    assert sel.estado is EstadoSelecao.AUSENTE


def test_observacao_exatamente_no_corte_entra() -> None:
    registro = _registro(observar(PF, "201801", "A", 10))
    sel = selecionar_versao(
        registro, _ATEND, CompetenciaArquivo("201801"), uf="SP", corte=instante(10)
    )
    assert sel.estado is EstadoSelecao.SELECIONADA


def test_documento_pendente_traz_base_e_competencia_como_o_motor_espera() -> None:
    pendente = PoliticaTemporal(
        politica_id="DOC_PENDENTE",
        tipo=TipoPolitica.DOCUMENTADA,
        metodo="M_TEMP",
        criterios=(_ATEND,),
        documento=docref(pendente=True),
    )
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(
        linha, regra(), _config(), registro=_registro(), politica=pendente
    ).selecoes
    assert sel.estado is EstadoSelecao.NAO_RESOLVIDA
    assert sel.base is BaseTemporal.ATENDIMENTO
    assert str(sel.competencia_requerida) == "201801"


def test_politica_sem_criterio_usa_o_motivo_do_motor() -> None:
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(
        linha, regra(), _config("M_TEMP_PADRAO"), registro=_registro()
    ).selecoes
    assert sel.motivo == f"politica_sem_criterio_para_a_fonte fonte={PF}"


def test_lote_trata_competencia_invalida_como_nao_resolvida() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    linha = registro_producao(None, None)
    con.execute("INSERT INTO registros VALUES (?, '201813', NULL)", [linha.row_id])
    selecionar_lote(con, "registros", [regra()], _politica(-1), _registro(), run_id="r", uf="SP")
    ((estado, motivo),) = con.execute("SELECT estado, motivo FROM selecao_versoes").fetchall()
    assert estado == "NAO_RESOLVIDA"
    assert motivo.startswith("competencia_base_ausente")


def test_lote_recusa_corte_sem_fuso() -> None:
    from datetime import datetime

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    with pytest.raises(ValueError, match="corte_sem_fuso"):
        selecionar_lote(
            con,
            "registros",
            [regra()],
            _politica(),
            _registro(),
            run_id="r",
            corte=datetime(2026, 1, 1),  # noqa: DTZ001
        )


def test_observacao_integra_sem_versao_no_registro_nao_aborta() -> None:
    obs, _versao = observar(PF, "201801", "A", 1, integridade_observada=EstadoIntegridade.OK)
    sel = selecionar_versao(_registro((obs, None)), _ATEND, CompetenciaArquivo("201801"), uf="SP")
    assert sel.estado is EstadoSelecao.EM_QUARENTENA


def test_selecionar_versao_confere_o_conteudo_selecionado(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[str] = []
    original = SelecaoVersao.confere

    def contar(self: SelecaoVersao, artefatos: object) -> None:
        chamadas.append(self.estado.value)
        original(self, artefatos)

    monkeypatch.setattr(modulo_seletor.SelecaoVersao, "confere", contar)
    selecionar_versao(
        _registro(observar(PF, "201801", "A", 1)), _ATEND, CompetenciaArquivo("201801"), uf="SP"
    )
    assert chamadas == ["SELECIONADA"]


def test_multipartes_so_com_falhas_e_ausente_e_parte_nao_declarada_e_incompleta() -> None:
    falha = observar(PF, "201801", "A", 1, parte="a", resultado=ResultadoTentativa.NAO_ENCONTRADO)
    sel = selecionar_versao(_registro(falha), _ATEND, CompetenciaArquivo("201801"), uf="SP")
    assert sel.estado is EstadoSelecao.AUSENTE
    a, c = observar(PF, "201801", "A", 1, parte="a"), observar(PF, "201801", "C", 1, parte="c")
    base = _registro(a, c)
    declarado = type(base)(base.observacoes, base.versoes, {(PF, "201801"): frozenset({"a"})})
    sel = selecionar_versao(declarado, _ATEND, CompetenciaArquivo("201801"), uf="SP")
    assert sel.estado is EstadoSelecao.INCOMPLETA
    assert "nao_declaradas" in sel.motivo


def test_unir_snapshots_deduplica_por_chave_para_a_execucao() -> None:
    registro = _registro(observar(PF, "201801", "A", 1), observar(PF, "201712", "B", 1))
    linhas = [registro_producao("201801", "201801", 0), registro_producao("201801", "201712", 1)]
    linhas.append(registro_producao("201712", "201712", 2))
    conjuntos = [select_snapshots(linha, regra(), _config(), registro=registro) for linha in linhas]
    execucao = unir_snapshots(conjuntos)
    chaves = [(s.fonte, s.base, str(s.competencia_requerida)) for s in execucao.selecoes]
    assert sorted(chaves) == sorted(set(chaves))
    assert len(chaves) == 2
    assert set(execucao.artifact_ids) == {a for c in conjuntos for a in c.artifact_ids}


_COMPS = ["201711", "201712", "201801", "201802"]


@st.composite
def _cenario(draw):
    itens = []
    for comp in draw(st.lists(st.sampled_from(_COMPS), max_size=6)):
        resultado = draw(
            st.sampled_from(
                [
                    ResultadoTentativa.OBTIDO,
                    ResultadoTentativa.NAO_ENCONTRADO,
                    ResultadoTentativa.CONTEUDO_INVALIDO,
                ]
            )
        )
        integridade = (
            EstadoIntegridade.QUARENTENA_TRUNCADO
            if resultado is ResultadoTentativa.CONTEUDO_INVALIDO
            else EstadoIntegridade.OK
        )
        itens.append(
            observar(
                PF,
                comp,
                draw(st.sampled_from(["A", "B"])) + comp,
                draw(st.integers(min_value=0, max_value=40)),
                resultado=resultado,
                integridade=integridade,
                parte=draw(st.sampled_from([None, None, "a", "b"])),
                uf=draw(st.sampled_from(["SP", "SP", "MG"])),
            )
        )
    linhas = draw(
        st.lists(
            st.tuples(st.sampled_from([*_COMPS, None]), st.sampled_from([*_COMPS, None])),
            min_size=1,
            max_size=4,
        )
    )
    deslocamento = draw(st.sampled_from([-1, 0, 1]))
    return itens, linhas, deslocamento, draw(st.booleans()), draw(_extras())


@st.composite
def _extras(draw):
    """Política pendente e partes declaradas, para gerar NAO_RESOLVIDA, INCOMPLETA e SELECIONADA."""
    declaradas = draw(st.sampled_from([None, frozenset({"a"}), frozenset({"a", "b"})]))
    return draw(st.booleans()), declaradas


def _estados_do_cenario(cenario) -> set[EstadoSelecao]:
    itens, linhas, deslocamento, _com_corte, (pendente, declaradas) = cenario
    base = _registro(*itens)
    partes = {} if declaradas is None else {(PF, c): declaradas for c in _COMPS}
    registro = type(base)(base.observacoes, base.versoes, partes)
    politica = _politica(deslocamento, pendente=pendente)
    return {
        s.estado
        for a, p in linhas
        for s in select_snapshots(
            registro_producao(a, p), regra(), _config(), registro=registro, politica=politica
        ).selecoes
    }


_JAN = [("201801", "201801")]
_QUARENTENA = {
    "resultado": ResultadoTentativa.CONTEUDO_INVALIDO,
    "integridade": EstadoIntegridade.QUARENTENA_TRUNCADO,
}
_EXEMPLOS = {
    EstadoSelecao.SELECIONADA: ([observar(PF, "201801", "A", 1)], _JAN, 0, True, (False, None)),
    EstadoSelecao.AMBIGUA: (
        [observar(PF, "201801", "A", 1), observar(PF, "201801", "B", 2)],
        _JAN,
        0,
        False,
        (False, None),
    ),
    EstadoSelecao.INCOMPLETA: (
        [observar(PF, "201801", "A", 1, parte="a")],
        _JAN,
        0,
        False,
        (False, frozenset({"a", "b"})),
    ),
    EstadoSelecao.EM_QUARENTENA: (
        [observar(PF, "201801", "A", 1, **_QUARENTENA)],
        _JAN,
        0,
        False,
        (False, None),
    ),
    EstadoSelecao.NAO_RESOLVIDA: ([observar(PF, "201801", "A", 1)], _JAN, 0, False, (True, None)),
}


@pytest.mark.parametrize("estado", list(_EXEMPLOS))
def test_exemplos_do_lote_cobrem_cada_estado(estado: EstadoSelecao) -> None:
    assert _estados_do_cenario(_EXEMPLOS[estado]) == {estado}


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=40)
@given(_cenario())
@example(_EXEMPLOS[EstadoSelecao.SELECIONADA])
@example(_EXEMPLOS[EstadoSelecao.AMBIGUA])
@example(_EXEMPLOS[EstadoSelecao.INCOMPLETA])
@example(_EXEMPLOS[EstadoSelecao.EM_QUARENTENA])
@example(_EXEMPLOS[EstadoSelecao.NAO_RESOLVIDA])
def test_lote_equivale_ao_registro_com_deslocamento_uf_e_quarentena(cenario) -> None:
    itens, linhas, deslocamento, com_corte, (pendente, declaradas) = cenario
    base = _registro(*itens)
    partes = {} if declaradas is None else {(PF, c): declaradas for c in _COMPS}
    registro = type(base)(base.observacoes, base.versoes, partes)
    corte = "2026-01-20T00:00:00+00:00" if com_corte else None
    config = _config(corte=corte)
    politica = _politica(deslocamento, pendente=pendente)
    registros = [registro_producao(a, p, i) for i, (a, p) in enumerate(linhas)]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    con.executemany(
        "INSERT INTO registros VALUES (?, ?, ?)",
        [(r.row_id, a, p) for r, (a, p) in zip(registros, linhas, strict=True)],
    )
    selecionar_lote(
        con,
        "registros",
        [regra()],
        politica,
        registro,
        run_id="r",
        uf="SP",
        corte=config.corte_observacao,
    )
    lote = {
        linha[0]: linha[1:]
        for linha in con.execute(
            "SELECT row_id, base, competencia_requerida, estado, artifact_ids, observation_ids, "
            "motivo FROM selecao_versoes"
        ).fetchall()
    }
    for linha in registros:
        (sel,) = select_snapshots(
            linha, regra(), config, registro=registro, politica=politica
        ).selecoes
        esperado = (
            None if sel.base is None else str(sel.base),
            None if sel.competencia_requerida is None else str(sel.competencia_requerida),
            str(sel.estado),
            ";".join(sel.artifact_ids),
            ";".join(sel.observation_ids),
            sel.motivo,
        )
        assert lote[linha.row_id] == esperado


def _ambiente_padrao(tmp_path, partes: tuple[str, ...]):
    from pathlib import Path

    from sustemporal.acquisition.manifest import Manifesto

    manifesto = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl")
    for parte in partes:
        obs, versao = observar(PF, "201801", f"P{parte}", 1, parte=parte)
        manifesto.registrar(obs, versao)
    texto = Path("catalog/sources.yaml").read_text(encoding="utf-8")
    marcador = "  - fonte: CNES_PF\n"
    texto = texto.replace(
        marcador, marcador + '    partes_esperadas:\n      "201801": [a, b, c]\n', 1
    )
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    return _config().model_copy(
        update={
            "runtime": _config().runtime.model_copy(
                update={"raiz_manifestos": str(tmp_path / "manifests")}
            ),
            "catalogos": {"fontes": str(catalogo)},
        }
    )


@pytest.mark.parametrize(
    ("partes", "estado"),
    [(("a", "b", "c"), EstadoSelecao.SELECIONADA), (("a", "b"), EstadoSelecao.INCOMPLETA)],
)
def test_caminho_padrao_le_partes_esperadas_do_catalogo(
    tmp_path, partes: tuple[str, ...], estado: EstadoSelecao
) -> None:
    config = _ambiente_padrao(tmp_path, partes)
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(linha, regra(), config).selecoes
    assert sel.estado is estado


def _regra_com_fonte_repetida():
    from sustemporal.contracts.rules import RequisitoFonte

    base = regra()
    extra = RequisitoFonte(fonte=PF, schema_id="cnes_estab_cbo.v1", campos=("cnes",))
    return base.model_copy(update={"requisitos_fonte": (*base.requisitos_fonte, extra)})


def test_fonte_repetida_na_regra_gera_uma_selecao_por_fonte() -> None:
    linha = registro_producao("201801", "201801")
    snapshot = select_snapshots(linha, _regra_com_fonte_repetida(), _config(), registro=_registro())
    assert [s.fonte for s in snapshot.selecoes] == [PF]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    con.execute("INSERT INTO registros VALUES (?, '201801', '201801')", [linha.row_id])
    selecionar_lote(
        con,
        "registros",
        [_regra_com_fonte_repetida()],
        _politica(),
        _registro(),
        run_id="r",
        uf="SP",
    )
    assert con.execute("SELECT count(*) FROM selecao_versoes").fetchall() == [(1,)]
