"""Observação de republicações (T13): tentativas, comparação por multiconjunto; SINTETICO."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.fixtures.aquisicao_dados import Relogio, servidor_ftp
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa, leiaute_pa, registro_pa

from sustemporal.acquisition.cli import executar_watch
from sustemporal.acquisition.comparacao import (
    ComparacaoVersoes,
    ResultadoComparacao,
    comparar_versoes,
)
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.transport import TransporteFTP
from sustemporal.acquisition.watch import observe_updates, resumir_vigilancia
from sustemporal.config import load_config
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    FormatoArquivo,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte, OrigemDados
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.errors import ExitCode

if TYPE_CHECKING:
    import pytest

CATALOGO = Path("catalog/sources.yaml")
_R1 = registro_pa(PA_PROC_ID="0301010072")
_R2 = registro_pa(PA_PROC_ID="0301010080")
_R3 = registro_pa(PA_PROC_ID="0301010099")


def _requisicao(localizador: str) -> SourceRequest:
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf="SP",
        competencia_arquivo="201801",
        parte="a",
        canal=CanalPublicacao.ATUAL,
        nome_original="PASP1801a.dbc",
    )
    return SourceRequest(
        chave=chave,
        localizador=localizador,
        formato_esperado=FormatoArquivo.DBC,
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.VIGILANCIA,
    )


def test_conteudo_inalterado_registra_cada_tentativa(tmp_path: Path) -> None:
    dados = tmp_path / "ftp" / "Dados"
    dados.mkdir(parents=True)
    (dados / "PASP1801a.dbc").write_bytes(dbc_pa([_R1]))
    store = tmp_path / "store"
    relogio = Relogio()
    with servidor_ftp(tmp_path / "ftp") as porta:
        pedido = [_requisicao(f"ftp://127.0.0.1:{porta}/Dados/PASP1801a.dbc")]
        transportes = {"ftp": TransporteFTP(timeout=5)}
        primeira = observe_updates(
            pedido, store, rede_permitida=True, relogio=relogio, transportes=transportes
        )
        segunda = observe_updates(
            pedido, store, rede_permitida=True, relogio=relogio, transportes=transportes
        )
    observadas = [*primeira, *segunda]
    assert [o.resultado for o in observadas] == [ResultadoTentativa.OBTIDO] * 2
    assert len({o.artifact_id for o in observadas}) == 1
    assert observadas[0].observado_em < observadas[1].observado_em
    estado = Manifesto(store / "manifesto.jsonl").ler()
    assert len(estado.observacoes) == 2
    assert len(estado.versoes) == 1


def _comparar(
    tmp_path: Path,
    antes: list[dict[str, str]],
    depois: list[dict[str, str]],
    *,
    deletados_depois: tuple[int, ...] = (),
    deletados_antes: tuple[int, ...] = (),
) -> ComparacaoVersoes:
    raiz = tmp_path / "dados"
    anterior = artefato_pa(raiz, dbc_pa(antes, deletados=deletados_antes))
    nova = artefato_pa(raiz, dbc_pa(depois, deletados=deletados_depois))
    return comparar_versoes(
        anterior,
        nova,
        layout=leiaute_pa(),
        runtime=RuntimeConfig(raiz_dados=str(raiz)),
        destino=tmp_path / "comparacao",
        origem_dados=OrigemDados.SINTETICO,
    )


def test_bytes_diferentes_com_as_mesmas_linhas_em_outra_ordem_sao_inalterados(
    tmp_path: Path,
) -> None:
    comparacao = _comparar(tmp_path, [_R1, _R2, _R2], [_R2, _R1, _R2])
    assert comparacao.anterior != comparacao.nova
    assert comparacao.resultado is ResultadoComparacao.INALTERADA


def test_linhas_que_entram_sem_sair_nenhuma_sao_revisao_real(tmp_path: Path) -> None:
    comparacao = _comparar(tmp_path, [_R1, _R2], [_R1, _R2, _R2])
    assert comparacao.resultado is ResultadoComparacao.REVISAO_REAL
    assert (comparacao.linhas_removidas, comparacao.linhas_adicionadas) == (0, 1)


def test_deletadas_contadas_por_versao_sem_inferir_transicao(tmp_path: Path) -> None:
    comparacao = _comparar(tmp_path, [_R1, _R2], [_R1, _R2], deletados_depois=(1,))
    assert comparacao.resultado is ResultadoComparacao.REVISAO_REAL
    assert (comparacao.linhas_removidas, comparacao.linhas_adicionadas) == (1, 0)
    assert (comparacao.deletadas_anterior, comparacao.deletadas_nova) == (0, 1)
    assert "transicao_de_delecao_ambigua" in comparacao.motivo


def test_correspondencia_ambigua_nao_pareia_linhas(tmp_path: Path) -> None:
    comparacao = _comparar(tmp_path, [_R1, _R1, _R2], [_R1, _R3, _R2])
    assert comparacao.resultado is ResultadoComparacao.CORRESPONDENCIA_AMBIGUA
    assert (comparacao.linhas_removidas, comparacao.linhas_adicionadas) == (1, 1)
    assert "sem_pareamento" in comparacao.motivo


def test_ausencia_de_revisao_observada_nao_afirma_que_nunca_houve(tmp_path: Path) -> None:
    store = tmp_path / "store"
    origem = tmp_path / "PASP1801a.dbc"
    origem.write_bytes(dbc_pa([_R1]))
    relogio = Relogio()
    pedido = [_requisicao(origem.as_uri())]
    observadas = [o for _ in range(3) for o in observe_updates(pedido, store, relogio=relogio)]
    artefato = str(observadas[0].artifact_id)
    inalterada = ComparacaoVersoes(
        artefato, artefato, ResultadoComparacao.INALTERADA, 0, 0, "mesma_versao"
    )
    resumo = resumir_vigilancia(observadas, [inalterada, inalterada])
    assert resumo.startswith("sem_revisao_observada")
    assert "nunca" not in resumo
    assert f"de={observadas[0].observado_em.isoformat()}" in resumo
    assert f"ate={observadas[-1].observado_em.isoformat()}" in resumo
    assert "alcance=somente_observacoes_da_pesquisa" in resumo


def _ambiente_watch(
    tmp_path: Path,
    *,
    janela: int = 2,
    competencias: tuple[str, ...] = ("2510", "2511", "2512", "2601", "2607"),
    cnes: tuple[str, ...] = (),
) -> Path:
    dados = tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"
    dados.mkdir(parents=True)
    for aamm in competencias:
        registro = registro_pa(PA_MVM=f"20{aamm}", PA_CMP=f"20{aamm}")
        (dados / f"PASP{aamm}a.dbc").write_bytes(dbc_pa([registro]))
    pf = tmp_path / "origem" / "CNES" / "200508_" / "Dados" / "PF"
    pf.mkdir(parents=True)
    for aamm in cnes:
        (pf / f"PFSP{aamm}.dbc").write_bytes(dbc_pa([_R1]))
    texto = CATALOGO.read_text(encoding="utf-8").replace(
        "ftp://ftp.datasus.gov.br/dissemin/publicos", (tmp_path / "origem").as_uri()
    )
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    familias = "[SIA_PA, CNES_PF]" if cnes or janela > 2 else "[SIA_PA]"
    config = tmp_path / "watch.yaml"
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        "runtime:",
        f"  raiz_dados: {tmp_path / 'data'}",
        f"  raiz_manifestos: {tmp_path / 'manifests'}",
        "vigilancia:",
        f"  janela_competencias: {janela}",
        f"  familias_fontes: {familias}",
        "  uf: SP",
        "catalogos:",
        f"  fontes: {catalogo}",
    ]
    config.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return config


def _executar(tmp_path: Path) -> tuple[int, list[dict[str, object]]]:
    """Roda o watch e devolve o código e as linhas do relatório só desta execução."""
    config = load_config(tmp_path / "watch.yaml")
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    codigo = executar_watch(argparse.Namespace(), config, relogio=relogio)
    relatorio = tmp_path / "manifests" / "vigilancia.jsonl"
    todas = [json.loads(x) for x in relatorio.read_text(encoding="utf-8").splitlines()]
    resumos = [i for i, linha in enumerate(todas) if "resumo" in linha]
    inicio = resumos[-2] + 1 if len(resumos) > 1 else 0
    return codigo, todas[inicio:]


def _por_chave(linhas: list[dict[str, object]]) -> dict[tuple[object, object], tuple[str, str]]:
    return {
        (d["competencia"], d["parte"]): (str(d["resultado"]), str(d["motivo"]))
        for d in linhas
        if "resultado" in d
    }


def _dados(tmp_path: Path) -> Path:
    return tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"


def _alterar_dezembro(tmp_path: Path) -> None:
    registro = registro_pa(PA_MVM="202512", PA_CMP="202512")
    (_dados(tmp_path) / "PASP2512a.dbc").write_bytes(dbc_pa([registro, registro]))


def test_primeira_execucao_registra_cada_chave_como_arquivo_novo(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.OK
    assert _por_chave(linhas) == {
        ("202511", "a"): ("ARQUIVO_NOVO", "sem_versao_anterior"),
        ("202512", "a"): ("ARQUIVO_NOVO", "sem_versao_anterior"),
    }
    assert not str(linhas[-1]["resumo"]).startswith("sem_revisao_observada")


def test_watch_no_recorte_registra_inalterada_e_revisao_real(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    _alterar_dezembro(tmp_path)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.OK
    estado = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler()
    arquivos = [o for o in estado.observacoes if o.chave.tipo_conteudo is None]
    assert sorted({o.chave.competencia_arquivo.valor for o in arquivos}) == ["202511", "202512"]
    assert len(arquivos) == 4
    resultados = {chave: r for chave, (r, _m) in _por_chave(linhas).items()}
    assert resultados == {("202511", "a"): "INALTERADA", ("202512", "a"): "REVISAO_REAL"}
    assert str(linhas[-1]["resumo"]).startswith("revisao_observada")


def test_sem_mudanca_e_janela_completa_diz_sem_revisao_observada(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.OK
    assert {r for r, _m in _por_chave(linhas).values()} == {"INALTERADA"}
    assert str(linhas[-1]["resumo"]).startswith("sem_revisao_observada")


def test_parte_nova_depois_do_inicio_e_arquivo_novo(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    registro = registro_pa(PA_MVM="202512", PA_CMP="202512")
    (_dados(tmp_path) / "PASP2512b.dbc").write_bytes(dbc_pa([registro]))
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.OK
    assert _por_chave(linhas).get(("202512", "b"), ("", ""))[0] == "ARQUIVO_NOVO"
    assert not str(linhas[-1]["resumo"]).startswith("sem_revisao_observada")


def test_familia_sem_comparacao_com_bytes_novos(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path, cnes=("2511", "2512"))
    _executar(tmp_path)
    pf = tmp_path / "origem" / "CNES" / "200508_" / "Dados" / "PF" / "PFSP2512.dbc"
    pf.write_bytes(dbc_pa([_R2]))
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.OK
    cnes = {(d["competencia"], d["resultado"]) for d in linhas if d.get("fonte") == "CNES_PF"}
    assert cnes == {("202511", "INALTERADA"), ("202512", "BYTES_ALTERADOS_SEM_COMPARACAO")}
    assert str(linhas[-1]["resumo"]).startswith("revisao_observada")


def test_arquivo_que_some_da_listagem_e_arquivo_sumiu(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    (_dados(tmp_path) / "PASP2512a.dbc").unlink()
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    assert _por_chave(linhas)[("202512", "a")] == ("ARQUIVO_SUMIU", "sumiu_da_listagem")


def test_comparacao_que_falha_e_inconclusiva(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    estado = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler()
    for versao in estado.versoes.values():
        competencia = versao.chave.competencia_arquivo
        if competencia is not None and competencia.valor == "202512":
            (tmp_path / "data" / "raw" / versao.caminho_conteudo).unlink()
    _alterar_dezembro(tmp_path)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    resultado, motivo = _por_chave(linhas)[("202512", "a")]
    assert (resultado, motivo.split()[0]) == ("INCONCLUSIVO", "comparacao_inconclusiva")
    resumo = str(linhas[-1]["resumo"])
    assert resumo.startswith("vigilancia_inconclusiva")
    assert "inconclusivo=1" in resumo


def test_observacao_falha_de_arquivo_ja_acompanhado_e_inconclusiva(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _executar(tmp_path)
    (_dados(tmp_path) / "PASP2512a.dbc").unlink()
    (_dados(tmp_path) / "PASP2512a.dbc").mkdir()
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    resultado, motivo = _por_chave(linhas)[("202512", "a")]
    assert resultado == "INCONCLUSIVO"
    assert motivo.startswith("observacao_sem_conteudo")


def test_janela_incompleta_ou_listagem_vazia_e_falha(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path, janela=3, competencias=("2511", "2512"))
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    janelas = {d["fonte"]: (d["pedido"], d["obtido"]) for d in linhas if d.get("janela_incompleta")}
    assert janelas == {"SIA_PA": (3, 2), "CNES_PF": (3, 0)}
    resumo = str(linhas[-1]["resumo"])
    assert resumo.startswith("vigilancia_inconclusiva")
    assert "janelas_incompletas=2" in resumo


def test_travessia_da_janela_nao_converte_competencia_em_numero() -> None:
    import inspect

    from sustemporal.acquisition import watch

    assert "int(" not in inspect.getsource(watch.competencias_da_janela)


def test_config_de_vigilancia_e_valida() -> None:
    config = load_config(Path("config/watch.yaml"))
    assert config.vigilancia is not None
    assert config.vigilancia.janela_competencias == 6
    assert (config.vigilancia.cadencia_dias, config.vigilancia.duracao_meses) == (7, 12)
    assert config.origem_dados is OrigemDados.REAL


def test_listagem_sem_arquivo_da_fonte_nao_vira_arquivo_sumiu(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path, cnes=("2511", "2512"))
    _executar(tmp_path)
    pf = tmp_path / "origem" / "CNES" / "200508_" / "Dados" / "PF"
    for arquivo in pf.iterdir():
        arquivo.unlink()
    (pf / "LEIAME.txt").write_text("sem arquivos de competencia", encoding="utf-8")
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    cnes = [d for d in linhas if d.get("fonte") == "CNES_PF"]
    assert [d.get("obtido") for d in cnes if d.get("janela_incompleta")] == [0]
    assert not [d for d in cnes if d.get("resultado") == "ARQUIVO_SUMIU"]


def test_listagem_que_falha_vira_linha_de_familia_inconclusiva(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path, cnes=("2511", "2512"))
    _executar(tmp_path)
    pf = tmp_path / "origem" / "CNES" / "200508_" / "Dados" / "PF"
    for arquivo in pf.iterdir():
        arquivo.unlink()
    pf.rmdir()
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    (familia,) = [d for d in linhas if d.get("fonte") == "CNES_PF"]
    assert familia.get("resultado") == "INCONCLUSIVO"
    assert str(familia["motivo"]).startswith("listagem_nao_obtida")
    assert "inconclusivo=1" in str(linhas[-1]["resumo"])


def test_primeira_observacao_que_falha_e_inconclusiva(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    (_dados(tmp_path) / "PASP2512a.dbc").unlink()
    (_dados(tmp_path) / "PASP2512a.dbc").mkdir()
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    assert _por_chave(linhas)[("202512", "a")][0] == "INCONCLUSIVO"
    assert str(linhas[-1]["resumo"]).startswith("vigilancia_inconclusiva")


_NAO_CONCLUSIVOS = {"INCONCLUSIVO", "ARQUIVO_SUMIU"}
_ACOES = ("manter", "alterar", "apagar", "diretorio")


def _aplicar(dados: Path, aamm: str, acao: str) -> None:
    arquivo = dados / f"PASP{aamm}a.dbc"
    if acao == "manter" or not arquivo.exists():
        return
    arquivo.unlink()
    registro = registro_pa(PA_MVM=f"20{aamm}", PA_CMP=f"20{aamm}")
    if acao == "alterar":
        arquivo.write_bytes(dbc_pa([registro, registro]))
    elif acao == "diretorio":
        arquivo.mkdir()


def _conferir_execucao(raiz: Path) -> None:
    codigo, linhas = _executar(raiz)
    nao_conclusivas = [
        d for d in linhas if d.get("janela_incompleta") or d.get("resultado") in _NAO_CONCLUSIVOS
    ]
    assert (codigo == ExitCode.FALHA_OPERACIONAL) == bool(nao_conclusivas)
    resumo = str(linhas[-1]["resumo"])
    assert resumo.startswith("vigilancia_inconclusiva") == bool(nao_conclusivas)


@settings(max_examples=6, deadline=None)
@given(
    presentes=st.sets(st.sampled_from(["2510", "2511", "2512"]), min_size=1),
    acoes=st.tuples(*[st.sampled_from(_ACOES)] * 3),
    sem_cnes=st.booleans(),
)
def test_saida_5_se_e_somente_se_ha_linha_nao_conclusiva(
    presentes: set[str], acoes: tuple[str, str, str], sem_cnes: bool
) -> None:
    with tempfile.TemporaryDirectory() as pasta:
        raiz = Path(pasta)
        _ambiente_watch(raiz, competencias=tuple(sorted(presentes)), cnes=("2512",))
        _conferir_execucao(raiz)
        for aamm, acao in zip(("2510", "2511", "2512"), acoes, strict=True):
            _aplicar(_dados(raiz), aamm, acao)
        if sem_cnes:
            pf = raiz / "origem" / "CNES" / "200508_" / "Dados" / "PF"
            for arquivo in pf.iterdir():
                arquivo.unlink()
            pf.rmdir()
        _conferir_execucao(raiz)


def _requisicao_sigtap(origem: Path, geracao: str) -> SourceRequest:
    nome = f"TabelaUnificada_202512_v{geracao}.zip"
    caminho = origem / nome
    caminho.write_bytes(dbc_pa([registro_pa(PA_PROC_ID=f"03010{geracao[-5:]}")]))
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIGTAP,
        competencia_arquivo="202512",
        canal=CanalPublicacao.ATUAL,
        nome_original=nome,
        versao_publicacao=geracao,
    )
    return SourceRequest(
        chave=chave,
        localizador=caminho.as_uri(),
        formato_esperado=FormatoArquivo.DBC,
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.VIGILANCIA,
    )


def test_cada_geracao_do_sigtap_e_uma_chave_propria(tmp_path: Path) -> None:
    from sustemporal.acquisition.watch import (
        chave_de_comparacao,
        classificar_chave,
        versoes_anteriores,
    )

    store, origem = tmp_path / "store", tmp_path / "origem"
    origem.mkdir()
    relogio = Relogio()
    pedidos = [_requisicao_sigtap(origem, g) for g in ("2512011200", "2512151200")]
    observe_updates(pedidos, store, relogio=relogio)
    anteriores = versoes_anteriores(store / "manifesto.jsonl")
    pedidos.append(_requisicao_sigtap(origem, "2512201200"))
    observadas = observe_updates(pedidos, store, relogio=relogio)
    versoes = Manifesto(store / "manifesto.jsonl").ler().versoes

    def proibido(*_a: object) -> ComparacaoVersoes:
        raise AssertionError("sigtap_nao_e_comparado_por_linhas")

    resultados = [
        classificar_chave(anteriores.get(chave_de_comparacao(o.chave)), o, versoes, proibido)
        for o in observadas
    ]
    assert [r.resultado for r in resultados] == [
        ResultadoComparacao.INALTERADA,
        ResultadoComparacao.INALTERADA,
        ResultadoComparacao.ARQUIVO_NOVO,
    ]


def test_leiaute_que_nao_carrega_e_comparacao_inconclusiva(tmp_path: Path) -> None:
    config = _ambiente_watch(tmp_path)
    with config.open("a", encoding="utf-8") as saida:
        saida.write(f"  leiaute_sia_pa: {tmp_path / 'nao_existe.yaml'}\n")
    _executar(tmp_path)
    _alterar_dezembro(tmp_path)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    resultado, motivo = _por_chave(linhas)[("202512", "a")]
    assert (resultado, motivo.split()[0]) == ("INCONCLUSIVO", "comparacao_inconclusiva")


def test_listagem_guardada_ilegivel_vira_linha_de_familia_inconclusiva(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sustemporal.acquisition import cli as cli_aquisicao
    from sustemporal.errors import FalhaOperacionalErro

    def divergente(*_a: object) -> list[str]:
        raise FalhaOperacionalErro("listagem_divergente caminho=sintetico")

    _ambiente_watch(tmp_path)
    monkeypatch.setattr(cli_aquisicao, "nomes_listados", divergente)
    codigo, linhas = _executar(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    (familia,) = [d for d in linhas if d.get("fonte") == "SIA_PA"]
    assert familia.get("resultado") == "INCONCLUSIVO"
    assert str(familia["motivo"]).startswith("listagem_ilegivel")


def test_resumo_conta_listagens_e_arquivos(tmp_path: Path) -> None:
    _ambiente_watch(tmp_path)
    _codigo, linhas = _executar(tmp_path)
    estado = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler()
    resumo = str(linhas[-1]["resumo"])
    assert f"observacoes={len(estado.observacoes)}" in resumo
    assert f"de={estado.observacoes[0].observado_em.isoformat()}" in resumo


def test_mudanca_so_em_linhas_deletadas_e_revisao_real(tmp_path: Path) -> None:
    conteudo = _comparar(
        tmp_path / "conteudo", [_R1, _R2], [_R1, _R3], deletados_antes=(1,), deletados_depois=(1,)
    )
    contagem = _comparar(tmp_path / "contagem", [_R1, _R2], [_R1], deletados_antes=(1,))
    for comparacao in (conteudo, contagem):
        assert comparacao.resultado is ResultadoComparacao.REVISAO_REAL
        assert (comparacao.linhas_removidas, comparacao.linhas_adicionadas) == (0, 0)
        assert "so_em_deletadas" in comparacao.motivo
    resumo = resumir_vigilancia([], [conteudo])
    assert resumo.startswith("revisao_observada")
