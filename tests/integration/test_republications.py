"""Observação de republicações (T13): tentativas, comparação por multiconjunto; SINTETICO."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

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
) -> ComparacaoVersoes:
    raiz = tmp_path / "dados"
    anterior = artefato_pa(raiz, dbc_pa(antes))
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


def test_registro_que_passa_a_deletado_e_saida_e_conta_a_parte(tmp_path: Path) -> None:
    comparacao = _comparar(tmp_path, [_R1, _R2], [_R1, _R2], deletados_depois=(1,))
    assert comparacao.resultado is ResultadoComparacao.REVISAO_REAL
    assert (comparacao.linhas_removidas, comparacao.linhas_adicionadas) == (1, 0)
    assert comparacao.mudancas_de_delecao == 1


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
    resumo = resumir_vigilancia(observadas, [])
    assert resumo.startswith("sem_revisao_observada")
    assert "nunca" not in resumo
    assert f"de={observadas[0].observado_em.isoformat()}" in resumo
    assert f"ate={observadas[-1].observado_em.isoformat()}" in resumo
    assert "alcance=somente_observacoes_da_pesquisa" in resumo


def _ambiente_watch(tmp_path: Path) -> Path:
    dados = tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"
    dados.mkdir(parents=True)
    for aamm in ("2510", "2511", "2512", "2601", "2607"):
        registro = registro_pa(PA_MVM=f"20{aamm}", PA_CMP=f"20{aamm}")
        (dados / f"PASP{aamm}a.dbc").write_bytes(dbc_pa([registro]))
    texto = CATALOGO.read_text(encoding="utf-8").replace(
        "ftp://ftp.datasus.gov.br/dissemin/publicos", (tmp_path / "origem").as_uri()
    )
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    config = tmp_path / "watch.yaml"
    linhas = [
        'versao: "1"',
        "origem_dados: SINTETICO",
        "runtime:",
        f"  raiz_dados: {tmp_path / 'data'}",
        f"  raiz_manifestos: {tmp_path / 'manifests'}",
        "vigilancia:",
        "  janela_competencias: 2",
        "  familias_fontes: [SIA_PA]",
        "  uf: SP",
        "catalogos:",
        f"  fontes: {catalogo}",
    ]
    config.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return config


def _relatorio(tmp_path: Path) -> list[dict[str, object]]:
    relatorio = tmp_path / "manifests" / "vigilancia.jsonl"
    return [json.loads(linha) for linha in relatorio.read_text(encoding="utf-8").splitlines()]


def _dezembro(tmp_path: Path) -> Path:
    return tmp_path / "origem" / "SIASUS" / "200801_" / "Dados" / "PASP2512a.dbc"


def _alterar_dezembro(tmp_path: Path) -> None:
    alterado = _dezembro(tmp_path)
    registro = registro_pa(PA_MVM="202512", PA_CMP="202512")
    alterado.write_bytes(dbc_pa([registro, registro]))


def test_watch_observa_a_janela_do_recorte_e_registra_revisao(tmp_path: Path) -> None:
    config = load_config(_ambiente_watch(tmp_path))
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    args = argparse.Namespace()
    assert executar_watch(args, config, relogio=relogio) == ExitCode.OK
    _alterar_dezembro(tmp_path)
    assert executar_watch(args, config, relogio=relogio) == ExitCode.OK
    estado = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler()
    arquivos = [o for o in estado.observacoes if o.chave.tipo_conteudo is None]
    assert sorted({o.chave.competencia_arquivo.valor for o in arquivos}) == ["202511", "202512"]
    assert len(arquivos) == 4
    resultados = {
        (d["competencia"], d["resultado"]) for d in _relatorio(tmp_path) if "resultado" in d
    }
    assert resultados == {("202511", "INALTERADA"), ("202512", "REVISAO_REAL")}


def test_comparacao_que_falha_fica_inconclusiva_no_relatorio_e_na_saida(tmp_path: Path) -> None:
    config = load_config(_ambiente_watch(tmp_path))
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    args = argparse.Namespace()
    assert executar_watch(args, config, relogio=relogio) == ExitCode.OK
    estado = Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler()
    for versao in estado.versoes.values():
        competencia = versao.chave.competencia_arquivo
        if competencia is not None and competencia.valor == "202512":
            (tmp_path / "data" / "raw" / versao.caminho_conteudo).unlink()
    _alterar_dezembro(tmp_path)
    assert executar_watch(args, config, relogio=relogio) == ExitCode.FALHA_OPERACIONAL
    linhas = _relatorio(tmp_path)
    resultados = {(d["competencia"], d["resultado"]) for d in linhas if "resultado" in d}
    assert ("202512", "INCONCLUSIVO") in resultados
    resumo = str(linhas[-1]["resumo"])
    assert not resumo.startswith("sem_revisao_observada")
    assert "inconclusivas=1" in resumo


def _segunda_execucao(tmp_path: Path) -> tuple[int, list[dict[str, object]]]:
    config = load_config(tmp_path / "watch.yaml")
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    return executar_watch(argparse.Namespace(), config, relogio=relogio), _relatorio(tmp_path)


def _inconclusivas(linhas: list[dict[str, object]]) -> dict[object, str]:
    return {
        d["competencia"]: str(d["motivo"]) for d in linhas if d.get("resultado") == "INCONCLUSIVO"
    }


def test_observacao_falha_de_arquivo_ja_acompanhado_fica_inconclusiva(tmp_path: Path) -> None:
    config = load_config(_ambiente_watch(tmp_path))
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    assert executar_watch(argparse.Namespace(), config, relogio=relogio) == ExitCode.OK
    _dezembro(tmp_path).unlink()
    _dezembro(tmp_path).mkdir()
    codigo, linhas = _segunda_execucao(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    assert _inconclusivas(linhas)["202512"].startswith("observacao_sem_conteudo")
    assert "inconclusivas=0" not in str(linhas[-1]["resumo"])


def test_arquivo_que_some_da_listagem_fica_inconclusivo(tmp_path: Path) -> None:
    config = load_config(_ambiente_watch(tmp_path))
    relogio = Relogio(atual=datetime(2026, 9, 15, tzinfo=UTC))
    assert executar_watch(argparse.Namespace(), config, relogio=relogio) == ExitCode.OK
    _dezembro(tmp_path).unlink()
    codigo, linhas = _segunda_execucao(tmp_path)
    assert codigo == ExitCode.FALHA_OPERACIONAL
    assert _inconclusivas(linhas)["202512"] == "sumiu_da_listagem"


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
