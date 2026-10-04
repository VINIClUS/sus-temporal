"""Proteção contra vazamento no T10: partições, atributos e ajuste só no treino (SINTETICO)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import duckdb
import pytest
from tests.fixtures.protocolo_dados import (
    MUNICIPIO_FORA,
    SPEC_PADRAO,
    LinhaPa,
    artefato,
    cenario_baseline,
    coorte,
    fontes_identidade,
    gravar_sia_pa,
    gravar_territorio,
)

from sustemporal.contracts.experiment import Atributo, FeatureSpec, Particao, SplitManifest
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO, auditar_features
from sustemporal.evaluation.split import build_splits
from sustemporal.rules.catalog import carregar_esquema

ESQUEMAS = (carregar_esquema("sia_pa.v1"), carregar_esquema("sia_pa_rotulos.v1"))


def _ler(caminho: str, colunas: str) -> list[tuple[object, ...]]:
    con = duckdb.connect()
    try:
        consulta = f"SELECT {colunas} FROM read_parquet($c) ORDER BY row_id"  # noqa: S608
        return con.execute(consulta, {"c": caminho}).fetchall()
    finally:
        con.close()


def _split(tmp_path: Path, linhas: list[LinhaPa], **kwargs: Any) -> SplitManifest:
    dataset = gravar_sia_pa(linhas, tmp_path / "pa.parquet")
    territorio = gravar_territorio(tmp_path / "territorio.yaml")
    kwargs.setdefault("fonte_por_artefato", fontes_identidade(linhas))
    return build_splits(dataset, coorte(territorio), tmp_path / "split", spec=SPEC_PADRAO, **kwargs)


def test_separacao_temporal(tmp_path: Path) -> None:
    art = artefato("a")
    linhas = [
        LinhaPa(art, 0, competencia_processamento="201905"),
        LinhaPa(art, 1, competencia_processamento="202301", competencia_atendimento="202212"),
        LinhaPa(artefato("b"), 0, competencia_processamento="202412"),
    ]
    linhas[0].artifact_id = artefato("c")
    manifesto = _split(tmp_path, linhas)
    assert manifesto.particoes is not None
    competencias = {
        particao: _ler(ds.caminho, "competencia_processamento, competencia_atendimento")
        for particao, ds in manifesto.particoes.items()
    }
    assert competencias[Particao.DESENVOLVIMENTO] == [("201905", "201801")]
    assert competencias[Particao.CALIBRACAO] == [("202301", "202212")]
    assert competencias[Particao.TESTE] == [("202412", "201801")]
    assert manifesto.linhas_por_particao == dict.fromkeys(Particao, 1)
    assert manifesto.artefatos_teste == (artefato("b"),)


def test_dependencia_fora_da_fronteira_nao_entra_na_populacao(tmp_path: Path) -> None:
    art = artefato("a")
    linhas = [
        LinhaPa(art, 0, competencia_processamento="202001"),
        LinhaPa(art, 1, competencia_processamento="201712"),
        LinhaPa(art, 2, competencia_processamento="202601"),
        LinhaPa(art, 3, competencia_processamento=None),
        LinhaPa(art, 4, municipio_estabelecimento=MUNICIPIO_FORA),
        LinhaPa(art, 5, municipio_estabelecimento=None),
        LinhaPa(art, 6, deletado=True),
    ]
    manifesto = _split(tmp_path, linhas)
    assert manifesto.linhas_por_particao[Particao.DESENVOLVIMENTO] == 1
    assert manifesto.exclusoes == {
        "fora_da_coorte": 2,
        "sem_competencia_processamento": 1,
        "fora_do_territorio": 1,
        "sem_municipio_estabelecimento": 1,
        "registro_deletado": 1,
    }


def test_republicacao_na_mesma_particao(tmp_path: Path) -> None:
    original, republicada = artefato("pa_2301_v1"), artefato("pa_2301_v2")
    linhas = [
        LinhaPa(original, 0, competencia_processamento="202301"),
        LinhaPa(republicada, 0, competencia_processamento="202301"),
    ]
    fontes = {original: "SIA_PA:SP:2301", republicada: "SIA_PA:SP:2301"}
    manifesto = _split(tmp_path, linhas, fonte_por_artefato=fontes)
    assert manifesto.particoes is not None
    calibracao = manifesto.particoes[Particao.CALIBRACAO]
    assert set(calibracao.artifact_ids) == {original, republicada}
    assert manifesto.limites is not None
    assert any("republicacoes_agrupadas_por_fonte" in limite for limite in manifesto.limites)


def test_republicacao_que_cruza_particoes_e_recusada(tmp_path: Path) -> None:
    original, republicada = artefato("v1"), artefato("v2")
    linhas = [
        LinhaPa(original, 0, competencia_processamento="202212"),
        LinhaPa(republicada, 0, competencia_processamento="202301"),
    ]
    fontes = {original: "fonte", republicada: "fonte"}
    with pytest.raises(ValueError, match="republicacao_em_particoes_distintas"):
        _split(tmp_path, linhas, fonte_por_artefato=fontes)


def test_limites_longitudinais_registrados(tmp_path: Path) -> None:
    manifesto = _split(tmp_path, [LinhaPa(artefato("a"), 0)])
    assert manifesto.limites is not None
    textos = " ".join(manifesto.limites)
    assert "sem_vinculo_longitudinal" in textos
    assert "republicacoes_agrupadas_por_fonte" in textos


@pytest.mark.parametrize("fontes", [None, {}])
def test_artefato_sem_fonte_conhecida_e_recusado(
    tmp_path: Path, fontes: dict[str, str] | None
) -> None:
    linhas = [LinhaPa(artefato("a"), 0), LinhaPa(artefato("b"), 0)]
    with pytest.raises(ValueError, match="split_sem_fonte_para_artefato"):
        _split(tmp_path, linhas, fonte_por_artefato=fontes)


def test_fonte_inspecionada_nao_volta_ao_teste_por_outra_versao(tmp_path: Path) -> None:
    inspecionada, republicada = artefato("v1_inspecionada"), artefato("v2_republicada")
    linhas = [LinhaPa(republicada, 0, competencia_processamento="202401")]
    fontes = {inspecionada: "SIA_PA:SP:2401", republicada: "SIA_PA:SP:2401"}
    with pytest.raises(ValueError, match="teste_contem_fonte_inspecionada"):
        _split(tmp_path, linhas, fonte_por_artefato=fontes, inspecionados=[inspecionada])


def test_teste_disjunto_de_inspecionados(tmp_path: Path) -> None:
    dev, teste = artefato("dev"), artefato("teste")
    linhas = [
        LinhaPa(dev, 0, competencia_processamento="202001"),
        LinhaPa(teste, 0, competencia_processamento="202401"),
    ]
    manifesto = _split(tmp_path / "ok", linhas, inspecionados=[dev])
    assert manifesto.artefatos_inspecionados == (dev,)
    with pytest.raises(ValueError, match="teste_contem_artefato_inspecionado"):
        _split(tmp_path / "recusa", linhas, inspecionados=[teste])


def test_split_deterministico(tmp_path: Path) -> None:
    linhas = [LinhaPa(artefato("a"), i, competencia_processamento="202001") for i in range(3)]
    primeiro = _split(tmp_path / "1", linhas)
    segundo = _split(tmp_path / "2", linhas)
    assert primeiro.split_id == segundo.split_id
    assert primeiro.hash_por_particao == segundo.hash_por_particao


def test_conteudo_divergente_do_dataset_e_falha_operacional(tmp_path: Path) -> None:
    dataset = gravar_sia_pa([LinhaPa(artefato("a"), 0)], tmp_path / "pa.parquet")
    gravar_sia_pa([LinhaPa(artefato("a"), 1)], tmp_path / "pa.parquet")
    territorio = gravar_territorio(tmp_path / "territorio.yaml")
    with pytest.raises(FalhaOperacionalErro, match="conteudo_divergente"):
        build_splits(dataset, coorte(territorio), tmp_path / "split", spec=SPEC_PADRAO)


def test_pertenca_historica_sem_historico_e_recusada(tmp_path: Path) -> None:
    dataset = gravar_sia_pa([LinhaPa(artefato("a"), 0)], tmp_path / "pa.parquet")
    territorio = gravar_territorio(tmp_path / "territorio.yaml")
    with pytest.raises(ValueError, match="pertenca_historica"):
        build_splits(
            dataset,
            coorte(territorio, pertenca="HISTORICA"),
            tmp_path / "split",
            spec=SPEC_PADRAO,
        )


@pytest.mark.parametrize(
    ("schema_id", "coluna"),
    [
        ("sia_pa.v1", "pa_codoco"),
        ("sia_pa.v1", "pa_flqt"),
        ("sia_pa.v1", "pa_fler"),
        ("sia_pa.v1", "pa_flidade"),
        ("sia_pa.v1", "pa_indica"),
        ("sia_pa.v1", "quantidade_aprovada"),
        ("sia_pa.v1", "valor_aprovado"),
        ("sia_pa.v1", "valor_apresentado"),
        ("sia_pa.v1", "pa_tpfin"),
        ("sia_pa.v1", "tipo_unidade"),
        ("sia_pa.v1", "idademin"),
        ("sia_pa.v1", "cnes_bruto"),
        ("sia_pa.v1", "cnes_motivo"),
        ("sia_pa.v1", "coluna_inexistente"),
        ("sia_pa.v1", "competencia_processamento"),
        ("sia_pa_rotulos.v1", "rotulo"),
        ("sia_pa_rotulos.v1", "contradicoes"),
    ],
)
def test_proibicao_campos_pos_processamento(schema_id: str, coluna: str) -> None:
    try:
        atributo = Atributo(
            nome="x", schema_id=schema_id, coluna=coluna, transformacao="CATEGORICA"
        )
        features = FeatureSpec(feature_set_id="f", atributos=(atributo,))
    except ValueError:
        return
    with pytest.raises(ValueError, match="feature_"):
        auditar_features(features, ESQUEMAS)


@pytest.mark.parametrize("coluna", ["pa_codoco_grupo", "valor_aprovado_log", "rotulo_anterior"])
def test_derivado_disfarcado_de_campo_proibido_e_recusado(coluna: str) -> None:
    atributo = Atributo(nome="x", schema_id="sia_pa.v1", coluna=coluna, transformacao="NUMERICA")
    features = FeatureSpec(feature_set_id="f", atributos=(atributo,))
    with pytest.raises(ValueError, match="feature_derivada_de_campo_proibido"):
        auditar_features(features, ESQUEMAS)


def test_transformacao_fora_da_lista_e_recusada() -> None:
    atributo = Atributo(nome="x", schema_id="sia_pa.v1", coluna="cbo", transformacao="ALVO_MEDIO")
    features = FeatureSpec(feature_set_id="f", atributos=(atributo,))
    with pytest.raises(ValueError, match="feature_transformacao_invalida"):
        auditar_features(features, ESQUEMAS)


def test_features_padrao_rastreadas_a_origem() -> None:
    origens = auditar_features(FEATURES_PADRAO, ESQUEMAS)
    assert [o.coluna for o in origens] == [a.coluna for a in FEATURES_PADRAO.atributos]
    assert all(o.papel == "ATRIBUTO" and o.schema_id == "sia_pa.v1" for o in origens)
    assert all("posição" in o.origem for o in origens)


def _parametros(run_saida: str) -> dict[str, Any]:
    caminho = Path(run_saida).with_name("parametros.json")
    return cast("dict[str, Any]", json.loads(caminho.read_text(encoding="utf-8")))


def test_transformacoes_ajustadas_so_no_treino(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path / "a")
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    parametros = _parametros(run.saidas[0].caminho)
    treino = [
        linha
        for linha in cenario.linhas
        if linha.competencia_processamento in {"201901", "202001"}
        and cenario.rotulo_por_row[linha.row_id] in {"NAO_APROVADO", "APROVADO_TOTAL"}
    ]
    idades = [linha.idade for linha in treino if linha.idade is not None]
    numericos = parametros["numericos"]
    assert isinstance(numericos, dict)
    assert numericos["idade"]["media"] == pytest.approx(sum(idades) / len(idades))
    assert parametros["ajustado_em"] == ["DESENVOLVIMENTO"]
    assert parametros["limiar_ajustado_em"] == ["CALIBRACAO"]

    alterado = cenario_baseline(
        tmp_path / "b",
        extras=tuple(
            (
                LinhaPa(
                    artefato("pa_202401"),
                    100 + i,
                    competencia_processamento="202401",
                    idade=900,
                    procedimento="9999999999",
                ),
                "NAO_APROVADO",
            )
            for i in range(20)
        ),
    )
    run_alterado = fit_baseline(
        alterado.split,
        FEATURES_PADRAO,
        alterado.config,
        tmp_path / "run_b",
        rotulos=alterado.rotulos,
    )
    assert _parametros(run_alterado.saidas[0].caminho) == parametros
