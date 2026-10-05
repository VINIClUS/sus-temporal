"""T05: correções da revisão do #31 (SINTETICO; nenhum resultado empírico)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import cobertura_sintetica, conjunto_sia_pa, registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.piloto_relatorio import (
    DRS_XI,
    coorte_piloto,
    linhas_tabela,
    metrica,
    relatorio_gravado,
)
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap
from tests.integration.test_pilot_report import (
    PF,
    _estados_disponibilidade,
    _execucao_ingest,
    _manifesto_com_falhas,
)

from sustemporal import cli
from sustemporal.contracts import OrigemDados
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.reporting.report import build_pilot_report

if TYPE_CHECKING:
    from sustemporal.contracts import EvaluationReport

RAIZ = Path(__file__).resolve().parents[2]
LEIAUTE_PA = RAIZ / "catalog" / "layouts" / "sia_pa.yaml"
CONFIGURACAO_INGEST = "configuracao_ingest.json"
CORTE_POSTERIOR = "2026-10-02T00:00:00Z"
FORA_DO_DRS_XI = "355030"
CAMPOS_DE_ERRO = ("pa_codoco", "pa_flqt", "pa_fler")
FISICOS_OMITIDOS = ("PA_INDICA", "PA_CODOCO", "PA_FLQT", "PA_FLER")
AUSENCIA_ESPERADA = {
    "quantidade_apresentada": (2, 3),
    "valor_apresentado": (1, 3),
    "quantidade_aprovada": (0, 3),
    "valor_aprovado": (0, 3),
    "pa_indica": (3, 3),
    "pa_codoco": (3, 3),
    "pa_flqt": (3, 3),
    "pa_fler": (3, 3),
}


def _relatorio_sem_campos_do_g0(tmp_path: Path) -> EvaluationReport:
    registros = [
        registro("C", "201801", "201801", PA_QTDPRO="", PA_VALPRO=""),
        registro("C", "201801", "201801", PA_QTDPRO=""),
        registro("I", "201802", "201802"),
        registro("C", "201801", "201801", PA_UFMUN=FORA_DO_DRS_XI, PA_QTDPRO="", PA_VALPRO=""),
    ]
    dataset = conjunto_sia_pa(tmp_path, registros, sem_campos=FISICOS_OMITIDOS)
    saida = tmp_path / "relatorio"
    saida.mkdir()
    entradas = [dataset, cobertura_sintetica(tmp_path, [dataset])]
    return build_pilot_report(entradas, coorte_piloto(), saida)


def test_campos_do_g0_ausentes_entram_na_taxa_com_denominador_explicito(tmp_path: Path) -> None:
    relatorio = _relatorio_sem_campos_do_g0(tmp_path)
    estratos = {m.estrato for m in relatorio.metricas if m.nome == "taxa_ausencia_campo"}
    assert estratos >= set(AUSENCIA_ESPERADA)
    for campo, (ausentes, denominador) in AUSENCIA_ESPERADA.items():
        taxa = metrica(relatorio, "taxa_ausencia_campo", campo)
        assert (taxa.numerador, taxa.denominador) == (ausentes, denominador)
    tabela = {str(lin["campo"]): lin for lin in linhas_tabela(relatorio, "piloto_campos.v1")}
    assert {c: (tabela[c]["ausentes"], tabela[c]["denominador"]) for c in AUSENCIA_ESPERADA} == (
        AUSENCIA_ESPERADA
    )


def test_campos_de_erro_so_entram_na_tabela_de_ausencia_de_campos(tmp_path: Path) -> None:
    relatorio = _relatorio_sem_campos_do_g0(tmp_path)
    campos = {str(lin["campo"]) for lin in linhas_tabela(relatorio, "piloto_campos.v1")}
    assert set(CAMPOS_DE_ERRO) <= campos
    dimensoes = {str(lin["dimensao"]) for lin in linhas_tabela(relatorio, "piloto_contagens.v1")}
    assert dimensoes == {"competencia_processamento", "instrumento", "cnes"}
    for tabela in relatorio.tabelas:
        assert not set(CAMPOS_DE_ERRO) & set(pq.read_schema(tabela.caminho).names)
    outras = {m.estrato for m in relatorio.metricas if m.nome != "taxa_ausencia_campo"}
    assert not outras & set(CAMPOS_DE_ERRO)


def _manifesto_so_com_parte_truncada(pasta: Path) -> None:
    store = pasta / "dados" / "raw"
    (pasta / "manifestos").mkdir(parents=True)
    truncada = dbc_pa([registro("C", "201801", "201801")], truncar_bytes=30)
    versoes = [
        artefato_pa(store, truncada),
        artefato_sigtap(store, zip_sigtap(pacote_padrao("201801"))),
        artefato_cnes(store, dbc_cnes(PF, [registro_pf("0012345", "225125")]), PF),
    ]
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)


def test_competencia_so_com_artefato_truncado_continua_ausente_e_incompleta(
    tmp_path: Path,
) -> None:
    _manifesto_so_com_parte_truncada(tmp_path)
    estados = _estados_disponibilidade(tmp_path, ["a"])
    assert set(estados.values()) == {"AUSENTE"}
    linhas = linhas_tabela(relatorio_gravado(tmp_path), "piloto_disponibilidade.v1")
    motivos = [str(lin["motivo"]) for lin in linhas]
    assert not any("populacao_vazia_no_recorte" in motivo for motivo in motivos)
    assert all("sia_pa_incompleto competencia=201801 motivo=" in m for m in motivos)
    assert all("sia_pa_ausente competencia=201801" in m for m in motivos)


def test_relatorio_sem_cobertura_da_ingestao_e_recusado_sem_publicar_nada(tmp_path: Path) -> None:
    dataset = conjunto_sia_pa(tmp_path, [registro("C", "201801", "201801")])
    saida = tmp_path / "relatorio"
    saida.mkdir()
    with pytest.raises(ConfigInvalida, match="relatorio_sem_cobertura"):
        build_pilot_report([dataset], coorte_piloto(), saida)
    assert list(saida.iterdir()) == []


def _ingest_completo(pasta: Path) -> Path:
    _manifesto_com_falhas(pasta)
    config = config_ingest(pasta, fontes_ingest(pasta, ["a"]))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    return config


def _saida_do_pilot_report(config: Path) -> int | str:
    """Código de saída da CLI; exceção que escapa dela vira `Tipo: mensagem`."""
    try:
        return cli.main(["pilot-report", "--config", str(config)])
    except Exception as erro:
        return f"{type(erro).__name__}: {erro}"


def _execucao_parcial(pasta: Path, nome: str, *presentes: str) -> None:
    execucao = pasta / "saidas" / "ingest" / nome
    execucao.mkdir(parents=True)
    for arquivo in presentes:
        (execucao / arquivo).write_text("{}", encoding="utf-8")


def test_execucao_incompleta_do_ingest_mais_nova_e_ignorada_com_aviso(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    _execucao_parcial(tmp_path, "execucao_29991231T235959000000Z_vazia")
    _execucao_parcial(
        tmp_path,
        "execucao_29991231T235959000001Z_sem_datasets",
        "manifesto_lido.json",
        CONFIGURACAO_INGEST,
    )
    _execucao_parcial(
        tmp_path,
        "execucao_29991231T235959000002Z_sem_configuracao",
        "datasets.jsonl",
        "manifesto_lido.json",
    )
    (tmp_path / "saidas" / "ingest" / "zzz_rascunho").mkdir()
    capsys.readouterr()
    assert _saida_do_pilot_report(config) == ExitCode.OK
    avisos = [
        linha
        for linha in capsys.readouterr().err.splitlines()
        if "pilot_report_ingest_incompleto" in linha
    ]
    assert len(avisos) == 3
    assert avisos[0].endswith(
        "execucao=execucao_29991231T235959000002Z_sem_configuracao "
        "faltando=configuracao_ingest.json"
    )
    assert avisos[1].endswith(
        "execucao=execucao_29991231T235959000001Z_sem_datasets faltando=datasets.jsonl"
    )
    assert avisos[2].endswith(
        "execucao=execucao_29991231T235959000000Z_vazia "
        "faltando=datasets.jsonl,manifesto_lido.json,configuracao_ingest.json"
    )
    assert relatorio_gravado(tmp_path).origem_dados is OrigemDados.SINTETICO


@pytest.mark.parametrize("estado", ["sem_pasta", "so_incompletas"])
def test_pilot_report_sem_execucao_completa_do_ingest_recusa(tmp_path: Path, estado: str) -> None:
    _manifesto_com_falhas(tmp_path)
    config = config_ingest(tmp_path, fontes_ingest(tmp_path, ["a"]))
    if estado == "so_incompletas":
        _execucao_parcial(tmp_path, "execucao_20261001T000000000000Z_vazia")
        _execucao_parcial(tmp_path, "execucao_20261002T000000000000Z_antiga", "datasets.jsonl")
    assert _saida_do_pilot_report(config) == ExitCode.CONFIG_INVALIDA
    assert not (tmp_path / "saidas" / "pilot").exists()


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _configuracao_gravada(pasta: Path) -> Path:
    arquivo = _execucao_ingest(pasta) / CONFIGURACAO_INGEST
    assert arquivo.is_file()
    return arquivo


def _divergencia(campo: str, ingest: str, atual: str) -> str:
    return f"ingest_com_configuracao_divergente campo={campo} ingest={ingest} atual={atual}"


def _erro_do_relatorio_recusado(
    config: Path, pasta: Path, capsys: pytest.CaptureFixture[str]
) -> str:
    """Texto do erro de um `pilot-report` recusado (saída 2) antes de gravar qualquer coisa."""
    capsys.readouterr()
    assert _saida_do_pilot_report(config) == ExitCode.CONFIG_INVALIDA
    assert not (pasta / "saidas" / "pilot").exists()
    return capsys.readouterr().err


def test_ingest_grava_a_configuracao_que_determina_a_selecao(tmp_path: Path) -> None:
    _ingest_completo(tmp_path)
    gravada = json.loads(_configuracao_gravada(tmp_path).read_text(encoding="utf-8"))
    assert gravada == {
        "uf": "SP",
        "corte_observacao": None,
        "familias_fontes": ["CNES_PF", "SIA_PA", "SIGTAP"],
        "catalogo_fontes_sha256": _sha256(tmp_path / "sources.yaml"),
        "leiaute_sia_pa_sha256": _sha256(LEIAUTE_PA),
    }


def test_corte_de_observacao_fica_na_configuracao_gravada_em_utc(tmp_path: Path) -> None:
    _manifesto_com_falhas(tmp_path)
    config = config_ingest(tmp_path, fontes_ingest(tmp_path, ["a"]), corte=CORTE_POSTERIOR)
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    gravada = json.loads(_configuracao_gravada(tmp_path).read_text(encoding="utf-8"))
    assert gravada["corte_observacao"] == "2026-10-02T00:00:00+00:00"


def test_catalogo_de_fontes_alterado_depois_do_ingest_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    antes = _sha256(tmp_path / "sources.yaml")
    fontes_ingest(tmp_path, ["a", "b"])
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    depois = _sha256(tmp_path / "sources.yaml")
    assert antes != depois
    assert _divergencia("catalogo_fontes_sha256", antes, depois) in erro


def test_catalogo_de_fontes_removido_depois_do_ingest_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    (tmp_path / "sources.yaml").unlink()
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert f"catalogo_fontes_ilegivel caminho={tmp_path / 'sources.yaml'}" in erro


def test_corte_de_observacao_alterado_depois_do_ingest_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest_completo(tmp_path)
    config = config_ingest(tmp_path, tmp_path / "sources.yaml", corte=CORTE_POSTERIOR)
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert _divergencia("corte_observacao", "None", "2026-10-02T00:00:00+00:00") in erro


def test_familias_alteradas_depois_do_ingest_recusam(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest_completo(tmp_path)
    config = config_ingest(tmp_path, tmp_path / "sources.yaml", familias="SIA_PA, SIGTAP")
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert _divergencia("familias_fontes", "CNES_PF,SIA_PA,SIGTAP", "SIA_PA,SIGTAP") in erro


def test_leiaute_do_sia_pa_alterado_depois_do_ingest_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ingest_completo(tmp_path)
    texto = LEIAUTE_PA.read_text(encoding="utf-8")
    assert "proveniencia: INFERIDA\n" in texto
    leiaute = tmp_path / "sia_pa_leiaute.yaml"
    leiaute.write_text(
        texto.replace(
            "proveniencia: INFERIDA\n", 'proveniencia: INFERIDA\nvalido_de: "201901"\n', 1
        ),
        encoding="utf-8",
    )
    config = config_ingest(tmp_path, tmp_path / "sources.yaml", leiaute_pa=leiaute)
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert _divergencia("leiaute_sia_pa_sha256", _sha256(LEIAUTE_PA), _sha256(leiaute)) in erro


def test_uf_gravada_diferente_da_atual_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    arquivo = _configuracao_gravada(tmp_path)
    gravada = json.loads(arquivo.read_text(encoding="utf-8"))
    arquivo.write_text(json.dumps({**gravada, "uf": "MG"}), encoding="utf-8")
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert _divergencia("uf", "MG", "SP") in erro


@pytest.mark.parametrize("conteudo", ["{", "[]", '"texto"'])
def test_configuracao_gravada_ilegivel_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], conteudo: str
) -> None:
    config = _ingest_completo(tmp_path)
    _configuracao_gravada(tmp_path).write_text(conteudo, encoding="utf-8")
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert "pilot_report_configuracao_ilegivel ingest=execucao_" in erro


def test_execucao_sem_configuracao_do_ingest_conta_como_incompleta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    _configuracao_gravada(tmp_path).unlink()
    erro = _erro_do_relatorio_recusado(config, tmp_path, capsys)
    assert "pilot_report_ingest_incompleto" in erro
    assert "faltando=configuracao_ingest.json" in erro
    assert "pilot_report_sem_ingest_completo" in erro


def test_mesma_configuracao_com_familias_em_outra_ordem_gera_o_relatorio(tmp_path: Path) -> None:
    _ingest_completo(tmp_path)
    config = config_ingest(tmp_path, tmp_path / "sources.yaml", familias="SIGTAP, SIA_PA, CNES_PF")
    assert _saida_do_pilot_report(config) == ExitCode.OK
    assert relatorio_gravado(tmp_path).origem_dados is OrigemDados.SINTETICO


def test_coorte_sem_competencia_na_cobertura_da_ingestao_e_recusada_sem_publicar_nada(
    tmp_path: Path,
) -> None:
    dataset = conjunto_sia_pa(tmp_path, [registro("C", "201801", "201801")])
    saida = tmp_path / "relatorio"
    saida.mkdir()
    entradas = [dataset, cobertura_sintetica(tmp_path, [dataset])]
    esperado = (
        "coorte_sem_competencias_na_cobertura coorte=piloto_sintetico "
        "inicio=202001 fim=202012 cobertura=201801,201802"
    )
    with pytest.raises(ConfigInvalida, match=esperado):
        build_pilot_report(entradas, coorte_piloto(inicio="202001", fim="202012"), saida)
    assert list(saida.iterdir()) == []


def test_pilot_report_com_coorte_explicita_sem_competencia_na_cobertura_recusa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ingest_completo(tmp_path)
    coorte = (
        "coorte:\n  cohort_id: sem_sobreposicao\n  uf: SP\n"
        f'  territorio: {DRS_XI}\n  inicio: "202001"\n  fim: "202012"\n'
    )
    with config.open("a", encoding="utf-8") as saida:
        saida.write(coorte)
    capsys.readouterr()
    assert _saida_do_pilot_report(config) == ExitCode.CONFIG_INVALIDA
    erro = capsys.readouterr().err
    assert "coorte_sem_competencias_na_cobertura coorte=sem_sobreposicao" in erro
    assert not list((tmp_path / "saidas" / "pilot").glob("*/relatorio.json"))
