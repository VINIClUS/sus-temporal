"""Itens da revisão independente do T06 (PR #12): corte futuro, quarentena citada e lacunas."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.rules import RequisitoFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.temporal.lote import selecionar_lote
from sustemporal.temporal.registry import RegistroTemporal, registro_de
from sustemporal.temporal.selector import selecionar_versao, select_snapshots, unir_snapshots
from tests.fixtures.temporal_registro import docref, instante, observar, registro_producao, regra

if TYPE_CHECKING:
    from sustemporal.contracts.temporal import SnapshotSet

PF = FamiliaFonte.CNES_PF
ST = FamiliaFonte.CNES_ST
_ATEND = CriterioTemporal(fonte=PF, base=BaseTemporal.ATENDIMENTO)
_JAN = CompetenciaArquivo("201801")
_CORTE = "2026-01-20T00:00:00+00:00"


def _registro(*itens, partes=None) -> RegistroTemporal:
    base = registro_de([o for o, _ in itens], [v for _, v in itens if v is not None])
    return RegistroTemporal(base.observacoes, base.versoes, partes or {})


def _config(corte: str | None = None) -> RunConfig:
    campos: dict[str, object] = {
        "versao": "1",
        "politica_id": "B_ATEND",
        "piloto": {
            "uf": "SP",
            "competencias_processamento": ["201801"],
            "territorio": "catalog/territorio/drs_xi.yaml",
            "familias_fontes": ["SIA_PA", "CNES_PF"],
        },
    }
    if corte is not None:
        campos["corte_observacao"] = corte
    return RunConfig.model_validate(campos)


def _politica(*fontes: FamiliaFonte, pendente: bool = False) -> PoliticaTemporal:
    criterios = tuple(CriterioTemporal(fonte=f, base=BaseTemporal.ATENDIMENTO) for f in fontes)
    return PoliticaTemporal(
        politica_id="EXP",
        tipo=TipoPolitica.DOCUMENTADA if pendente else TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo="B_ATEND",
        criterios=criterios or (_ATEND,),
        documento=docref(pendente=True) if pendente else None,
    )


def _snapshot(registro: RegistroTemporal, corte: str | None, relogio_dias: int) -> SnapshotSet:
    return select_snapshots(
        registro_producao("201801", "201801"),
        regra(),
        _config(corte),
        registro=registro,
        relogio=lambda: instante(relogio_dias),
    )


def test_corte_no_futuro_nao_congela_o_conjunto() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    assert _snapshot(registro, _CORTE, 10).congelado is False
    assert _snapshot(registro, _CORTE, 19).congelado is True
    assert _snapshot(registro, None, 30).congelado is False
    futuro = _snapshot(registro, _CORTE, 10)
    assert unir_snapshots([futuro], relogio=lambda: instante(10)).congelado is False
    assert unir_snapshots([futuro], relogio=lambda: instante(30)).congelado is True


def test_quarentena_divergente_descartada_e_citada_no_motivo() -> None:
    integra = observar(PF, "201801", "A", 1)
    truncada = observar(
        PF,
        "201801",
        "B",
        2,
        resultado=ResultadoTentativa.CONTEUDO_INVALIDO,
        integridade=EstadoIntegridade.QUARENTENA_TRUNCADO,
    )
    sel = selecionar_versao(_registro(integra, truncada), _ATEND, _JAN, uf="SP")
    assert sel.estado is EstadoSelecao.SELECIONADA
    assert f"descartadas_quarentena={truncada[0].observation_id}" in sel.motivo


def test_partes_declaradas_com_so_arquivo_sem_parte_e_incompleta() -> None:
    declaradas = {(PF, "201801"): frozenset({"a", "b", "c"})}
    sel = selecionar_versao(
        _registro(observar(PF, "201801", "A", 1), partes=declaradas), _ATEND, _JAN, uf="SP"
    )
    assert sel.estado is EstadoSelecao.INCOMPLETA
    assert "ausentes=a,b,c" in sel.motivo


def _regra_com(*fontes: FamiliaFonte):
    base = regra()
    requisitos = tuple(
        RequisitoFonte(fonte=f, schema_id="cnes_estab_cbo.v1", campos=("cbo",)) for f in fontes
    )
    return base.model_copy(update={"requisitos_fonte": (base.requisitos_fonte[0], *requisitos)})


def test_ordem_das_fontes_na_regra_nao_muda_o_id_do_conjunto() -> None:
    registro = _registro(observar(PF, "201801", "A", 1), observar(ST, "201801", "S", 1))
    linha = registro_producao("201801", "201801")
    politica = _politica(PF, ST)
    ids = {
        select_snapshots(
            linha, _regra_com(*fontes), _config(), registro=registro, politica=politica
        ).snapshot_id
        for fontes in [(PF, ST), (ST, PF)]
    }
    assert len(ids) == 1


def test_observacao_integra_sem_versao_tem_motivo_proprio() -> None:
    obs, _versao = observar(PF, "201801", "A", 1, integridade_observada=EstadoIntegridade.OK)
    sel = selecionar_versao(_registro((obs, None)), _ATEND, _JAN, uf="SP")
    assert sel.estado is EstadoSelecao.EM_QUARENTENA
    assert sel.motivo.startswith("observacao_integra_sem_versao")


def test_politicas_do_catalogo_independem_do_diretorio_corrente(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sustemporal.temporal.politicas import carregar_politica

    monkeypatch.chdir(tmp_path)
    assert carregar_politica("B_ATEND").politica_id == "B_ATEND"


def test_borda_de_2018_atendimento_ausente_nao_usa_o_processamento() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    (sel,) = select_snapshots(
        registro_producao("201712", "201801"), regra(), _config(), registro=registro
    ).selecoes
    assert str(sel.competencia_requerida) == "201712"
    assert sel.estado is EstadoSelecao.AUSENTE


def _lote(registro: RegistroTemporal, politica: PoliticaTemporal) -> list[tuple[str, ...]]:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    linha = registro_producao("201801", "201801")
    con.execute("INSERT INTO registros VALUES (?, '201801', '201801')", [linha.row_id])
    selecionar_lote(con, "registros", [regra()], politica, registro, run_id="r", config=_config())
    return con.execute(
        "SELECT base, competencia_requerida, estado, artifact_ids, motivo FROM selecao_versoes"
    ).fetchall()


def test_lote_nao_resolve_ambigua_pelo_primeiro_candidato() -> None:
    a, b = observar(PF, "201801", "A", 1), observar(PF, "201801", "B", 2)
    ((_base, _comp, estado, artefatos, _motivo),) = _lote(_registro(a, b), _politica())
    assert estado == "AMBIGUA"
    assert sorted(artefatos.split(";")) == sorted([a[1].artifact_id, b[1].artifact_id])


def test_lote_respeita_a_pendencia_documental() -> None:
    registro = _registro(observar(PF, "201801", "A", 1))
    ((base, comp, estado, artefatos, motivo),) = _lote(registro, _politica(pendente=True))
    assert (base, comp, estado, artefatos) == ("ATENDIMENTO", "201801", "NAO_RESOLVIDA", "")
    assert motivo.startswith("politica_documento_pendente")


def _conjuntos() -> list[SnapshotSet]:
    registro = _registro(observar(PF, "201801", "A", 1), observar(PF, "201712", "B", 1))
    linhas = [registro_producao("201801", "201801", 0), registro_producao("201712", "201712", 1)]
    return [select_snapshots(linha, regra(), _config(), registro=registro) for linha in linhas]


def test_unir_snapshots_independe_da_ordem_da_entrada() -> None:
    conjuntos = _conjuntos()
    direto = unir_snapshots(conjuntos)
    invertido = unir_snapshots(list(reversed(conjuntos)))
    assert direto.snapshot_id == invertido.snapshot_id
    assert direto.selecoes == invertido.selecoes


def test_unir_snapshots_recusa_decisoes_divergentes_na_mesma_chave() -> None:
    linha = registro_producao("201801", "201801")
    conjuntos = [
        select_snapshots(linha, regra(), _config(), registro=_registro(obs))
        for obs in (observar(PF, "201801", "A", 1), observar(PF, "201801", "B", 1))
    ]
    with pytest.raises(ValueError, match="decisoes_divergentes"):
        unir_snapshots(conjuntos)


def test_catalogo_de_fontes_padrao_independe_do_diretorio_corrente(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sustemporal.temporal.selector import partes_esperadas_do_catalogo

    monkeypatch.chdir(tmp_path)
    assert isinstance(partes_esperadas_do_catalogo(_config()), dict)
