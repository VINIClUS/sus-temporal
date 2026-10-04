"""T04: completude das partes do SIA-PA na ingestão, coerente com o seletor do T06 (SINTETICO)."""

from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path

import duckdb
import pytest
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.config import load_config
from sustemporal.contracts import (
    ArtifactVersion,
    BaseTemporal,
    CatalogoFamilias,
    ChaveArtefato,
    CriterioTemporal,
    DatasetRef,
    EstadoIntegridade,
    EstadoSelecao,
    FamiliaFonte,
    FormatoArquivo,
    TipoConteudo,
)
from sustemporal.contracts.artifacts import calcular_artifact_id
from sustemporal.contracts.temporal import CompetenciaArquivo
from sustemporal.errors import ExitCode
from sustemporal.store import caminho_conteudo
from sustemporal.temporal.registry import RegistroTemporal
from sustemporal.temporal.selector import partes_esperadas_do_catalogo, selecionar_versao
from sustemporal.yamlio import carregar_yaml

RAIZ = Path(__file__).resolve().parents[2]
DRS_XI = RAIZ / "catalog" / "territorio" / "drs_xi.yaml"
FONTES = RAIZ / "catalog" / "sources.yaml"
FAMILIAS = RAIZ / "catalog" / "familias.yaml"
PF = FamiliaFonte.CNES_PF


def _fontes(pasta: Path, partes: list[str] | None) -> Path:
    texto = FONTES.read_text(encoding="utf-8")
    marcador = '    multipartes: "true"\n'
    assert marcador in texto
    if partes is not None:
        declaracao = f'    partes_esperadas:\n      "201801": [{", ".join(partes)}]\n'
        texto = texto.replace(marcador, marcador + declaracao, 1)
    destino = pasta / "sources.yaml"
    destino.write_text(texto, encoding="utf-8")
    return destino


def _config(pasta: Path, fontes: Path) -> Path:
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        f"catalogos:\n  fontes: {fontes}",
        "runtime:",
        f"  raiz_dados: {pasta / 'dados'}",
        f"  raiz_manifestos: {pasta / 'manifestos'}",
        f"  raiz_saidas: {pasta / 'saidas'}",
        "  duckdb_memoria: 256MB",
        '  duckdb_threads: "1"',
        "piloto:",
        "  uf: SP",
        '  competencias_processamento: ["201801"]',
        f"  territorio: {DRS_XI}",
        "  familias_fontes: [SIA_PA, CNES_PF, SIGTAP]",
    ]
    caminho = pasta / "ingest.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def _executar(
    pasta: Path,
    partes_obtidas: list[str],
    declaradas: list[str] | None,
    *,
    republicar: bool = False,
) -> Path:
    store = pasta / "dados" / "raw"
    registros = [registro("C", "201801", "201801")]
    pf = [registro_pf("0012345", "225125")]
    versoes = [artefato_pa(store, dbc_pa(registros), parte=p) for p in partes_obtidas]
    if republicar:
        outro = [*registros, registro("C", "201801", "201801", PA_QTDPRO="2")]
        versoes.append(artefato_pa(store, dbc_pa(outro), parte=partes_obtidas[0]))
    versoes += [
        artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        artefato_cnes(store, dbc_cnes(PF, pf), PF),
    ]
    (pasta / "manifestos").mkdir(parents=True)
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)
    config = _config(pasta, _fontes(pasta, declaradas))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    return config


def _cobertura(pasta: Path, instrumento: str = "C") -> list[tuple[str, str, str, str | None]]:
    (execucao,) = sorted(p for p in (pasta / "saidas" / "ingest").iterdir() if p.is_dir())
    linhas = (execucao / "datasets.jsonl").read_text(encoding="utf-8").splitlines()
    datasets = [DatasetRef.model_validate(json.loads(linha)) for linha in linhas]
    (cobertura,) = [d for d in datasets if d.schema_id == "cobertura.v1"]
    with closing(duckdb.connect()) as con:
        return [
            (str(f), str(b), str(e), m)
            for f, b, e, m in con.execute(
                "SELECT familia_regra, base_temporal, estado, motivo FROM read_parquet($c) "
                "WHERE competencia = '201801' AND instrumento = $i",
                {"c": cobertura.caminho, "i": instrumento},
            ).fetchall()
        ]


@pytest.mark.parametrize(
    ("obtidas", "declaradas", "motivo"),
    [
        (["a"], ["a", "b"], "partes_ausentes ausentes=b"),
        (["a", "b"], ["a"], "partes_nao_declaradas extras=b"),
        (["a"], None, "completude=INDETERMINADA"),
    ],
    ids=["declarada_sem_versao", "presente_nao_declarada", "sem_declaracao"],
)
def test_partes_do_sia_pa_incompletas_nunca_deixam_a_cobertura_disponivel(
    tmp_path: Path, obtidas: list[str], declaradas: list[str] | None, motivo: str
) -> None:
    _executar(tmp_path, obtidas, declaradas)
    linhas = _cobertura(tmp_path)
    assert "DISPONIVEL" not in {estado for _, _, estado, _ in linhas}
    assert all(motivo in (m or "") for _, _, estado, m in linhas if estado == "INSUFICIENTE")


def _fonte_auxiliar(familia: str) -> FamiliaFonte:
    catalogo = CatalogoFamilias.model_validate(carregar_yaml(FAMILIAS))
    (entrada,) = [f for f in catalogo.familias if f.familia.value == familia]
    return next(r.fonte for r in entrada.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)


@pytest.mark.parametrize("republicar", [False, True], ids=["completo", "republicacao_divergente"])
def test_cobertura_disponivel_implica_selecao_selecionada_no_seletor(
    tmp_path: Path, republicar: bool
) -> None:
    config_caminho = _executar(tmp_path, ["a"], ["a"], republicar=republicar)
    config = load_config(config_caminho)
    registro_temporal = RegistroTemporal.de_manifesto(
        tmp_path / "manifestos" / "aquisicao.jsonl",
        partes_esperadas=partes_esperadas_do_catalogo(config),
    )
    competencia = CompetenciaArquivo("201801")
    disponiveis = [(f, b) for f, b, estado, _ in _cobertura(tmp_path) if estado == "DISPONIVEL"]
    assert bool(disponiveis) is not republicar
    for familia, base in disponiveis:
        if base != BaseTemporal.PROCESSAMENTO.value:
            continue
        for fonte in (FamiliaFonte.SIA_PA, _fonte_auxiliar(familia)):
            uf = None if fonte is FamiliaFonte.SIGTAP else "SP"
            criterio = CriterioTemporal(fonte=fonte, base=BaseTemporal.PROCESSAMENTO)
            selecao = selecionar_versao(registro_temporal, criterio, competencia, uf=uf)
            assert selecao.estado is EstadoSelecao.SELECIONADA, (familia, fonte, selecao.motivo)


def _resultados(pasta: Path) -> list[dict[str, str]]:
    (execucao,) = sorted(p for p in (pasta / "saidas" / "ingest").iterdir() if p.is_dir())
    texto = (execucao / "resultados.jsonl").read_text(encoding="utf-8")
    return [json.loads(linha) for linha in texto.splitlines()]


def test_versoes_de_outra_uf_nao_entram_na_ingestao_nem_na_cobertura(tmp_path: Path) -> None:
    store = tmp_path / "dados" / "raw"
    registros = [registro("C", "201801", "201801")]
    pf = [registro_pf("0012345", "225125")]
    pa_mg = artefato_pa(store, dbc_pa([registro("I", "201801", "201712")]), parte="b")
    pa_mg = _em_outra_uf(pa_mg, "MG")
    versoes = [
        artefato_pa(store, dbc_pa(registros)),
        artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        artefato_cnes(store, dbc_cnes(PF, pf), PF, uf="MG"),
        pa_mg,
    ]
    (tmp_path / "manifestos").mkdir(parents=True)
    registrar_versoes(tmp_path / "manifestos" / "aquisicao.jsonl", versoes)
    config = _config(tmp_path, _fontes(tmp_path, ["a"]))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    fora = {
        (r["fonte"], r.get("uf")) for r in _resultados(tmp_path) if r["estado"] == "FORA_DO_RECORTE"
    }
    assert fora == {("CNES_PF", "MG"), ("SIA_PA", "MG")}
    estados = {(f, b): e for f, b, e, _ in _cobertura(tmp_path)}
    assert estados[("ESTABELECIMENTO_CBO", "PROCESSAMENTO")] == "AUSENTE"
    assert estados[("VIGENCIA_PROCEDIMENTO", "PROCESSAMENTO")] == "DISPONIVEL"
    instrumento_i = {(f, b): m for f, b, _, m in _cobertura(tmp_path, "I")}
    assert "sem_registros" in (instrumento_i[("PROCEDIMENTO_CBO", "ATENDIMENTO")] or "")


def _em_outra_uf(versao: ArtifactVersion, uf: str) -> ArtifactVersion:
    chave = versao.chave.model_copy(update={"uf": uf})
    return versao.model_copy(
        update={"chave": chave, "artifact_id": calcular_artifact_id(chave, versao.sha256)}
    )


def test_listagem_de_diretorio_nao_passa_pelos_normalizadores(tmp_path: Path) -> None:
    store = tmp_path / "dados" / "raw"
    registros = [registro("C", "201801", "201801")]
    texto = b"PASP1801a.dbc\n"
    sha256 = hashlib.sha256(texto).hexdigest()
    caminho = caminho_conteudo(store, sha256, "txt")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(texto)
    chave = ChaveArtefato.model_validate(
        {
            "fonte": "SIA_PA",
            "uf": "SP",
            "competencia_arquivo": "201801",
            "canal": "ATUAL",
            "nome_original": "listagem.txt",
            "tipo_conteudo": TipoConteudo.LISTAGEM_DIRETORIO,
        }
    )
    listagem = ArtifactVersion(
        artifact_id=calcular_artifact_id(chave, sha256),
        chave=chave,
        localizador="sintetico://listagem",
        sha256=sha256,
        tamanho_bytes=len(texto),
        formato=FormatoArquivo.TXT,
        caminho_conteudo=str(caminho),
        integridade=EstadoIntegridade.OK,
    )
    versoes = [artefato_pa(store, dbc_pa(registros)), listagem]
    (tmp_path / "manifestos").mkdir(parents=True)
    registrar_versoes(tmp_path / "manifestos" / "aquisicao.jsonl", versoes)
    config = _config(tmp_path, _fontes(tmp_path, ["a"]))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    resultados = _resultados(tmp_path)
    assert listagem.artifact_id not in {r["artifact_id"] for r in resultados}
    assert [r["estado"] for r in resultados] == ["NORMALIZADO"]
