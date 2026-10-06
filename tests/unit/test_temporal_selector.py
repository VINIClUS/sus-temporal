"""Registro e seleção temporal (T06); todo registro e versão é SINTETICO."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.hashing import hash_logico_linhas
from sustemporal.temporal.politicas import carregar_politica
from sustemporal.temporal.registry import ORIGEM_INTERVALO, registro_de
from sustemporal.temporal.selector import selecionar_versao, select_snapshots
from tests.fixtures.temporal_registro import docref, instante, observar, registro_producao, regra

if TYPE_CHECKING:
    from pathlib import Path

PF = FamiliaFonte.CNES_PF
_ATEND = CriterioTemporal(fonte=PF, base=BaseTemporal.ATENDIMENTO)


def _registro(*itens, partes=None):
    observacoes = [o for o, _ in itens]
    versoes = [v for _, v in itens if v is not None]
    registro = registro_de(observacoes, versoes)
    if partes is not None:
        registro = type(registro)(registro.observacoes, registro.versoes, partes)
    return registro


def _config(politica: str = "B_ATEND", corte: str | None = None) -> RunConfig:
    campos: dict[str, object] = {"versao": "1", "politica_id": politica}
    campos["piloto"] = {
        "uf": "SP",
        "competencias_processamento": ["201801"],
        "territorio": "catalog/territorio/drs_xi.yaml",
        "familias_fontes": ["SIA_PA", "CNES_PF"],
    }
    if corte is not None:
        campos["corte_observacao"] = corte
    return RunConfig.model_validate(campos)


def _comp(valor: str) -> CompetenciaArquivo:
    return CompetenciaArquivo(valor)


def test_politicas_do_catalogo_carregam_e_so_baselines_tem_criterios() -> None:
    b_atend, b_proc = carregar_politica("B_ATEND"), carregar_politica("B_PROC")
    m_temp = carregar_politica("M_TEMP_PADRAO")
    assert {c.base for c in b_atend.criterios} == {BaseTemporal.ATENDIMENTO}
    assert {c.base for c in b_proc.criterios} == {BaseTemporal.PROCESSAMENTO}
    assert b_atend.tipo is TipoPolitica.ALTERNATIVA_EXPLORATORIA
    assert m_temp.tipo is TipoPolitica.NAO_RESOLVIDA
    assert not any(p.tipo is TipoPolitica.DOCUMENTADA for p in (b_atend, b_proc, m_temp))


def test_atendimento_diferente_de_processamento_seleciona_meses_distintos() -> None:
    dez, jan = observar(PF, "201712", "dez", 1), observar(PF, "201801", "jan", 1)
    registro = _registro(dez, jan)
    linha = registro_producao("201712", "201801")
    por_atendimento = select_snapshots(linha, regra(), _config("B_ATEND"), registro=registro)
    por_processamento = select_snapshots(linha, regra(), _config("B_PROC"), registro=registro)
    (sel_a,), (sel_p,) = por_atendimento.selecoes, por_processamento.selecoes
    assert sel_a.artifact_ids == (dez[1].artifact_id,)
    assert sel_p.artifact_ids == (jan[1].artifact_id,)
    assert str(sel_a.competencia_requerida) == "201712"
    assert sel_a.base is BaseTemporal.ATENDIMENTO


def test_arquivo_auxiliar_anterior_a_2018_e_o_proprio_mes_de_atendimento() -> None:
    out = observar(PF, "201710", "out", 1)
    registro = _registro(out, observar(PF, "201801", "jan", 1))
    snapshot = select_snapshots(
        registro_producao("201710", "201801"), regra(), _config(), registro=registro
    )
    (selecao,) = snapshot.selecoes
    assert selecao.estado is EstadoSelecao.SELECIONADA
    assert selecao.artifact_ids == (out[1].artifact_id,)


def test_ausencia_no_mes_exigido_nunca_usa_o_mes_vizinho() -> None:
    registro = _registro(observar(PF, "201712", "dez", 1), observar(PF, "201802", "fev", 1))
    selecao = selecionar_versao(registro, _ATEND, _comp("201801"), uf="SP")
    assert selecao.estado is EstadoSelecao.AUSENTE
    assert selecao.artifact_ids == ()
    assert str(selecao.competencia_requerida) == "201801"


def test_republicacao_tardia_fora_do_corte_nao_entra() -> None:
    antes, depois = observar(PF, "201801", "A", 1), observar(PF, "201801", "B", 30)
    registro = _registro(antes, depois)
    com_corte = selecionar_versao(registro, _ATEND, _comp("201801"), uf="SP", corte=instante(10))
    assert com_corte.estado is EstadoSelecao.SELECIONADA
    assert com_corte.artifact_ids == (antes[1].artifact_id,)
    sem_corte = selecionar_versao(registro, _ATEND, _comp("201801"), uf="SP")
    assert sem_corte.estado is EstadoSelecao.AMBIGUA
    assert set(sem_corte.artifact_ids) == {antes[1].artifact_id, depois[1].artifact_id}


def test_observada_so_depois_do_corte_e_fora_do_corte() -> None:
    registro = _registro(observar(PF, "201801", "A", 30))
    selecao = selecionar_versao(registro, _ATEND, _comp("201801"), uf="SP", corte=instante(10))
    assert selecao.estado is EstadoSelecao.FORA_DO_CORTE
    assert selecao.artifact_ids == ()


def test_politica_documental_ambigua_ou_nao_resolvida_se_abstem() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    linha = registro_producao("201801", "201801")
    (sel,) = select_snapshots(linha, regra(), _config("M_TEMP_PADRAO"), registro=registro).selecoes
    assert sel.estado is EstadoSelecao.NAO_RESOLVIDA
    assert sel.artifact_ids == ()
    pendente = PoliticaTemporal(
        politica_id="DOC_PENDENTE",
        tipo=TipoPolitica.DOCUMENTADA,
        metodo="M_TEMP",
        criterios=(_ATEND,),
        documento=docref(pendente=True),
    )
    (sel,) = select_snapshots(
        linha,
        regra(criterios_temporais=(_ATEND,)),
        _config("M_TEMP_PADRAO"),
        registro=registro,
        politica=pendente,
    ).selecoes
    assert sel.estado is EstadoSelecao.NAO_RESOLVIDA
    assert "documento_pendente" in sel.motivo


def test_competencia_base_nula_nao_resolve() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    linha = registro_producao(None, "201801")
    (sel,) = select_snapshots(linha, regra(), _config(), registro=registro).selecoes
    assert sel.estado is EstadoSelecao.NAO_RESOLVIDA


def test_conjunto_congelado_nao_muda_quando_chegam_versoes_novas() -> None:
    a = observar(PF, "201801", "A", 1)
    linha = registro_producao("201801", "201801")
    config = _config(corte="2026-01-10T00:00:00+00:00")
    antes = select_snapshots(linha, regra(), config, registro=_registro(a))
    novo = observar(PF, "201801", "B", 40)
    depois = select_snapshots(linha, regra(), config, registro=_registro(a, novo))
    assert antes.congelado
    assert antes.snapshot_id == depois.snapshot_id
    assert antes == depois


def test_mesmo_conteudo_observado_duas_vezes_e_uma_versao_com_duas_observacoes() -> None:
    primeira, segunda = observar(PF, "201801", "A", 1), observar(PF, "201801", "A", 2)
    selecao = selecionar_versao(_registro(primeira, segunda), _ATEND, _comp("201801"), uf="SP")
    assert selecao.estado is EstadoSelecao.SELECIONADA
    assert selecao.artifact_ids == (primeira[1].artifact_id,)
    assert set(selecao.observation_ids) == {primeira[0].observation_id, segunda[0].observation_id}


def test_conteudo_a_b_a_e_ambiguo_e_intervalos_sao_da_pesquisa() -> None:
    itens = [observar(PF, "201801", c, d) for c, d in (("A", 1), ("B", 2), ("A", 3))]
    registro = _registro(*itens)
    assert selecionar_versao(registro, _ATEND, _comp("201801"), uf="SP").estado is (
        EstadoSelecao.AMBIGUA
    )
    intervalos = registro.intervalos(PF, "SP", _comp("201801"))
    assert [i.artifact_id for i in intervalos] == [
        itens[0][1].artifact_id,
        itens[1][1].artifact_id,
        itens[0][1].artifact_id,
    ]
    assert {i.origem for i in intervalos} == {ORIGEM_INTERVALO}


@pytest.mark.parametrize("pela_observacao", [False, True])
def test_conteudo_em_quarentena_nao_e_selecionado(pela_observacao: bool) -> None:
    item = (
        observar(PF, "201801", "A", 1, integridade_observada=EstadoIntegridade.QUARENTENA_TRUNCADO)
        if pela_observacao
        else observar(
            PF,
            "201801",
            "A",
            1,
            resultado=ResultadoTentativa.CONTEUDO_INVALIDO,
            integridade=EstadoIntegridade.QUARENTENA_TRUNCADO,
        )
    )
    selecao = selecionar_versao(_registro(item), _ATEND, _comp("201801"), uf="SP")
    assert selecao.estado is EstadoSelecao.EM_QUARENTENA


def test_so_tentativas_sem_conteudo_e_ausencia() -> None:
    falha = observar(PF, "201801", "A", 1, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    selecao = selecionar_versao(_registro(falha), _ATEND, _comp("201801"), uf="SP")
    assert selecao.estado is EstadoSelecao.AUSENTE
    assert selecao.observation_ids == (falha[0].observation_id,)


def test_multipartes_sem_declaracao_ou_com_parte_faltante_e_incompleta() -> None:
    a = observar(PF, "201801", "A", 1, parte="a")
    b = observar(PF, "201801", "B", 1, parte="b")
    sem_declaracao = selecionar_versao(_registro(a, b), _ATEND, _comp("201801"), uf="SP")
    assert sem_declaracao.estado is EstadoSelecao.INCOMPLETA
    assert "INDETERMINADA" in sem_declaracao.motivo
    declaradas = {(PF, "201801"): frozenset({"a", "b"})}
    so_a = selecionar_versao(_registro(a, partes=declaradas), _ATEND, _comp("201801"), uf="SP")
    assert so_a.estado is EstadoSelecao.INCOMPLETA
    completa = selecionar_versao(
        _registro(a, b, partes=declaradas), _ATEND, _comp("201801"), uf="SP"
    )
    assert completa.estado is EstadoSelecao.SELECIONADA
    assert len(completa.artifact_ids) == 2


def test_selecao_confere_competencia_e_fonte_do_conteudo() -> None:
    jan = observar(PF, "201801", "A", 1)
    selecao = selecionar_versao(_registro(jan), _ATEND, _comp("201801"), uf="SP")
    selecao.confere([jan[1]])
    vizinho = observar(PF, "201802", "B", 1)
    errada = selecao.model_copy(update={"artifact_ids": (vizinho[1].artifact_id,)})
    with pytest.raises(ValueError, match="selecao_competencia_divergente"):
        errada.confere([vizinho[1]])


_COMPS = ["201710", "201711", "201712", "201801", "201802"]


@st.composite
def _cenario(draw):
    itens = []
    for comp in draw(st.lists(st.sampled_from(_COMPS), max_size=6)):
        conteudo = draw(st.sampled_from(["A", "B"]))
        dias = draw(st.integers(min_value=0, max_value=40))
        resultado = draw(
            st.sampled_from([ResultadoTentativa.OBTIDO, ResultadoTentativa.NAO_ENCONTRADO])
        )
        itens.append(observar(PF, comp, conteudo + comp, dias, resultado=resultado))
    linhas = draw(
        st.lists(
            st.tuples(st.sampled_from([*_COMPS, None]), st.sampled_from([*_COMPS, None])),
            min_size=1,
            max_size=5,
        )
    )
    return itens, linhas


@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=40)
@given(_cenario(), st.sampled_from(["B_ATEND", "B_PROC", "M_TEMP_PADRAO"]), st.booleans())
def test_lote_equivale_a_selecao_por_registro(cenario, politica_id, com_corte) -> None:
    import duckdb

    from sustemporal.temporal.lote import selecionar_lote

    itens, linhas = cenario
    registro = _registro(*itens)
    corte = "2026-01-20T00:00:00+00:00" if com_corte else None
    config = _config(politica_id, corte)
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
    politica = carregar_politica(politica_id)
    selecionar_lote(
        con,
        "registros",
        [regra()],
        politica,
        registro,
        run_id="run_t",
        config=config,
    )
    lote = {
        linha[0]: linha[1:]
        for linha in con.execute(
            "SELECT row_id, base, competencia_requerida, estado, artifact_ids, observation_ids, "
            "motivo FROM selecao_versoes"
        ).fetchall()
    }
    for registro_linha in registros:
        (sel,) = select_snapshots(registro_linha, regra(), config, registro=registro).selecoes
        esperado = (
            None if sel.base is None else str(sel.base),
            None if sel.competencia_requerida is None else str(sel.competencia_requerida),
            str(sel.estado),
            ";".join(sorted(sel.artifact_ids)),
            ";".join(sorted(sel.observation_ids)),
            sel.motivo,
        )
        assert lote[registro_linha.row_id] == esperado


def test_gravar_selecoes_produz_dataset_com_hash_logico_e_contagem(tmp_path: Path) -> None:
    import duckdb

    from sustemporal.temporal.lote import gravar_selecoes, selecionar_lote

    jan = observar(PF, "201801", "A", 1)
    linhas = [registro_producao("201801", "201801", 0), registro_producao("201712", None, 1)]
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    con.executemany(
        "INSERT INTO registros VALUES (?, ?, ?)",
        [(r.row_id, str(r.competencia_atendimento), None) for r in linhas],
    )
    politica = carregar_politica("B_ATEND")
    selecionar_lote(
        con, "registros", [regra()], politica, _registro(jan), run_id="run_t", config=_config()
    )
    destino = tmp_path / "selecao"
    dataset = gravar_selecoes(con, destino, run_id="run_t", origem=OrigemDados.SINTETICO)
    colunas = [
        "run_id",
        "row_id",
        "rule_id",
        "fonte",
        "base",
        "competencia_requerida",
        "estado",
        "artifact_ids",
        "observation_ids",
        "motivo",
    ]
    linhas_tabela = con.execute(f"SELECT {', '.join(colunas)} FROM selecao_versoes").fetchall()  # noqa: S608
    assert dataset.schema_id == "selecao_versoes.v1"
    assert dataset.linhas == len(linhas_tabela) == 2
    assert dataset.hash_logico == hash_logico_linhas(colunas, linhas_tabela)
    assert dataset.artifact_ids == (jan[1].artifact_id,)
    assert dataset.caminho == str(destino / f"{dataset.dataset_id}.parquet")
