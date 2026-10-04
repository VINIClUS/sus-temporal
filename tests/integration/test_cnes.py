"""T04: CNES PF reduzido a contagens estabelecimento–CBO e ST a estabelecimentos (SINTETICO)."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pytest
from tests.fixtures.cnes_dbc import (
    IDENTIFICADORES_FALSOS,
    artefato_cnes,
    campos_cnes,
    dbc_cnes,
    registro_pf,
    registro_st,
)
from tests.fixtures.dbf_writer import CampoDbf

from sustemporal.contracts import (
    EsquemaCanonico,
    EstadoIntegridade,
    FamiliaFonte,
    LayoutSpec,
    OrigemDados,
    RuntimeConfig,
)
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.cnes import FamiliaReservada, carregar_leiautes_cnes, normalize_cnes
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.rules.auxiliares import preparar_auxiliar
from sustemporal.rules.catalog import carregar_regras, requisito_auxiliar
from sustemporal.rules.conteudo import verificar_conteudo

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sustemporal.contracts import ArtifactVersion, DatasetRef

ESQUEMAS = Path(__file__).resolve().parents[2] / "catalog" / "schemas"
PF = FamiliaFonte.CNES_PF
ST = FamiliaFonte.CNES_ST


def _runtime(pasta: Path) -> RuntimeConfig:
    return RuntimeConfig(raiz_dados=str(pasta), duckdb_memoria="256MB", duckdb_threads=1)


def _normalizar(
    pasta: Path, artefato: ArtifactVersion, fonte: FamiliaFonte, layout: LayoutSpec | None = None
) -> DatasetRef:
    return normalize_cnes(
        artefato,
        layout or carregar_leiautes_cnes()[fonte],
        pasta / "saida",
        runtime=_runtime(pasta),
        origem_dados=OrigemDados.SINTETICO,
    )


def _pf(pasta: Path, registros: Sequence[dict[str, str]], **extras: Any) -> ArtifactVersion:
    competencia = extras.pop("competencia", "201801")
    dados = dbc_cnes(PF, registros, **extras)
    return artefato_cnes(pasta, dados, PF, competencia=competencia)


def _linhas(dataset: DatasetRef) -> list[dict[str, Any]]:
    with closing(duckdb.connect()) as con:
        relacao = con.execute("SELECT * FROM read_parquet($c)", {"c": dataset.caminho})
        nomes = [d[0] for d in relacao.description]
        return [dict(zip(nomes, linha, strict=True)) for linha in relacao.fetchall()]


def _quarentena(pasta: Path, artefato: ArtifactVersion, fonte: FamiliaFonte) -> QuarentenaLeitura:
    with pytest.raises(QuarentenaLeitura) as erro:
        _normalizar(pasta, artefato, fonte)
    return erro.value


def _padrao() -> list[dict[str, str]]:
    return [
        registro_pf("2001234", "225125"),
        registro_pf("2001234", "225125", CPF_PROF="98765432100"),
        registro_pf("2001234", "2231F9"),
        registro_pf("0012345", "225125"),
    ]


def test_pf_vira_contagens_por_estabelecimento_cbo_com_zeros_preservados(tmp_path: Path) -> None:
    dataset = _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF)
    contagens = {(x["cnes"], x["cbo"]): x["n_vinculos"] for x in _linhas(dataset)}
    assert contagens == {
        ("2001234", "225125"): 2,
        ("2001234", "2231F9"): 1,
        ("0012345", "225125"): 1,
    }
    assert {x["competencia_arquivo"] for x in _linhas(dataset)} == {"201801"}
    assert dataset.schema_id == "cnes_estab_cbo.v1"
    assert dataset.linhas == 3


def test_pf_nao_leva_identificador_pessoal_para_a_tabela(tmp_path: Path) -> None:
    dataset = _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF)
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / "cnes_estab_cbo.yaml")
    linhas = _linhas(dataset)
    assert list(linhas[0]) == [c.nome for c in esquema.colunas]
    valores = {str(v) for linha in linhas for v in linha.values()}
    assert not valores & {*IDENTIFICADORES_FALSOS.values(), "98765432100"}
    assert Path(dataset.caminho).read_bytes().find(b"FICTICIO") == -1


def test_dataset_pf_confere_hash_logico_contagem_e_reconciliacao(tmp_path: Path) -> None:
    dataset = _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF)
    colunas = [c.nome for c in EsquemaCanonico.de_yaml(ESQUEMAS / "cnes_estab_cbo.yaml").colunas]
    with closing(duckdb.connect()) as con:
        con.execute("CREATE TABLE t AS SELECT * FROM read_parquet($c)", {"c": dataset.caminho})
        assert hash_logico_relacao(con, "t", colunas) == dataset.hash_logico
        tipos = {str(d[0]): str(d[1]) for d in con.execute("DESCRIBE t").fetchall()}
    assert tipos["n_vinculos"] == "BIGINT"
    assert dataset.reconciliacao is not None
    assert dataset.reconciliacao.fisicos == 4
    assert dict(dataset.reconciliacao.excluidas_por_motivo) == {"agregada_em_contagem": 1}


def test_pf_exclui_cnes_ou_cbo_invalido_e_deletado_com_motivo(tmp_path: Path) -> None:
    registros = [
        *_padrao(),
        registro_pf("2001234", ""),
        registro_pf("2001234", "2231f9"),
        registro_pf("12345", "225125"),
        registro_pf("2001234", "322205"),
    ]
    dataset = _normalizar(tmp_path, _pf(tmp_path, registros, deletados=[7]), PF)
    assert dataset.reconciliacao is not None
    assert dict(dataset.reconciliacao.excluidas_por_motivo) == {
        "agregada_em_contagem": 1,
        "cbo_VAZIO": 1,
        "cbo_CODIFICACAO_INVALIDA": 1,
        "cnes_CODIFICACAO_INVALIDA": 1,
        "deletado": 1,
    }
    assert dataset.linhas == 3


def test_cbo_alfanumerico_e_aceito_e_conta_separado(tmp_path: Path) -> None:
    registros = [registro_pf("2001234", "2231F9"), registro_pf("2001234", "223100")]
    linhas = _linhas(_normalizar(tmp_path, _pf(tmp_path, registros), PF))
    assert sorted(x["cbo"] for x in linhas) == ["223100", "2231F9"]


@pytest.mark.parametrize("valor", ["201712", "", "201802"])
def test_competen_diferente_da_competencia_do_arquivo_vai_para_quarentena(
    tmp_path: Path, valor: str
) -> None:
    registros = [*_padrao(), registro_pf("2001234", "225125", COMPETEN=valor)]
    erro = _quarentena(tmp_path, _pf(tmp_path, registros), PF)
    assert erro.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert "competencia_divergente" in erro.motivo


def test_pf_vazio_ou_sem_linha_valida_vai_para_quarentena(tmp_path: Path) -> None:
    erro = _quarentena(tmp_path, _pf(tmp_path, []), PF)
    assert "tabela_vazia" in erro.motivo
    invalidos = [registro_pf("2001234", ""), registro_pf("x", "225125")]
    pasta = tmp_path / "invalidos"
    assert "tabela_vazia" in _quarentena(pasta, _pf(pasta, invalidos), PF).motivo


def _campos_sem(nome: str) -> list[CampoDbf]:
    return [c for c in campos_cnes(PF) if c.nome != nome]


def _campos_com_largura(nome: str, largura: int) -> list[CampoDbf]:
    return [
        CampoDbf(c.nome, c.tipo, largura, c.decimais) if c.nome == nome else c
        for c in campos_cnes(PF)
    ]


_VARIANTES = {
    "campo_ausente": lambda: _campos_sem("UFMUNRES"),
    "largura_divergente": lambda: _campos_com_largura("CBO", 7),
    "ordem_trocada": lambda: list(reversed(campos_cnes(PF))),
}


@pytest.mark.parametrize("variante", sorted(_VARIANTES))
def test_mudanca_de_leiaute_do_pf_vai_para_quarentena(tmp_path: Path, variante: str) -> None:
    artefato = _pf(tmp_path, _padrao(), campos=_VARIANTES[variante]())
    assert _quarentena(tmp_path, artefato, PF).estado is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_pf_truncado_vai_para_quarentena(tmp_path: Path) -> None:
    artefato = _pf(tmp_path, _padrao(), truncar_bytes=40)
    _quarentena(tmp_path, artefato, PF)


def test_arquivo_ausente_e_inconclusivo(tmp_path: Path) -> None:
    artefato = _pf(tmp_path, _padrao())
    Path(artefato.caminho_conteudo).unlink()
    with pytest.raises(ArquivoAusente):
        _normalizar(tmp_path, artefato, PF)


@pytest.mark.parametrize("fonte", [FamiliaFonte.CNES_SR, FamiliaFonte.CNES_HB])
def test_sr_e_hb_sao_familias_reservadas_sem_tabela(tmp_path: Path, fonte: FamiliaFonte) -> None:
    artefato = artefato_cnes(tmp_path, dbc_cnes(PF, _padrao()), fonte)
    layout = carregar_leiautes_cnes()[PF].model_copy(update={"fonte": fonte})
    with pytest.raises(FamiliaReservada, match="familia_reservada"):
        _normalizar(tmp_path, artefato, PF, layout=layout)
    assert not (tmp_path / "saida").exists() or not any((tmp_path / "saida").iterdir())


def test_leiaute_de_outra_fonte_vai_para_quarentena(tmp_path: Path) -> None:
    artefato = _pf(tmp_path, _padrao())
    with pytest.raises(QuarentenaLeitura) as erro:
        _normalizar(tmp_path, artefato, PF, layout=carregar_leiautes_cnes()[ST])
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


@pytest.mark.parametrize(
    "sobrescrita",
    [{"codificacao": "utf-8"}, {"valido_de": "201901"}, {"valido_ate": "201712"}],
    ids=["codificacao", "antes_da_vigencia", "depois_da_vigencia"],
)
def test_leiaute_pf_com_codificacao_ou_vigencia_incompativel_vai_para_quarentena(
    tmp_path: Path, sobrescrita: dict[str, str]
) -> None:
    base = carregar_leiautes_cnes()[PF].model_dump()
    layout = LayoutSpec.model_validate({**base, **sobrescrita})
    with pytest.raises(QuarentenaLeitura) as erro:
        _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF, layout=layout)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_artefato_nao_integro_vai_para_quarentena(tmp_path: Path) -> None:
    dados = dbc_cnes(PF, _padrao())
    artefato = artefato_cnes(tmp_path, dados, integridade=EstadoIntegridade.QUARENTENA_TRUNCADO)
    assert _quarentena(tmp_path, artefato, PF).estado is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_versoes_da_mesma_competencia_sao_artefatos_distintos(tmp_path: Path) -> None:
    a = _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF)
    b = _normalizar(tmp_path, _pf(tmp_path, _padrao()[:3]), PF)
    assert a.artifact_ids != b.artifact_ids
    assert a.dataset_id != b.dataset_id


def test_origem_dados_padrao_e_sintetico(tmp_path: Path) -> None:
    artefato = _pf(tmp_path, _padrao())
    layout = carregar_leiautes_cnes()[PF]
    dataset = normalize_cnes(artefato, layout, tmp_path / "saida", runtime=_runtime(tmp_path))
    assert dataset.origem_dados is OrigemDados.SINTETICO


def _st(pasta: Path, registros: Sequence[dict[str, str]]) -> ArtifactVersion:
    return artefato_cnes(pasta, dbc_cnes(ST, registros), ST)


def test_st_vira_estabelecimentos_com_atributos_texto(tmp_path: Path) -> None:
    registros = [registro_st("0012345"), registro_st("2001234", TP_UNID="05")]
    dataset = _normalizar(tmp_path, _st(tmp_path, registros), ST)
    assert dataset.schema_id == "cnes_estabelecimento.v1"
    por_cnes = {x["cnes"]: x for x in _linhas(dataset)}
    assert por_cnes["0012345"]["municipio_estabelecimento"] == "354140"
    assert por_cnes["2001234"]["tipo_unidade"] == "05"
    assert {x["competencia_arquivo"] for x in por_cnes.values()} == {"201801"}


def test_st_duplicata_exata_entra_na_reconciliacao(tmp_path: Path) -> None:
    registros = [registro_st("0012345"), registro_st("0012345"), registro_st("2001234")]
    dataset = _normalizar(tmp_path, _st(tmp_path, registros), ST)
    assert dataset.linhas == 2
    assert dataset.reconciliacao is not None
    assert dict(dataset.reconciliacao.excluidas_por_motivo) == {"duplicata_exata": 1}


@pytest.mark.parametrize(
    ("registros", "motivo"),
    [
        ([registro_st("0012345"), registro_st("0012345", TP_UNID="05")], "chave_repetida"),
        ([registro_st("12345")], "codigo_invalido"),
        ([registro_st("0012345", COMPETEN="201712")], "competencia_divergente"),
    ],
    ids=["chave_divergente", "cnes_invalido", "competencia"],
)
def test_st_inconsistente_vai_para_quarentena(
    tmp_path: Path, registros: list[dict[str, str]], motivo: str
) -> None:
    assert motivo in _quarentena(tmp_path, _st(tmp_path, registros), ST).motivo


def test_motor_real_aceita_o_conjunto_estabelecimento_cbo(tmp_path: Path) -> None:
    dataset = _normalizar(tmp_path, _pf(tmp_path, _padrao()), PF)
    regras = [r for r in carregar_regras() if requisito_auxiliar(r).fonte is PF]
    assert regras
    for regra in regras:
        with closing(duckdb.connect()) as con:
            verificar_conteudo(con, dataset)
            assert preparar_auxiliar(con, regra, (dataset,)).leiaute == "OK"
