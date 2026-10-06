"""Fluxo ponta a ponta pela CLI em diretório limpo e `reproduce --offline` (T14); dados SINTETICO.

Originais gerados por código num FTP local (`acquire`), `ingest`, `validate` das três políticas,
`explain` e `counterfactual` nas linhas de ausência, mês faltante e borda de 2018, `freeze`
(recusado sem G0; com a decisão de teste, exploratório), `evaluate`, `annotation-export` e a
reprodução offline com hashes lógicos iguais. Nada aqui é resultado empírico: sintético nunca é
confirmatório, e a decisão G0 existe só no diretório temporário do teste.
"""

from __future__ import annotations

import json
import shutil
import socket
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest
from tests.fixtures.reproducao_fluxo import (
    Fluxo,
    Reproducao,
    adquirir_e_ingerir,
    artefatos_do_sia_pa,
    coleta_depois_do_congelamento,
    congelar_e_avaliar,
    derivar,
    iniciar,
    instantaneo,
    linha_do_ingest,
    metricas_refeitas,
    reproduzir,
    sem_evidencias,
    sem_os_artefatos,
    validar_janelas,
)
from tests.fixtures.reproducao_mundo import COMPETENCIAS, JANELAS, comando, escrever_config
from tests.fixtures.reproducao_parquet import adulterar_coluna, reordenar_linhas

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import FamiliaFonte
from sustemporal.contracts.artifacts import ResultadoTentativa
from sustemporal.contracts.counterfactual import CounterfactualSearchResult, MotivoParada
from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.contracts.experiment import (
    FreezeManifest,
    ModoExecucao,
    Particao,
    RunResult,
    SplitManifest,
)
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro
from sustemporal.explanation.cli import diretorio_explicacao
from sustemporal.reporting.reproduce_etapas import (
    competencias_da_particao,
    derivar_protocolo,
    validar_janela,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.slow

FAMILIAS = ("CNES_PF", "CNES_ST", "SIA_PA", "SIGTAP")
ESQUEMAS_DA_SAIDA = (
    "avaliacoes.v1",
    "evidencias.v1",
    "selecao_versoes.v1",
    "agregados_registro.v1",
    "falhas.v1",
)
METODOS = ("M_TEMP", "B_ATEND", "B_PROC")
POLITICAS = ("m_temp_nao_resolvida", "b_atend_exploratoria", "b_proc_exploratoria")
POLITICA_ESTRAGADA = "b_atend_exploratoria"
ITENS_DA_REPRODUCAO = {
    "conjunto:sia_pa.v1",
    "conjunto:sia_pa_rotulos.v1",
    "split:split_id",
    *(f"split:particao:{p.value}" for p in Particao),
    *(f"split:rotulos:{p.value}" for p in Particao),
    *(f"insumos:{politica}" for politica in POLITICAS),
    *(f"saida:{m}:{s}" for m in METODOS for s in ESQUEMAS_DA_SAIDA),
    "metricas",
    "notas",
}
BYTES_DIFERENTES = "BYTES_DIFERENTES_HASH_LOGICO_IGUAL"
EVIDENCIAS = "evidencias.v1"


@pytest.fixture(scope="module")
def fluxo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fluxo]:
    with pytest.MonkeyPatch.context() as mp:
        estado = iniciar(tmp_path_factory.mktemp("reproduz"), mp)
        adquirir_e_ingerir(estado)
        validar_janelas(estado)
        derivar(estado, inspecionados=artefatos_do_sia_pa(estado, "dev"))
        congelar_e_avaliar(estado)
        yield estado


def _freeze(fluxo: Fluxo) -> str:
    assert fluxo.freeze_id is not None
    return fluxo.freeze_id


def _estados(run: RunResult) -> dict[str, set[str]]:
    ref = next(saida for saida in run.saidas if saida.schema_id == "avaliacoes.v1")
    estados: dict[str, set[str]] = {}
    for linha in pq.read_table(ref.caminho, columns=["row_id", "estado"]).to_pylist():
        estados.setdefault(linha["row_id"], set()).add(linha["estado"])
    return estados


def _linhas_de_dev(fluxo: Fluxo) -> dict[str, str]:
    return {
        "ausencia": linha_do_ingest(fluxo, atendimento="201801", instrumento="I"),
        "mes_faltante": linha_do_ingest(fluxo, atendimento="201802", instrumento="C"),
        "borda_de_2018": linha_do_ingest(fluxo, atendimento="201712", instrumento="C"),
    }


def test_acquire_no_ftp_local_traz_o_que_existe_e_a_ausencia_sai_com_falha(fluxo: Fluxo) -> None:
    assert fluxo.codigos["acquire_primaria"] == ExitCode.OK
    assert fluxo.codigos["acquire_auxiliar"] == ExitCode.FALHA_OPERACIONAL
    estado = Manifesto(fluxo.mundo.raiz / "manifestos" / "aquisicao.jsonl").ler()
    obtidos = Counter(
        (o.chave.fonte.value, str(o.chave.competencia_arquivo))
        for o in estado.observacoes
        if o.chave.competencia_arquivo is not None and o.artifact_id is not None
    )
    assert obtidos == {(familia, c): 1 for familia in FAMILIAS for c in COMPETENCIAS}


def test_ingest_normaliza_so_o_que_foi_adquirido(fluxo: Fluxo) -> None:
    assert fluxo.codigos["ingest"] == ExitCode.OK
    assert fluxo.ingest is not None
    texto = (fluxo.ingest / "resultados.jsonl").read_text(encoding="utf-8")
    resultados = [json.loads(linha) for linha in texto.splitlines()]
    assert Counter(r["estado"] for r in resultados) == {"NORMALIZADO": 28}
    assert Counter(r["fonte"] for r in resultados) == {
        "SIA_PA": 4,
        "CNES_PF": 4,
        "CNES_ST": 4,
        "SIGTAP": 16,
    }


def test_as_tres_politicas_se_dividem_nas_linhas_de_borda_e_de_mes_faltante(fluxo: Fluxo) -> None:
    linhas = _linhas_de_dev(fluxo)
    documentada = _estados(fluxo.execucoes[("dev", "documented")])
    atendimento = _estados(fluxo.execucoes[("dev", "atendimento")])
    processamento = _estados(fluxo.execucoes[("dev", "processamento")])
    assert all(estados == {"INCONCLUSIVO"} for estados in documentada.values())
    assert atendimento[linhas["ausencia"]] == {"CONFORME", "VIOLACAO"}
    assert atendimento[linhas["mes_faltante"]] == {"INCONCLUSIVO"}
    assert atendimento[linhas["borda_de_2018"]] == {"INCONCLUSIVO"}
    assert processamento[linhas["mes_faltante"]] == {"CONFORME"}
    assert "VIOLACAO" in processamento[linhas["borda_de_2018"]]


@pytest.mark.parametrize(
    ("linha", "trechos"),
    [
        ("ausencia", ["ficou em VIOLACAO", "não é causa oficial", "não prova inexistência"]),
        ("mes_faltante", ["competência 201802", "O mês vizinho nunca substitui"]),
        ("borda_de_2018", ["competência 201712", "nunca a violação"]),
    ],
)
def test_explain_das_tres_linhas_nunca_atribui_causa_nem_usa_o_mes_vizinho(
    fluxo: Fluxo, linha: str, trechos: list[str]
) -> None:
    run = fluxo.execucoes[("dev", "atendimento")]
    row = _linhas_de_dev(fluxo)[linha]
    argumentos = ["--config", str(fluxo.configs["dev"]), "--run", run.run_id, "--row", row]
    assert comando("explain", *argumentos) == ExitCode.OK
    pasta = diretorio_explicacao(fluxo.mundo.saidas, run.run_id, row)
    texto = " ".join((pasta / "explicacao.txt").read_text(encoding="utf-8").split())
    assert "SINTETICO" in texto
    for trecho in trechos:
        assert trecho in texto


def _buscas(fluxo: Fluxo) -> list[CounterfactualSearchResult]:
    arquivos = sorted((fluxo.mundo.saidas / "contrafactuais").rglob("contrafactual.json"))
    return [
        CounterfactualSearchResult.model_validate_json(a.read_text(encoding="utf-8"))
        for a in arquivos
    ]


def test_counterfactual_so_busca_na_linha_com_violacao(fluxo: Fluxo) -> None:
    run = fluxo.execucoes[("dev", "atendimento")]
    base = ["counterfactual", "--config", str(fluxo.configs["dev"]), "--run", run.run_id]
    linhas = _linhas_de_dev(fluxo)
    assert comando(*base, "--row", linhas["mes_faltante"]) == ExitCode.CONFIG_INVALIDA
    assert comando(*base, "--row", linhas["borda_de_2018"]) == ExitCode.CONFIG_INVALIDA
    assert _buscas(fluxo) == []
    assert comando(*base, "--row", linhas["ausencia"]) == ExitCode.OK
    (busca,) = _buscas(fluxo)
    assert busca.motivo_parada is MotivoParada.MINIMO_ENCONTRADO
    operacoes = [[o.op_id for o in solucao.operacoes] for solucao in busca.solucoes]
    assert operacoes == [["INCLUIR_CBO_NO_ESTABELECIMENTO"]]
    assert busca.aprovacao_garantida is False


def test_freeze_e_recusado_sem_g0_e_com_a_decisao_de_teste_fica_exploratorio(fluxo: Fluxo) -> None:
    assert fluxo.codigos["freeze_sem_g0"] == ExitCode.PORTAO_RECUSADO
    assert fluxo.codigos["freeze"] == ExitCode.OK
    caminho = fluxo.mundo.congelamentos / f"{_freeze(fluxo)}.json"
    manifesto = FreezeManifest.model_validate_json(caminho.read_text(encoding="utf-8"))
    assert manifesto.decisao_g0.endswith("g0_teste.yaml")
    assert set(manifesto.entradas_validacao or {}) == set(POLITICAS)
    assert {d.schema_id for d in manifesto.datasets} == {"sia_pa.v1", "sia_pa_rotulos.v1"}


def test_sintetico_nunca_e_confirmatorio(fluxo: Fluxo) -> None:
    assert fluxo.codigos["evaluate_sem_exploratory"] == ExitCode.PORTAO_RECUSADO
    confirmatoria = fluxo.mundo.raiz / "config_confirmatoria.yaml"
    texto = fluxo.configs["cal"].read_text(encoding="utf-8")
    confirmatoria.write_text(f"{texto}modo: CONFIRMATORIO\nfreeze_id: {_freeze(fluxo)}\n")
    argumentos = ["--config", str(confirmatoria), "--freeze", _freeze(fluxo)]
    assert comando("evaluate", *argumentos) == ExitCode.CONFIG_INVALIDA
    (rodada,) = ler_registro(fluxo.mundo.congelamentos / "registro_execucoes.jsonl")
    assert (rodada["modo"], rodada["origem_dados"]) == ("EXPLORATORIO", "SINTETICO")
    assert rodada["decisao_g2"] is None


def test_evaluate_exploratorio_registra_a_rodada_e_annotation_export_prepara_o_pacote(
    fluxo: Fluxo,
) -> None:
    assert fluxo.codigos["evaluate"] == ExitCode.OK
    assert fluxo.codigos["annotation_export"] == ExitCode.OK
    anotacao = fluxo.mundo.saidas / "anotacao" / _freeze(fluxo)
    assert {p.name for p in anotacao.iterdir()} == {"amostra.json", "pacote", "privado"}
    (relatorio,) = (fluxo.mundo.saidas / "avaliacao" / _freeze(fluxo)).glob("rep_*.json")
    avaliado = EvaluationReport.model_validate_json(relatorio.read_text(encoding="utf-8"))
    assert avaliado.modo is ModoExecucao.EXPLORATORIO
    assert "particao=CALIBRACAO" in avaliado.notas
    assert len(avaliado.metricas) > 100


@pytest.fixture(scope="module")
def reproducao(fluxo: Fluxo) -> Reproducao:
    """`reproduce --offline` com a config do protocolo, no destino padrão (1 thread).

    Roda com um arquivo novo, uma republicação e uma ausência registrados depois do congelamento:
    o que o congelamento não resolveu não entra na reconstrução.
    """
    with coleta_depois_do_congelamento(fluxo) as coletadas:
        antes = instantaneo(fluxo)
        feita = reproduzir(fluxo, fluxo.configs["teste"])
        depois = instantaneo(fluxo)
    return Reproducao(feita.codigo, feita.out, feita.conteudo, antes, depois, tuple(coletadas))


def test_reproduce_offline_reproduz_com_hashes_logicos_iguais(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    assert reproducao.codigo == ExitCode.OK
    assert reproducao.conteudo["freeze_id"] == _freeze(fluxo)
    assert reproducao.conteudo["relatorio_refeito"].startswith("rep_")
    assert reproducao.conteudo["resultado"] == "IGUAL"
    assert set(reproducao.itens) == ITENS_DA_REPRODUCAO
    assert set(reproducao.situacoes.values()) == {"IGUAL"}
    assert reproducao.conteudo["modo"] == "EXPLORATORIO"
    assert reproducao.conteudo["origem_dados"] == "SINTETICO"


def test_reproduce_refaz_o_fluxo_inteiro_no_diretorio_novo(reproducao: Reproducao) -> None:
    assert reproducao.codigo == ExitCode.OK
    esperados = {"manifestos", "ingest", "split", "janelas", "runs", "avaliacao", "reproducao.json"}
    assert {p.name for p in reproducao.out.iterdir()} == esperados
    assert len(list(reproducao.out.glob("split/spl_*.json"))) == 2
    assert len(list(reproducao.out.glob("runs/val_*/run_result.json"))) == 6


def test_reproduce_nao_altera_nenhum_original(reproducao: Reproducao) -> None:
    assert reproducao.codigo == ExitCode.OK
    assert reproducao.antes
    assert reproducao.antes == reproducao.depois


def test_reproduce_registra_a_diferenca_de_codigo_sem_chamar_de_divergencia(
    reproducao: Reproducao,
) -> None:
    assert reproducao.codigo == ExitCode.OK
    *_, observacao = reproducao.conteudo["observacoes"]
    assert observacao.startswith("codigo_diferente_do_congelado")


def _manifesto(fluxo: Fluxo) -> FreezeManifest:
    caminho = fluxo.mundo.congelamentos / f"{_freeze(fluxo)}.json"
    return FreezeManifest.model_validate_json(caminho.read_text(encoding="utf-8"))


def _original_do_congelamento(fluxo: Fluxo, schema_id: str) -> Path:
    return Path(next(d for d in _manifesto(fluxo).datasets if d.schema_id == schema_id).caminho)


def test_reproduce_refaz_o_split_com_os_artefatos_inspecionados_do_congelamento(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    inspecionados = artefatos_do_sia_pa(fluxo, "dev")
    assert len(inspecionados) == 2
    assert _manifesto(fluxo).split.artefatos_inspecionados == inspecionados
    item = reproducao.itens["split:split_id"]
    assert item["situacao"] == "IGUAL"
    refeito = reproducao.out / "split" / f"{item['obtido']}.json"
    split = SplitManifest.model_validate_json(refeito.read_text(encoding="utf-8"))
    assert split.artefatos_inspecionados == inspecionados


def test_reproduce_ignora_o_que_foi_coletado_depois_do_congelamento(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    resultados = [o.resultado for o in reproducao.coletadas]
    obtido, ausente = ResultadoTentativa.OBTIDO, ResultadoTentativa.NAO_ENCONTRADO
    assert resultados == [obtido, obtido, ausente] * 2
    depois = reproducao.coletadas[:3]
    assert all(o.observado_em > _manifesto(fluxo).criado_em for o in depois)
    assert reproducao.codigo == ExitCode.OK
    assert set(reproducao.situacoes.values()) == {"IGUAL"}


def test_reproduce_ignora_o_que_foi_coletado_entre_o_ingest_e_o_congelamento(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    entre = reproducao.coletadas[3:]
    assert [o.resultado for o in entre] == [
        ResultadoTentativa.OBTIDO,
        ResultadoTentativa.OBTIDO,
        ResultadoTentativa.NAO_ENCONTRADO,
    ]
    assert all(o.observado_em < _manifesto(fluxo).criado_em for o in entre)
    assert reproducao.codigo == ExitCode.OK
    assert set(reproducao.situacoes.values()) == {"IGUAL"}
    assert fluxo.ingest is not None
    lido = json.loads((fluxo.ingest / "manifesto_lido.json").read_text(encoding="utf-8"))
    assert reproducao.conteudo["observacoes"][:3] == [
        f"manifesto_do_ingest execucao={fluxo.ingest.name} linhas={lido['linhas']}",
        "artefatos_depois_do_ingest_ignorados n=4",
        "observacoes_depois_do_ingest_ignoradas n=6",
    ]


def test_reproduce_mantem_na_janela_o_arquivo_cuja_competencia_difere_da_das_linhas(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    teste = (_manifesto(fluxo).split.particoes or {})[Particao.TESTE]
    (artefato,) = teste.artifact_ids
    versoes = Manifesto(fluxo.mundo.raiz / "manifestos" / "aquisicao.jsonl").ler().versoes
    assert str(versoes[artefato].chave.competencia_arquivo) == "202401"
    assert competencias_da_particao(teste) == ("202402",)
    assert reproducao.codigo == ExitCode.OK
    assert reproducao.conteudo["resultado"] == "IGUAL"


def test_reproduce_com_4_threads_e_bytes_diferentes_nos_originais_segue_igual(
    fluxo: Fluxo, reproducao: Reproducao
) -> None:
    config = escrever_config(fluxo.mundo, "teste4", JANELAS["teste"], threads=4)
    rotulos = _original_do_congelamento(fluxo, "sia_pa_rotulos.v1")
    original = reordenar_linhas(rotulos)
    try:
        de_4 = reproduzir(fluxo, config, fluxo.mundo.raiz / "reproducao_4_threads")
    finally:
        rotulos.write_bytes(original)
    assert de_4.codigo == ExitCode.OK
    assert reproducao.codigo == ExitCode.OK
    situacoes = de_4.situacoes
    assert situacoes.pop("conjunto:sia_pa_rotulos.v1") == BYTES_DIFERENTES
    assert set(situacoes.values()) == {"IGUAL"}
    assert de_4.conteudo["resultado"] == BYTES_DIFERENTES
    assert "config_diferente_da_congelada" in de_4.conteudo["observacoes"]
    assert metricas_refeitas(de_4.out) == metricas_refeitas(reproducao.out)


def test_reproduce_falha_e_nomeia_os_itens_quando_o_conteudo_original_diverge(fluxo: Fluxo) -> None:
    uniao = _original_do_congelamento(fluxo, "sia_pa.v1")
    run = fluxo.execucoes[("cal", "atendimento")]
    agregados = Path(next(s for s in run.saidas if s.schema_id == "agregados_registro.v1").caminho)
    original_uniao = adulterar_coluna(uniao, "quantidade_apresentada", 99)
    original_agregados = adulterar_coluna(agregados, "resultado", "ABSTENCAO")
    try:
        feita = reproduzir(fluxo, fluxo.configs["teste"], fluxo.mundo.raiz / "reproducao_div")
    finally:
        uniao.write_bytes(original_uniao)
        agregados.write_bytes(original_agregados)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo["resultado"] == "DIVERGENTE"
    divergentes = {item for item, situacao in feita.situacoes.items() if situacao == "DIVERGENTE"}
    assert divergentes == {"conjunto:sia_pa.v1", "saida:B_ATEND:agregados_registro.v1"}
    assert feita.itens["conjunto:sia_pa.v1"]["detalhe"] == "original_diverge"


def _arquivo_original(fluxo: Fluxo, familia: FamiliaFonte, competencia: str) -> Path:
    estado = Manifesto(fluxo.mundo.raiz / "manifestos" / "aquisicao.jsonl").ler()
    (versao,) = (
        v
        for v in estado.versoes.values()
        if v.chave.fonte is familia and str(v.chave.competencia_arquivo) == competencia
    )
    return fluxo.mundo.raiz / "dados" / "raw" / versao.caminho_conteudo


def test_reproduce_com_original_do_sia_pa_ausente_e_inconclusivo_e_nao_divergente(
    fluxo: Fluxo,
) -> None:
    arquivo = _arquivo_original(fluxo, FamiliaFonte.SIA_PA, "202301")
    guardado = arquivo.read_bytes()
    arquivo.unlink()
    try:
        feita = reproduzir(
            fluxo, fluxo.configs["teste"], fluxo.mundo.raiz / "reproducao_sem_sia_pa"
        )
    finally:
        arquivo.write_bytes(guardado)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo["resultado"] == "INCONCLUSIVO"
    assert feita.conteudo["relatorio_refeito"] is None
    assert feita.situacoes == {
        "conjunto:sia_pa.v1": "INCONCLUSIVO",
        "conjunto:sia_pa_rotulos.v1": "INCONCLUSIVO",
    }
    detalhe = "originais_indisponiveis artefatos=1 estados=ARQUIVOAUSENTE"
    assert {i["detalhe"] for i in feita.itens.values()} == {detalhe}
    assert "ingest_sem_tabela artefatos=1 estados=ARQUIVOAUSENTE" in feita.conteudo["observacoes"]


@pytest.mark.parametrize(
    "familia", [FamiliaFonte.CNES_PF, FamiliaFonte.CNES_ST, FamiliaFonte.SIGTAP]
)
def test_reproduce_com_original_auxiliar_ausente_e_inconclusivo_e_nao_divergente(
    fluxo: Fluxo, familia: FamiliaFonte
) -> None:
    arquivo = _arquivo_original(fluxo, familia, "202401")
    guardado = arquivo.read_bytes()
    arquivo.unlink()
    destino = fluxo.mundo.raiz / f"reproducao_sem_{familia.value.lower()}"
    try:
        feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    finally:
        arquivo.write_bytes(guardado)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo.get("resultado") == "INCONCLUSIVO"
    assert feita.conteudo["relatorio_refeito"] is None
    assert feita.situacoes == {f"insumos:{politica}": "INCONCLUSIVO" for politica in POLITICAS}
    detalhe = "originais_indisponiveis artefatos=1 estados=ARQUIVOAUSENTE"
    assert {i["detalhe"] for i in feita.itens.values()} == {detalhe}
    assert "ingest_sem_tabela artefatos=1 estados=ARQUIVOAUSENTE" in feita.conteudo["observacoes"]


def _entrada_alterada(arquivo: Path) -> None:
    conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
    conteudo["identidade_adicional"] = {"recorte_territorial": "0" * 64}
    arquivo.write_text(json.dumps(conteudo), encoding="utf-8")


ESTRAGOS_DA_ENTRADA = {
    "ausente": (Path.unlink, "entrada_original_ausente"),
    "ilegivel": (lambda arquivo: arquivo.write_text('{"dataset": '), "entrada_original_ilegivel"),
    "alterada": (_entrada_alterada, "entrada_original_alterada"),
}


@pytest.mark.parametrize("auxiliar", ["disponivel", "indisponivel"])
@pytest.mark.parametrize("estrago", list(ESTRAGOS_DA_ENTRADA))
def test_reproduce_com_a_entrada_original_que_nao_confere_e_inconclusivo_e_nao_divergente(
    fluxo: Fluxo, estrago: str, auxiliar: str
) -> None:
    entrada = fluxo.mundo.saidas / "split" / "insumos" / f"{POLITICA_ESTRAGADA}.json"
    cnes = _arquivo_original(fluxo, FamiliaFonte.CNES_ST, "202401")
    guardados = {arquivo: arquivo.read_bytes() for arquivo in (entrada, cnes)}
    destino = fluxo.mundo.raiz / f"reproducao_entrada_{estrago}_{auxiliar}"
    estragar, motivo = ESTRAGOS_DA_ENTRADA[estrago]
    try:
        estragar(entrada)
        if auxiliar == "indisponivel":
            cnes.unlink()
        feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    finally:
        for arquivo, conteudo in guardados.items():
            arquivo.write_bytes(conteudo)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo.get("resultado") == "INCONCLUSIVO"
    assert feita.conteudo["relatorio_refeito"] is None
    esperadas = [POLITICA_ESTRAGADA] if auxiliar == "disponivel" else POLITICAS
    assert feita.situacoes == {f"insumos:{politica}": "INCONCLUSIVO" for politica in esperadas}
    assert feita.itens[f"insumos:{POLITICA_ESTRAGADA}"]["detalhe"] == motivo
    sem_auxiliar = {i["detalhe"] for i in feita.itens.values()} - {motivo}
    assert sem_auxiliar <= {"originais_indisponiveis artefatos=1 estados=ARQUIVOAUSENTE"}
    assert not any("insumos_originais_nao_conferidos" in o for o in feita.conteudo["observacoes"])


def test_reproduce_com_saida_que_a_reconstrucao_nao_emitiu_e_divergente(
    fluxo: Fluxo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sustemporal.reporting.reproduce.validar_janela",
        sem_evidencias(validar_janela, EVIDENCIAS),
    )
    destino = fluxo.mundo.raiz / "reproducao_sem_evidencias"
    feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo.get("resultado") == "DIVERGENTE"
    divergentes = {item for item, situacao in feita.situacoes.items() if situacao == "DIVERGENTE"}
    assert divergentes == {f"saida:{metodo}:{EVIDENCIAS}" for metodo in METODOS}
    assert {feita.itens[item]["detalhe"] for item in divergentes} == {"saida_ausente_no_refeito"}


def _estragar_o_ingest(fluxo: Fluxo, como: str, fora: Path, copia: Path) -> str:
    """Estraga o ingest original de um jeito e devolve o motivo que a reprodução deve dar."""
    assert fluxo.ingest is not None
    pasta = fluxo.ingest
    posicao = pasta / "manifesto_lido.json"
    lido = json.loads(posicao.read_text(encoding="utf-8"))
    linhas = lido["linhas"]
    if como == "ausente":
        pasta.rename(fora)
        return "ingest_original_ausente execucoes=0"
    if como == "ambigua":
        shutil.copytree(pasta, copia)
        (copia / "manifesto_lido.json").write_text(json.dumps({**lido, "linhas": linhas - 1}))
        return "ingest_original_ambiguo candidatas=2 posicoes=2"
    if como == "sem_posicao":
        posicao.write_text("{", encoding="utf-8")
        return f"ingest_original_sem_posicao execucao={pasta.name}"
    if como == "cabeca_diferente":
        posicao.write_text(json.dumps({**lido, "cabeca_sha256": "0" * 64}), encoding="utf-8")
        return f"manifesto_diferente_do_lido_pelo_ingest linhas={linhas}"
    posicao.write_text(json.dumps({**lido, "linhas": linhas + 1000}), encoding="utf-8")
    return f"manifesto_menor_que_o_lido_pelo_ingest linhas={linhas + 1000} atual={linhas}"


@contextmanager
def _ingest_original_assim(fluxo: Fluxo, como: str) -> Iterator[str]:
    assert fluxo.ingest is not None
    pasta = fluxo.ingest
    guardado = (pasta / "manifesto_lido.json").read_bytes()
    fora = fluxo.mundo.raiz / "ingest_guardado"
    copia = pasta.with_name("execucao_99991231T235959999999Z_copia")
    try:
        yield _estragar_o_ingest(fluxo, como, fora, copia)
    finally:
        if fora.exists():
            fora.rename(pasta)
        shutil.rmtree(copia, ignore_errors=True)
        (pasta / "manifesto_lido.json").write_bytes(guardado)


@pytest.mark.parametrize(
    "como", ["ausente", "ambigua", "sem_posicao", "cabeca_diferente", "alem_do_fim"]
)
def test_reproduce_sem_saber_o_que_o_ingest_leu_do_manifesto_e_inconclusivo_e_nao_divergente(
    fluxo: Fluxo, como: str
) -> None:
    destino = fluxo.mundo.raiz / f"reproducao_ingest_{como}"
    with _ingest_original_assim(fluxo, como) as motivo:
        feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo.get("resultado") == "INCONCLUSIVO"
    assert feita.conteudo["relatorio_refeito"] is None
    assert feita.situacoes == {"manifesto:aquisicao": "INCONCLUSIVO"}
    assert feita.itens["manifesto:aquisicao"]["detalhe"] == motivo
    assert not (destino / "ingest").exists()


def test_reproduce_sem_o_ingest_original_relata_tambem_a_entrada_que_nao_confere(
    fluxo: Fluxo,
) -> None:
    entrada = fluxo.mundo.saidas / "split" / "insumos" / f"{POLITICA_ESTRAGADA}.json"
    guardada = entrada.read_bytes()
    entrada.unlink()
    destino = fluxo.mundo.raiz / "reproducao_sem_ingest_e_sem_entrada"
    try:
        with _ingest_original_assim(fluxo, "ausente"):
            feita = reproduzir(fluxo, fluxo.configs["teste"], destino)
    finally:
        entrada.write_bytes(guardada)
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.situacoes == {
        "manifesto:aquisicao": "INCONCLUSIVO",
        f"insumos:{POLITICA_ESTRAGADA}": "INCONCLUSIVO",
    }


def test_reproduce_com_particao_vazia_e_inconclusivo_e_nao_erro_de_configuracao(
    fluxo: Fluxo, monkeypatch: pytest.MonkeyPatch
) -> None:
    particoes = _manifesto(fluxo).split.particoes or {}
    refeito = sem_os_artefatos(derivar_protocolo, particoes[Particao.TESTE].artifact_ids)
    monkeypatch.setattr("sustemporal.reporting.reproduce.derivar_protocolo", refeito)
    feita = reproduzir(fluxo, fluxo.configs["teste"], fluxo.mundo.raiz / "reproducao_vazia")
    assert feita.codigo == ExitCode.FALHA_OPERACIONAL
    assert feita.conteudo["relatorio_refeito"] is None
    assert feita.itens["particao:TESTE"]["situacao"] == "INCONCLUSIVO"
    assert feita.itens["particao:TESTE"]["detalhe"] == "particao_vazia"
    assert {"conjunto:sia_pa.v1", "split:split_id"} <= set(feita.itens)
    assert "particao:CALIBRACAO" not in feita.itens
    assert "particao_sem_artefatos particao=TESTE" in feita.conteudo["observacoes"]


def test_reproduce_recusa_destino_ja_usado(fluxo: Fluxo, reproducao: Reproducao) -> None:
    assert reproducao.codigo == ExitCode.OK
    assert reproducao.out.is_dir()
    assert reproduzir(fluxo, fluxo.configs["teste"]).codigo == ExitCode.CONFIG_INVALIDA


def test_reproduce_recusa_destino_que_e_um_arquivo(fluxo: Fluxo) -> None:
    arquivo = fluxo.mundo.raiz / "saida_que_e_arquivo"
    arquivo.write_text("conteúdo do usuário", encoding="utf-8")
    assert reproduzir(fluxo, fluxo.configs["teste"], arquivo).codigo == ExitCode.CONFIG_INVALIDA
    assert arquivo.read_text(encoding="utf-8") == "conteúdo do usuário"


def test_reproduce_exige_offline(fluxo: Fluxo) -> None:
    destino = fluxo.mundo.raiz / "reproducao_sem_offline"
    argumentos = ["--config", str(fluxo.configs["teste"]), "--freeze", _freeze(fluxo)]
    assert comando("reproduce", *argumentos, "--saida", str(destino)) == ExitCode.CONFIG_INVALIDA
    assert not destino.exists()


def test_reproduce_recusa_config_que_permite_rede_antes_de_tocar_em_arquivo(fluxo: Fluxo) -> None:
    config = escrever_config(fluxo.mundo, "com_rede", ("202401",), rede=True)
    destino = fluxo.mundo.raiz / "reproducao_com_rede"
    assert reproduzir(fluxo, config, destino).codigo == ExitCode.REDE_PROIBIDA
    assert not destino.exists()


def test_reproduce_de_congelamento_inexistente_e_recusado_sem_criar_o_destino(fluxo: Fluxo) -> None:
    inexistente = "frz_" + "0" * 64
    argumentos = ["--config", str(fluxo.configs["teste"]), "--freeze", inexistente, "--offline"]
    assert comando("reproduce", *argumentos) == ExitCode.CONFIG_INVALIDA
    assert not (fluxo.mundo.saidas / "reproducao" / inexistente).exists()


def test_reproduce_nao_reproduz_congelamento_confirmatorio(fluxo: Fluxo) -> None:
    texto = fluxo.configs["teste"].read_text(encoding="utf-8")
    texto = texto.replace("origem_dados: SINTETICO", "origem_dados: REAL")
    confirmatoria = fluxo.mundo.raiz / "config_confirmatoria_real.yaml"
    confirmatoria.write_text(f"{texto}modo: CONFIRMATORIO\nfreeze_id: {_freeze(fluxo)}\n")
    destino = fluxo.mundo.raiz / "reproducao_confirmatoria"
    assert reproduzir(fluxo, confirmatoria, destino).codigo == ExitCode.CONFIG_INVALIDA
    assert not destino.exists()


def test_reproduce_roda_sob_a_guarda_de_rede(fluxo: Fluxo, monkeypatch: pytest.MonkeyPatch) -> None:
    def tenta_conectar(*_args: object, **_kwargs: object) -> int:
        socket.create_connection(("127.0.0.1", 9), timeout=1)
        return 0

    monkeypatch.setattr("sustemporal.ingest.cli.executar_ingest", tenta_conectar)
    destino = fluxo.mundo.raiz / "reproducao_guarda"
    assert reproduzir(fluxo, fluxo.configs["teste"], destino).codigo == ExitCode.REDE_PROIBIDA
