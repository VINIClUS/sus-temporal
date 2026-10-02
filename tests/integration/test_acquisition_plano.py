"""Catálogo de fontes, plano em duas passadas e comando `acquire` (T02); dados SINTETICO."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.aquisicao_dados import dbc_sintetico, zip_sintetico

from sustemporal import cli
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.sources import (
    carregar_catalogo,
    competencias_auxiliares,
    requisicao_listagem,
    requisicoes_da_listagem,
    requisicoes_documentos,
)
from sustemporal.contracts.artifacts import (
    FormatoArquivo,
    MotivoRequisicao,
    ResultadoTentativa,
    TipoConteudo,
)
from sustemporal.contracts.base import Confirmacao, FamiliaFonte, Proveniencia
from sustemporal.contracts.temporal import (
    CompetenciaArquivo,
    CompetenciaAtendimento,
    CompetenciaProcessamento,
)
from sustemporal.errors import ExitCode

CATALOGO = Path("catalog/sources.yaml")
_PA = ["PASP1801a.dbc", "PASP1801B.DBC", "PASP1802a.dbc", "PAPE1801.dbc", "PASP1801.txt"]


@pytest.fixture(scope="module")
def catalogo():
    return carregar_catalogo(CATALOGO)


def test_catalogo_do_piloto_marca_caminhos_como_nao_confirmados(catalogo) -> None:
    familias = {f.fonte for f in catalogo.fontes}
    assert familias == {
        FamiliaFonte.SIA_PA,
        FamiliaFonte.CNES_ST,
        FamiliaFonte.CNES_PF,
        FamiliaFonte.CNES_SR,
        FamiliaFonte.CNES_HB,
        FamiliaFonte.SIGTAP,
    }
    assert all(f.confirmacao is Confirmacao.A_CONFIRMAR for f in catalogo.fontes)
    assert all(f.proveniencia is Proveniencia.SECUNDARIA for f in catalogo.fontes)
    assert catalogo.fonte(FamiliaFonte.SIA_PA).multipartes


def test_catalogo_traz_documentos_w1_a_w9_e_lista_do_drs_xi(catalogo) -> None:
    ids = {d.doc_id for d in catalogo.documentos}
    assert {f"W{n}" for n in range(1, 10)} <= ids
    drs = [d for d in catalogo.documentos if d.fonte is FamiliaFonte.TERRITORIO_DRS]
    assert drs
    assert all(d.proveniencia is not Proveniencia.OFICIAL_DOCUMENTO for d in catalogo.documentos)
    requisicoes = requisicoes_documentos(catalogo)
    assert len(requisicoes) == len(catalogo.documentos)
    assert {r.motivo for r in requisicoes} == {MotivoRequisicao.DOCUMENTO}


def test_listagem_e_requisicao_de_texto_com_tipo_proprio(catalogo) -> None:
    requisicao = requisicao_listagem(catalogo, FamiliaFonte.SIA_PA)
    assert requisicao.chave.tipo_conteudo is TipoConteudo.LISTAGEM_DIRETORIO
    assert requisicao.formato_esperado is FormatoArquivo.TXT
    assert requisicao.chave.competencia_arquivo is None
    assert requisicao.localizador == catalogo.fonte(FamiliaFonte.SIA_PA).diretorio


def test_todas_as_partes_listadas_da_competencia_sao_requisitadas(catalogo) -> None:
    competencia = CompetenciaArquivo("201801")
    requisicoes = requisicoes_da_listagem(catalogo, FamiliaFonte.SIA_PA, "SP", [competencia], _PA)
    assert sorted(r.chave.parte or "" for r in requisicoes) == ["a", "b"]
    assert {r.chave.nome_original for r in requisicoes} == {"PASP1801a.dbc", "PASP1801B.DBC"}
    assert all(r.chave.competencia_arquivo == competencia for r in requisicoes)
    assert all(r.localizador.endswith(r.chave.nome_original) for r in requisicoes)


def test_competencia_ausente_na_listagem_nunca_usa_o_mes_vizinho(catalogo) -> None:
    requisicoes = requisicoes_da_listagem(
        catalogo, FamiliaFonte.SIA_PA, "SP", [CompetenciaArquivo("201712")], _PA
    )
    assert requisicoes == []


def test_sigtap_requisita_cada_geracao_listada_sem_uf(catalogo) -> None:
    nomes = [
        "TabelaUnificada_201801_v1801101010.zip",
        "TabelaUnificada_201801_v1801201010.zip",
        "TabelaUnificada_201802_v1802101010.zip",
    ]
    requisicoes = requisicoes_da_listagem(
        catalogo, FamiliaFonte.SIGTAP, "SP", [CompetenciaArquivo("201801")], nomes
    )
    assert [r.chave.versao_publicacao for r in requisicoes] == ["1801101010", "1801201010"]
    assert {r.chave.uf for r in requisicoes} == {None}


def test_competencias_auxiliares_vem_dos_registros_inclusive_antes_de_2018() -> None:
    atendimento = [CompetenciaAtendimento(c) for c in ("201801", "201712", "201710", "201711")]
    processamento = [CompetenciaProcessamento("201801")]
    auxiliares = competencias_auxiliares(atendimento, processamento)
    assert [c.valor for c in auxiliares] == ["201710", "201711", "201712", "201801"]
    assert all(isinstance(c, CompetenciaArquivo) for c in auxiliares)


def _catalogo_local(tmp_path: Path) -> Path:
    texto = CATALOGO.read_text(encoding="utf-8")
    for remoto in ("ftp://ftp.datasus.gov.br/dissemin/publicos", "ftp://ftp2.datasus.gov.br"):
        texto = texto.replace(remoto, (tmp_path / "origem").as_uri())
    destino = tmp_path / "sources.yaml"
    destino.write_text(texto, encoding="utf-8")
    return destino


def _publicar_origem(tmp_path: Path) -> None:
    dados = tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"
    st = tmp_path / "origem" / "CNES" / "200508_" / "Dados" / "ST"
    tup = tmp_path / "origem" / "pub" / "sistemas" / "tup" / "downloads"
    for pasta in (dados, st, tup):
        pasta.mkdir(parents=True)
    for nome in ("PASP1801a.dbc", "PASP1801b.dbc", "PASP1802a.dbc"):
        (dados / nome).write_bytes(dbc_sintetico(nome[-5]))
    for nome in ("STSP1712.dbc", "STSP1801.dbc", "STSP1802.dbc"):
        (st / nome).write_bytes(dbc_sintetico(nome[-5]))
    (tup / "TabelaUnificada_201801_v1801101010.zip").write_bytes(zip_sintetico({"a.txt": b"1"}))


def _config(tmp_path: Path, *, rede: bool, catalogo: Path | None) -> Path:
    linhas = [
        'versao: "1"',
        "runtime:",
        f"  raiz_dados: {tmp_path / 'data'}",
        f"  raiz_manifestos: {tmp_path / 'manifests'}",
        f"  rede_permitida: {'true' if rede else 'false'}",
        "piloto:",
        "  uf: SP",
        "  competencias_processamento: ['201801']",
        "  territorio: catalog/territorio/drs_xi.yaml",
        "  familias_fontes: [SIA_PA, CNES_ST, SIGTAP]",
    ]
    if catalogo is not None:
        linhas += ["catalogos:", f"  fontes: {catalogo}"]
    caminho = tmp_path / "config.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def _observacoes(tmp_path: Path):
    return Manifesto(tmp_path / "manifests" / "aquisicao.jsonl").ler().observacoes


def test_acquire_offline_recusa_e_registra_a_tentativa(tmp_path: Path) -> None:
    config = _config(tmp_path, rede=False, catalogo=None)
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.REDE_PROIBIDA
    (observacao,) = _observacoes(tmp_path)
    assert observacao.resultado is ResultadoTentativa.RECUSADO_OFFLINE
    assert observacao.chave.tipo_conteudo is TipoConteudo.LISTAGEM_DIRETORIO


def test_acquire_primaria_lista_e_obtem_todas_as_partes(tmp_path: Path) -> None:
    _publicar_origem(tmp_path)
    config = _config(tmp_path, rede=False, catalogo=_catalogo_local(tmp_path))
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.OK
    observacoes = _observacoes(tmp_path)
    arquivos = sorted(o.chave.nome_original for o in observacoes if o.chave.tipo_conteudo is None)
    assert arquivos == ["PASP1801a.dbc", "PASP1801b.dbc"]
    assert all(o.resultado is ResultadoTentativa.OBTIDO for o in observacoes)


def test_acquire_reexecutado_nao_reobserva_o_ja_obtido_sem_pedido(tmp_path: Path) -> None:
    _publicar_origem(tmp_path)
    config = str(_config(tmp_path, rede=False, catalogo=_catalogo_local(tmp_path)))
    cli.main(["acquire", "--config", config])
    cli.main(["acquire", "--config", config])
    arquivos = [o for o in _observacoes(tmp_path) if o.chave.tipo_conteudo is None]
    assert len(arquivos) == 2
    cli.main(["acquire", "--config", config, "--reobservar"])
    arquivos = [o for o in _observacoes(tmp_path) if o.chave.tipo_conteudo is None]
    assert len(arquivos) == 4


def test_acquire_auxiliar_exige_competencias_de_atendimento(tmp_path: Path) -> None:
    config = _config(tmp_path, rede=False, catalogo=_catalogo_local(tmp_path))
    argumentos = ["acquire", "--config", str(config), "--passada", "auxiliar"]
    assert cli.main(argumentos) == ExitCode.CONFIG_INVALIDA


def test_acquire_auxiliar_usa_so_competencias_observadas(tmp_path: Path) -> None:
    _publicar_origem(tmp_path)
    config = _config(tmp_path, rede=False, catalogo=_catalogo_local(tmp_path))
    competencias = tmp_path / "atendimento.txt"
    competencias.write_text("201712\n201801\n", encoding="utf-8")
    argumentos = ["acquire", "--config", str(config), "--passada", "auxiliar"]
    argumentos += ["--competencias-atendimento", str(competencias)]
    assert cli.main(argumentos) == ExitCode.OK
    obtidos = {
        (o.chave.fonte, o.chave.competencia_arquivo.valor)
        for o in _observacoes(tmp_path)
        if o.chave.competencia_arquivo is not None
    }
    assert obtidos == {
        (FamiliaFonte.CNES_ST, "201712"),
        (FamiliaFonte.CNES_ST, "201801"),
        (FamiliaFonte.SIGTAP, "201801"),
    }
    motivos = {o.chave.fonte for o in _observacoes(tmp_path)}
    assert FamiliaFonte.SIA_PA not in motivos
