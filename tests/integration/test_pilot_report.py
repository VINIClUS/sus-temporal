"""T05: relatório do piloto de observabilidade (SINTETICO; nenhum resultado empírico)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import conjunto_sia_pa, registro
from tests.fixtures.piloto_ingest import cobertura_ingest, config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_falha, registrar_versoes
from tests.fixtures.piloto_relatorio import (
    coorte_piloto,
    linhas_tabela,
    metrica,
    relatorio_gravado,
)
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.contracts import (
    CanalPublicacao,
    ChaveArtefato,
    DatasetRef,
    EvaluationReport,
    FamiliaFonte,
    OrigemDados,
    ResultadoTentativa,
)
from sustemporal.contracts.experiment import ModoExecucao, Portao
from sustemporal.errors import ExitCode, PortaoRecusado
from sustemporal.gates import exigir_portao
from sustemporal.reporting.report import build_pilot_report
from sustemporal.yamlio import carregar_yaml

RAIZ = Path(__file__).resolve().parents[2]
MODELO_G0 = RAIZ / "experiments" / "decisions" / "MODELO_G0.yaml"
PF = FamiliaFonte.CNES_PF
FORA_DO_DRS_XI = "355030"


def _registros() -> list[dict[str, str]]:
    return [
        registro("C", "201801", "201801", PA_INDICA="5"),
        registro("C", "201801", "201712", PA_INDICA="6"),
        registro("I", "201801", "201711", PA_INDICA="0", PA_CBOCOD=""),
        registro("I", "201802", "201802", PA_INDICA="5"),
        registro("C", "201801", "201801", PA_UFMUN=FORA_DO_DRS_XI),
        registro("C", "201801", "201801"),
        registro("C", "201901", "201901"),
    ]


def _relatorio(
    tmp_path: Path, instrumentos: tuple[str, ...] = ()
) -> tuple[DatasetRef, EvaluationReport]:
    dataset = conjunto_sia_pa(tmp_path, _registros(), deletados=[5])
    saida = tmp_path / "relatorio"
    saida.mkdir()
    return dataset, build_pilot_report([dataset], coorte_piloto(instrumentos=instrumentos), saida)


def _contagens(relatorio: EvaluationReport, dimensao: str) -> dict[str, int]:
    linhas = linhas_tabela(relatorio, "piloto_contagens.v1")
    return {str(lin["valor"]): int(lin["linhas"]) for lin in linhas if lin["dimensao"] == dimensao}


def test_totais_reconciliam_com_as_tabelas_canonicas(tmp_path: Path) -> None:
    dataset, relatorio = _relatorio(tmp_path)
    exclusoes = {
        str(lin["motivo"]): int(lin["linhas"])
        for lin in linhas_tabela(relatorio, "piloto_exclusoes.v1")
    }
    assert exclusoes == {"deletado": 1, "fora_do_territorio": 1, "fora_do_intervalo_da_coorte": 1}
    incluidos = metrica(relatorio, "fracao_registros_incluidos")
    assert (incluidos.numerador, incluidos.denominador) == (4, dataset.linhas)
    assert incluidos.numerador + sum(exclusoes.values()) == dataset.linhas
    for dimensao in ("competencia_processamento", "instrumento", "cnes"):
        assert sum(_contagens(relatorio, dimensao).values()) == incluidos.numerador
    assert _contagens(relatorio, "competencia_processamento") == {"201801": 3, "201802": 1}
    assert _contagens(relatorio, "instrumento") == {"C": 2, "I": 2}


def test_instrumento_fora_da_coorte_vira_exclusao_com_motivo(tmp_path: Path) -> None:
    _, relatorio = _relatorio(tmp_path, instrumentos=("C",))
    exclusoes = {
        str(lin["motivo"]): int(lin["linhas"])
        for lin in linhas_tabela(relatorio, "piloto_exclusoes.v1")
    }
    assert exclusoes["instrumento_fora_da_coorte"] == 2
    assert _contagens(relatorio, "instrumento") == {"C": 2}


def test_taxa_de_ausencia_de_campo_tem_denominador_explicito(tmp_path: Path) -> None:
    _, relatorio = _relatorio(tmp_path)
    cbo = metrica(relatorio, "taxa_ausencia_campo", "cbo")
    assert (cbo.numerador, cbo.denominador, cbo.valor) == (1, 4, Decimal("0.250000"))
    campos = {str(lin["campo"]): lin for lin in linhas_tabela(relatorio, "piloto_campos.v1")}
    assert (campos["cbo"]["ausentes"], campos["cbo"]["denominador"]) == (1, 4)


def test_defasagem_entre_atendimento_e_processamento(tmp_path: Path) -> None:
    _, relatorio = _relatorio(tmp_path)
    defasagens = {
        lin["defasagem_meses"]: lin["linhas"]
        for lin in linhas_tabela(relatorio, "piloto_defasagem.v1")
    }
    assert defasagens == {0: 2, 1: 1, 2: 1}


def test_rotulos_antes_e_depois_do_preprocessamento_incluem_aprovacoes(tmp_path: Path) -> None:
    _, relatorio = _relatorio(tmp_path)
    linhas = linhas_tabela(relatorio, "piloto_rotulos.v1")
    antes = {lin["valor"]: lin["linhas"] for lin in linhas if lin["etapa"] == "ANTES"}
    depois = {lin["valor"]: lin["linhas"] for lin in linhas if lin["etapa"] == "DEPOIS"}
    assert antes == {"5": 2, "6": 1, "0": 1}
    assert depois == {"APROVADO_TOTAL": 2, "APROVADO_PARCIAL": 1, "NAO_APROVADO": 1}
    assert sum(antes.values()) == sum(depois.values()) == 4


def test_relatorio_sintetico_fica_exploratorio_com_aviso(tmp_path: Path) -> None:
    _, relatorio = _relatorio(tmp_path)
    assert relatorio.origem_dados is OrigemDados.SINTETICO
    assert relatorio.modo is ModoExecucao.EXPLORATORIO
    assert any(nota.startswith("dados_sinteticos_exploratorio") for nota in relatorio.notas)
    assert {t.origem_dados for t in relatorio.tabelas} == {OrigemDados.SINTETICO}


def _manifesto_com_falhas(pasta: Path) -> None:
    store = pasta / "dados" / "raw"
    (pasta / "manifestos").mkdir(parents=True)
    manifesto = pasta / "manifestos" / "aquisicao.jsonl"
    registrar_versoes(manifesto, [artefato_pa(store, dbc_pa(_registros()[:4]))])
    sigtap = ChaveArtefato.model_validate(
        {
            "fonte": FamiliaFonte.SIGTAP,
            "competencia_arquivo": "201801",
            "canal": CanalPublicacao.ATUAL,
            "nome_original": "TabelaUnificada_201801_v1801010000.zip",
        }
    )
    registrar_falha(manifesto, sigtap, ResultadoTentativa.NAO_ENCONTRADO, "sintetico://sigtap")
    pf = ChaveArtefato.model_validate(
        {
            "fonte": PF,
            "uf": "SP",
            "competencia_arquivo": "201801",
            "canal": CanalPublicacao.ATUAL,
            "nome_original": "PFSP1801.dbc",
        }
    )
    registrar_falha(manifesto, pf, ResultadoTentativa.FALHA_TRANSPORTE, "sintetico://pf")


def _ingest_e_relatorio(pasta: Path) -> None:
    config = config_ingest(pasta, fontes_ingest(pasta, ["a"]))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    assert cli.main(["pilot-report", "--config", str(config)]) == ExitCode.OK


def test_inconclusivos_separam_nao_encontrado_de_tentativa_sem_bytes(tmp_path: Path) -> None:
    _manifesto_com_falhas(tmp_path)
    _ingest_e_relatorio(tmp_path)
    relatorio = relatorio_gravado(tmp_path)
    classes = {
        (str(lin["fonte"]), str(lin["classe"]))
        for lin in linhas_tabela(relatorio, "piloto_inconclusivos.v1")
    }
    assert ("SIGTAP", "ausente_nao_encontrado_na_listagem") in classes
    assert ("CNES_PF", "ausente_tentativa_sem_bytes") in classes
    taxas = [m for m in relatorio.metricas if m.nome == "taxa_inconclusivo"]
    assert taxas
    assert all(m.numerador == m.denominador > 0 for m in taxas)


def test_disponibilidade_das_tabelas_vem_da_cobertura(tmp_path: Path) -> None:
    _manifesto_com_falhas(tmp_path)
    _ingest_e_relatorio(tmp_path)
    linhas = linhas_tabela(relatorio_gravado(tmp_path), "piloto_disponibilidade.v1")
    assert linhas
    assert "DISPONIVEL" not in {lin["estado"] for lin in linhas}
    assert {lin["competencia"] for lin in linhas} == {"201801"}
    assert {lin["familia_regra"] for lin in linhas} >= {"ESTABELECIMENTO_CBO", "PROCEDIMENTO_CBO"}


def _origem_local(pasta: Path) -> Path:
    sia = pasta / "origem" / "SIASUS" / "200801_" / "Dados"
    pf = pasta / "origem" / "CNES" / "200508_" / "Dados" / "PF"
    tup = pasta / "origem_tup"
    for diretorio in (sia, pf, tup):
        diretorio.mkdir(parents=True)
    (sia / "PASP1801a.dbc").write_bytes(dbc_pa(_registros()[:4]))
    (pf / "PFSP1801.dbc").write_bytes(dbc_cnes(PF, [registro_pf("0012345", "225125")]))
    pacote = zip_sigtap(pacote_padrao("201801"))
    (tup / "TabelaUnificada_201801_v1801010000.zip").write_bytes(pacote)
    texto = fontes_ingest(pasta, ["a"]).read_text(encoding="utf-8")
    texto = texto.replace(
        "ftp://ftp.datasus.gov.br/dissemin/publicos", (pasta / "origem").as_uri()
    ).replace("ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads", tup.as_uri())
    catalogo = pasta / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    return catalogo


def test_piloto_sintetico_ponta_a_ponta_pela_cli(tmp_path: Path) -> None:
    config = config_ingest(tmp_path, _origem_local(tmp_path))
    atendimento = tmp_path / "atendimento.txt"
    atendimento.write_text("201801\n201712\n201711\n201802\n", encoding="utf-8")
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.OK
    auxiliar = ["--passada", "auxiliar", "--competencias-atendimento", str(atendimento)]
    cli.main(["acquire", "--config", str(config), *auxiliar])
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    assert cli.main(["pilot-report", "--config", str(config)]) == ExitCode.OK
    relatorio = relatorio_gravado(tmp_path)
    assert relatorio.origem_dados is OrigemDados.SINTETICO
    exclusoes = {
        str(lin["motivo"]): int(lin["linhas"])
        for lin in linhas_tabela(relatorio, "piloto_exclusoes.v1")
    }
    assert exclusoes == {"fora_do_intervalo_da_coorte": 1}
    assert metrica(relatorio, "fracao_registros_incluidos").numerador == 3
    assert _contagens(relatorio, "competencia_processamento") == {"201801": 3}
    bases = {lin["base"] for lin in linhas_tabela(relatorio, "piloto_inconclusivos.v1")}
    assert bases == {"ATENDIMENTO", "PROCESSAMENTO"}


def test_modelo_g0_nao_libera_o_portao(tmp_path: Path) -> None:
    assert MODELO_G0.is_file()
    modelo = carregar_yaml(MODELO_G0)
    assert set(modelo["opcoes"]) == {"CONTINUAR", "AMPLIAR_SP", "RESTRINGIR_FAMILIAS", "REFORMULAR"}
    assert "limitacao_amostral" in modelo["separar"]
    assert "ausencia_estrutural" in modelo["separar"]
    decisoes = tmp_path / "experiments" / "decisions"
    decisoes.mkdir(parents=True)
    (decisoes / MODELO_G0.name).write_bytes(MODELO_G0.read_bytes())
    with pytest.raises(PortaoRecusado, match="portao_sem_decisao"):
        exigir_portao(decisoes, Portao.G0)


def _manifesto_completo(pasta: Path, registros: list[dict[str, str]], *, truncar: bool) -> None:
    store = pasta / "dados" / "raw"
    (pasta / "manifestos").mkdir(parents=True)
    versoes = [
        artefato_pa(store, dbc_pa(registros)),
        artefato_sigtap(store, zip_sigtap(pacote_padrao("201801"))),
        artefato_cnes(store, dbc_cnes(PF, [registro_pf("0012345", "225125")]), PF),
    ]
    if truncar:
        versoes.append(artefato_pa(store, dbc_pa(registros, truncar_bytes=30), parte="b"))
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)


def _estados_disponibilidade(pasta: Path, partes: list[str]) -> dict[tuple[str, str], str]:
    config = config_ingest(pasta, fontes_ingest(pasta, partes))
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    assert cli.main(["pilot-report", "--config", str(config)]) == ExitCode.OK
    linhas = linhas_tabela(relatorio_gravado(pasta), "piloto_disponibilidade.v1")
    return {
        (str(lin["familia_regra"]), str(lin["base_temporal"])): str(lin["estado"])
        for lin in linhas
        if lin["instrumento"] == "C"
    }


def test_disponibilidade_recalculada_so_com_a_populacao_do_territorio(tmp_path: Path) -> None:
    registros = [
        registro("C", "201801", "201801"),
        registro("C", "201801", "", PA_UFMUN=FORA_DO_DRS_XI),
    ]
    _manifesto_completo(tmp_path, registros, truncar=False)
    estados = _estados_disponibilidade(tmp_path, ["a"])
    assert cobertura_ingest(tmp_path)[("VIGENCIA_PROCEDIMENTO", "ATENDIMENTO")] != "DISPONIVEL"
    assert estados[("VIGENCIA_PROCEDIMENTO", "ATENDIMENTO")] == "DISPONIVEL"


def test_marcas_de_sia_pa_incompleto_da_ingestao_continuam_no_relatorio(tmp_path: Path) -> None:
    _manifesto_completo(tmp_path, [registro("C", "201801", "201801")], truncar=True)
    estados = _estados_disponibilidade(tmp_path, ["a", "b"])
    assert "DISPONIVEL" not in estados.values()
    linhas = linhas_tabela(relatorio_gravado(tmp_path), "piloto_disponibilidade.v1")
    assert all(
        "sia_pa_incompleto competencia=201801 motivo=" in str(lin["motivo"]) for lin in linhas
    )
