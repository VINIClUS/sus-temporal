"""T04: matriz de cobertura `cobertura.v1` a partir das tabelas carregadas (SINTETICO)."""

from __future__ import annotations

from contextlib import closing
from typing import TYPE_CHECKING, Any

import duckdb
import pytest
from tests.fixtures.cnes_dbc import registro_pf
from tests.fixtures.piloto_conjuntos import (
    conjunto_cnes_pf,
    conjunto_sia_pa,
    conjuntos_sigtap,
    registro,
    runtime,
)

from sustemporal.contracts import CatalogoFamilias, OrigemDados
from sustemporal.ingest.coverage import CATALOGO_FAMILIAS, build_coverage
from sustemporal.rules.preparo import carregar_cobertura
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import DatasetRef

Chave = tuple[str, str, str, str]
COMPETENCIAS = ("201801", "201802")


def _catalogo() -> CatalogoFamilias:
    return CatalogoFamilias.model_validate(carregar_yaml(CATALOGO_FAMILIAS))


def _registros_padrao() -> list[dict[str, str]]:
    return [
        registro("C", "201801", "201801"),
        registro("I", "201801", "201712"),
        registro("S", "201801", "201801"),
        registro("A", "201801", "201712"),
        registro("A", "201801", "201801"),
    ]


def _matriz(dataset: DatasetRef) -> dict[Chave, dict[str, Any]]:
    with closing(duckdb.connect()) as con:
        relacao = con.execute("SELECT * FROM read_parquet($c)", {"c": dataset.caminho})
        nomes = [d[0] for d in relacao.description]
        linhas = [dict(zip(nomes, linha, strict=True)) for linha in relacao.fetchall()]
    return {
        (x["familia_regra"], x["instrumento"], x["competencia"], x["base_temporal"]): x
        for x in linhas
    }


def _cobertura(
    pasta: Path,
    auxiliares: list[DatasetRef],
    registros: list[dict[str, str]] | None = None,
) -> DatasetRef:
    sia_pa = conjunto_sia_pa(pasta, registros or _registros_padrao())
    return build_coverage(
        [sia_pa],
        auxiliares,
        COMPETENCIAS,
        pasta / "cobertura",
        runtime=runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
    )


@pytest.fixture
def completa(tmp_path: Path) -> DatasetRef:
    auxiliares = [*conjuntos_sigtap(tmp_path), conjunto_cnes_pf(tmp_path)]
    return _cobertura(tmp_path, auxiliares)


def test_matriz_completa_sem_nulo_na_chave_e_aceita_pelo_motor(completa: DatasetRef) -> None:
    matriz = _matriz(completa)
    esperadas = sum(len(f.instrumentos) for f in _catalogo().familias) * len(COMPETENCIAS) * 2
    assert len(matriz) == esperadas == completa.linhas
    assert all(None not in chave for chave in matriz)
    assert {x["estado"] for x in matriz.values()} <= {"DISPONIVEL", "INSUFICIENTE", "AUSENTE"}
    assert all((x["motivo"] is None) == (x["estado"] == "DISPONIVEL") for x in matriz.values())
    with closing(duckdb.connect()) as con:
        carregar_cobertura(con, completa)
        assert con.execute("SELECT count(*) FROM cobertura").fetchall()[0][0] == esperadas


def test_base_processamento_com_fonte_da_competencia_fica_disponivel(completa: DatasetRef) -> None:
    matriz = _matriz(completa)
    for familia in ("PROCEDIMENTO_CBO", "VIGENCIA_PROCEDIMENTO", "ESTABELECIMENTO_CBO"):
        assert matriz[(familia, "C", "201801", "PROCESSAMENTO")]["estado"] == "DISPONIVEL"


def test_base_atendimento_sem_versao_do_mes_de_atendimento_fica_ausente(
    completa: DatasetRef,
) -> None:
    linha = _matriz(completa)[("PROCEDIMENTO_CBO", "I", "201801", "ATENDIMENTO")]
    assert linha["estado"] == "AUSENTE"
    assert "201712" in linha["motivo"]
    assert _matriz(completa)[("PROCEDIMENTO_CBO", "C", "201801", "ATENDIMENTO")]["estado"] == (
        "DISPONIVEL"
    )


def test_atendimentos_em_meses_com_e_sem_versao_ficam_insuficientes(completa: DatasetRef) -> None:
    linha = _matriz(completa)[("VIGENCIA_PROCEDIMENTO", "A", "201801", "ATENDIMENTO")]
    assert linha["estado"] == "INSUFICIENTE"
    assert "201712" in linha["motivo"]


def test_fonte_carregada_nao_implica_familia_verificavel(tmp_path: Path) -> None:
    so_procedimento = conjuntos_sigtap(tmp_path, tabelas=["tb_procedimento"])
    matriz = _matriz(_cobertura(tmp_path, so_procedimento))
    chave = ("C", "201801", "PROCESSAMENTO")
    assert matriz[("VIGENCIA_PROCEDIMENTO", *chave)]["estado"] == "DISPONIVEL"
    for familia in ("PROCEDIMENTO_CBO", "INSTRUMENTO_REGISTRO", "ESTABELECIMENTO_CBO"):
        assert matriz[(familia, *chave)]["estado"] == "AUSENTE", familia


def test_instrumento_sem_registro_correspondente_no_sigtap_nao_fica_disponivel(
    completa: DatasetRef,
) -> None:
    matriz = _matriz(completa)
    assert matriz[("INSTRUMENTO_REGISTRO", "C", "201801", "PROCESSAMENTO")]["estado"] == (
        "DISPONIVEL"
    )
    linha = matriz[("INSTRUMENTO_REGISTRO", "S", "201801", "PROCESSAMENTO")]
    assert linha["estado"] == "AUSENTE"
    assert "co_registro=07" in linha["motivo"]


def test_competencia_sem_sia_pa_fica_ausente(completa: DatasetRef) -> None:
    matriz = _matriz(completa)
    linhas = [x for chave, x in matriz.items() if chave[2] == "201802"]
    assert linhas
    assert {x["estado"] for x in linhas} == {"AUSENTE"}
    assert all("sia_pa_ausente" in x["motivo"] for x in linhas)


def test_instrumento_sem_registros_fica_insuficiente(completa: DatasetRef) -> None:
    for base in ("ATENDIMENTO", "PROCESSAMENTO"):
        linha = _matriz(completa)[("PROCEDIMENTO_CBO", "P", "201801", base)]
        assert linha["estado"] == "INSUFICIENTE"
        assert "sem_registros" in linha["motivo"]


def test_competencia_de_atendimento_nula_fica_insuficiente(tmp_path: Path) -> None:
    registros = [registro("C", "201801", "201801"), registro("C", "201801", "")]
    matriz = _matriz(_cobertura(tmp_path, conjuntos_sigtap(tmp_path), registros))
    linha = matriz[("PROCEDIMENTO_CBO", "C", "201801", "ATENDIMENTO")]
    assert linha["estado"] == "INSUFICIENTE"
    assert "competencia_atendimento_nula" in linha["motivo"]
    assert matriz[("PROCEDIMENTO_CBO", "C", "201801", "PROCESSAMENTO")]["estado"] == "DISPONIVEL"


def test_conjunto_adulterado_e_recusado(tmp_path: Path) -> None:
    auxiliares = conjuntos_sigtap(tmp_path)
    adulterado = auxiliares[0].model_copy(update={"linhas": auxiliares[0].linhas + 1})
    with pytest.raises(ValueError, match="dataset_divergente"):
        _cobertura(tmp_path, [adulterado, *auxiliares[1:]])


def test_origem_dados_padrao_e_sintetico(tmp_path: Path) -> None:
    sia_pa = conjunto_sia_pa(tmp_path, _registros_padrao())
    dataset = build_coverage([sia_pa], [], COMPETENCIAS, tmp_path / "c", runtime=runtime(tmp_path))
    assert dataset.origem_dados is OrigemDados.SINTETICO
    assert {x["estado"] for x in _matriz(dataset).values()} <= {"AUSENTE", "INSUFICIENTE"}


def test_registro_sia_pa_deletado_nao_conta_na_cobertura(tmp_path: Path) -> None:
    registros = [registro("C", "201801", "201801"), registro("A", "201801", "201712")]
    sia_pa = conjunto_sia_pa(tmp_path, registros, deletados=[1])
    dataset = build_coverage(
        [sia_pa],
        conjuntos_sigtap(tmp_path),
        COMPETENCIAS,
        tmp_path / "c",
        runtime=runtime(tmp_path),
    )
    linha = _matriz(dataset)[("PROCEDIMENTO_CBO", "A", "201801", "ATENDIMENTO")]
    assert linha["estado"] == "INSUFICIENTE"
    assert "sem_registros" in linha["motivo"]


def test_sia_pa_incompleto_na_competencia_nunca_fica_disponivel(tmp_path: Path) -> None:
    sia_pa = conjunto_sia_pa(tmp_path, _registros_padrao())
    dataset = build_coverage(
        [sia_pa],
        conjuntos_sigtap(tmp_path),
        COMPETENCIAS,
        tmp_path / "c",
        runtime=runtime(tmp_path),
        sia_pa_incompleto={"201801": "QUARENTENA_TRUNCADO"},
    )
    linhas = [x for chave, x in _matriz(dataset).items() if chave[2] == "201801"]
    assert "DISPONIVEL" not in {x["estado"] for x in linhas}
    assert all("sia_pa_incompleto" in x["motivo"] for x in linhas if x["estado"] == "INSUFICIENTE")


def test_linhas_descartadas_do_pf_impedem_cobertura_disponivel(tmp_path: Path) -> None:
    pf = conjunto_cnes_pf(tmp_path, extras=[registro_pf("0012345", "")])
    matriz = _matriz(_cobertura(tmp_path, [*conjuntos_sigtap(tmp_path), pf]))
    linha = matriz[("ESTABELECIMENTO_CBO", "C", "201801", "PROCESSAMENTO")]
    assert linha["estado"] == "INSUFICIENTE"
    assert "linhas_descartadas" in linha["motivo"]
    assert matriz[("PROCEDIMENTO_CBO", "C", "201801", "PROCESSAMENTO")]["estado"] == "DISPONIVEL"
