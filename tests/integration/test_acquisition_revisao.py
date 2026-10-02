"""Casos da revisão adversarial do T02: mutações sobreviventes e falhas sem observação."""

from __future__ import annotations

import http.client
import io
import warnings
import zipfile
from pathlib import Path

import pytest
from tests.fixtures.aquisicao_dados import (
    HTML_DE_ERRO,
    Relogio,
    TransporteFalso,
    dbc_sintetico,
)

from sustemporal import cli
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto, ManifestoCorrompido
from sustemporal.acquisition.sources import carregar_catalogo, requisicoes_da_listagem
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte
from sustemporal.contracts.temporal import CompetenciaArquivo
from sustemporal.errors import ExitCode

CATALOGO = Path("catalog/sources.yaml")


def _requisicao(localizador: str, formato: FormatoArquivo = FormatoArquivo.DBC) -> SourceRequest:
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
        formato_esperado=formato,
        tamanho_maximo_bytes=10_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def _local(tmp_path: Path, conteudo: bytes, formato: FormatoArquivo) -> SourceRequest:
    arquivo = tmp_path / "origem.bin"
    arquivo.write_bytes(conteudo)
    return _requisicao(arquivo.as_uri(), formato)


def _versao(store: Path, artifact_id: str | None):
    return Manifesto(store / "manifesto.jsonl").ler().versoes[str(artifact_id)]


@pytest.mark.parametrize(
    "erro",
    [
        http.client.IncompleteRead(b"parcial"),
        http.client.BadStatusLine("lixo"),
        ValueError("porta invalida"),
    ],
    ids=["incomplete_read", "bad_status_line", "value_error"],
)
def test_excecao_inesperada_do_transporte_ainda_registra_observacao(
    tmp_path: Path, erro: Exception
) -> None:
    store = tmp_path / "store"
    observacao = fetch_source(
        _requisicao("https://exemplo.invalid/PASP1801a.dbc"),
        store,
        rede_permitida=True,
        transportes={"https": TransporteFalso(erro=erro)},
    )
    assert observacao.resultado is ResultadoTentativa.FALHA_TRANSPORTE
    assert Manifesto(store / "manifesto.jsonl").ler().observacoes == (observacao,)


def test_observacao_de_falha_guarda_o_localizador_pedido(tmp_path: Path) -> None:
    localizador = (tmp_path / "nao_existe.dbc").as_uri()
    observacao = fetch_source(_requisicao(localizador), tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.NAO_ENCONTRADO
    assert observacao.localizador == localizador


def test_zip_cifrado_fica_em_quarentena(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("dados.txt", b"x")
    conteudo = bytearray(buffer.getvalue())
    central = conteudo.index(b"PK\x01\x02")
    conteudo[6] |= 0x1
    conteudo[central + 8] |= 0x1
    observacao = fetch_source(
        _local(tmp_path, bytes(conteudo), FormatoArquivo.ZIP), tmp_path / "store"
    )
    versao = _versao(tmp_path / "store", observacao.artifact_id)
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO


def test_zip_com_nome_duplicado_fica_em_quarentena(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(buffer, "w") as arquivo:
            arquivo.writestr("dados.txt", b"um")
            arquivo.writestr("dados.txt", b"outro")
    observacao = fetch_source(
        _local(tmp_path, buffer.getvalue(), FormatoArquivo.ZIP), tmp_path / "store"
    )
    versao = _versao(tmp_path / "store", observacao.artifact_id)
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO


def test_dbc_com_fluxo_dcl_invalido_fica_em_quarentena(tmp_path: Path) -> None:
    conteudo = bytearray(dbc_sintetico())
    cabecalho = int.from_bytes(conteudo[8:10], "little")
    conteudo[cabecalho + 5] = 7
    observacao = fetch_source(
        _local(tmp_path, bytes(conteudo), FormatoArquivo.DBC), tmp_path / "store"
    )
    versao = _versao(tmp_path / "store", observacao.artifact_id)
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO


@pytest.mark.parametrize("formato", [FormatoArquivo.TXT, FormatoArquivo.CSV])
def test_html_no_lugar_de_texto_fica_em_quarentena(tmp_path: Path, formato: FormatoArquivo) -> None:
    observacao = fetch_source(_local(tmp_path, HTML_DE_ERRO, formato), tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO


def test_listagem_nunca_usa_o_mes_anterior_nem_o_seguinte() -> None:
    catalogo = carregar_catalogo(CATALOGO)
    nomes = ["PASP1711a.dbc", "PASP1801a.dbc"]
    requisicoes = requisicoes_da_listagem(
        catalogo, FamiliaFonte.SIA_PA, "SP", [CompetenciaArquivo("201712")], nomes
    )
    assert requisicoes == []


def _tres_registros(tmp_path: Path) -> Path:
    store = tmp_path / "store"
    relogio = Relogio()
    for valor in ("A", "B", "C"):
        fetch_source(
            _local(tmp_path, dbc_sintetico(valor), FormatoArquivo.DBC), store, relogio=relogio
        )
    return store / "manifesto.jsonl"


@pytest.mark.parametrize("operacao", ["remover_finais", "reescrever_ultima"])
def test_manifesto_detecta_alteracao_no_fim_pela_ancora(tmp_path: Path, operacao: str) -> None:
    caminho = _tres_registros(tmp_path)
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    if operacao == "remover_finais":
        linhas = linhas[:-2]
    else:
        linhas[-1] = linhas[-1].replace("2026-09-01T12:02:00", "2026-09-01T12:09:00")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with pytest.raises(ManifestoCorrompido, match="ancora"):
        Manifesto(caminho).ler()


def test_fragmento_de_escrita_interrompida_e_separado_e_registro_continua(tmp_path: Path) -> None:
    caminho = _tres_registros(tmp_path)
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write('{"sequencia": 7, "tip')
    observacao = fetch_source(
        _local(tmp_path, dbc_sintetico("D"), FormatoArquivo.DBC), caminho.parent
    )
    estado = Manifesto(caminho).ler()
    assert estado.observacoes[-1] == observacao
    assert len(estado.observacoes) == 4
    fragmentos = list(caminho.parent.glob("manifesto.jsonl.fragmento.*"))
    assert [f.read_text(encoding="utf-8") for f in fragmentos] == ['{"sequencia": 7, "tip']


def _config(tmp_path: Path, catalogo: Path) -> Path:
    texto = "\n".join(
        [
            'versao: "1"',
            "runtime:",
            f"  raiz_dados: {tmp_path / 'data'}",
            f"  raiz_manifestos: {tmp_path / 'manifests'}",
            "piloto:",
            "  uf: SP",
            "  competencias_processamento: ['201801']",
            "  territorio: catalog/territorio/drs_xi.yaml",
            "  familias_fontes: [SIA_PA]",
            "catalogos:",
            f"  fontes: {catalogo}",
        ]
    )
    caminho = tmp_path / "config.yaml"
    caminho.write_text(texto + "\n", encoding="utf-8")
    return caminho


@pytest.mark.parametrize("criar_diretorio", [False, True], ids=["ausente", "vazio"])
def test_acquire_com_listagem_ausente_ou_vazia_nao_sai_ok(
    tmp_path: Path, criar_diretorio: bool
) -> None:
    origem = tmp_path / "origem"
    if criar_diretorio:
        (origem / "SIASUS" / "200801_" / "Dados").mkdir(parents=True)
    texto = CATALOGO.read_text(encoding="utf-8")
    texto = texto.replace("ftp://ftp.datasus.gov.br/dissemin/publicos", origem.as_uri())
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    config = _config(tmp_path, catalogo)
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.FALHA_OPERACIONAL


def test_manifesto_zerado_com_ancora_presente_e_corrompido(tmp_path: Path) -> None:
    caminho = _tres_registros(tmp_path)
    caminho.write_text("", encoding="utf-8")
    with pytest.raises(ManifestoCorrompido, match="ancora"):
        Manifesto(caminho).ler()
    with pytest.raises(ManifestoCorrompido):
        fetch_source(_local(tmp_path, dbc_sintetico("D"), FormatoArquivo.DBC), caminho.parent)


def test_queda_antes_da_primeira_ancora_nao_bloqueia_o_manifesto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store"

    original = Manifesto._gravar_ancora

    def cair(manifesto: Manifesto, sequencia: int, sha256: str | None) -> None:
        if sequencia > 0:
            raise KeyboardInterrupt
        original(manifesto, sequencia, sha256)

    with monkeypatch.context() as contexto:
        contexto.setattr(Manifesto, "_gravar_ancora", cair)
        with pytest.raises(KeyboardInterrupt):
            fetch_source(_local(tmp_path, dbc_sintetico("A"), FormatoArquivo.DBC), store)
    assert (store / "manifesto.jsonl").read_text(encoding="utf-8")
    observacao = fetch_source(_local(tmp_path, dbc_sintetico("B"), FormatoArquivo.DBC), store)
    assert Manifesto(store / "manifesto.jsonl").ler().observacoes[-1] == observacao


@pytest.mark.parametrize("conteudo", [b"%PDF-", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"])
def test_pdf_sem_marcador_final_fica_em_quarentena(tmp_path: Path, conteudo: bytes) -> None:
    observacao = fetch_source(_local(tmp_path, conteudo, FormatoArquivo.PDF), tmp_path / "store")
    versao = _versao(tmp_path / "store", observacao.artifact_id)
    assert versao.integridade is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_pdf_com_marcador_final_e_obtido(tmp_path: Path) -> None:
    conteudo = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    observacao = fetch_source(_local(tmp_path, conteudo, FormatoArquivo.PDF), tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.OBTIDO


def test_zip_com_membro_corrompido_fica_em_quarentena(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr("tb_procedimento.txt", b"0101010010" * 200)
    conteudo = bytearray(buffer.getvalue())
    dados = 30 + len("tb_procedimento.txt")
    conteudo[dados + 5] ^= 0xFF
    observacao = fetch_source(
        _local(tmp_path, bytes(conteudo), FormatoArquivo.ZIP), tmp_path / "store"
    )
    versao = _versao(tmp_path / "store", observacao.artifact_id)
    assert versao.integridade is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_fragmento_apos_linha_de_versao_completa_e_separado(tmp_path: Path) -> None:
    caminho = _tres_registros(tmp_path)
    estado = Manifesto(caminho).ler()
    proxima = estado.linhas[-1].model_copy(
        update={
            "sequencia": estado.linhas[-1].sequencia + 1,
            "anterior_sha256": estado.linhas[-1].sha256(),
            "tipo": "VERSAO",
            "observacao": None,
            "versao": estado.versoes[next(iter(estado.versoes))].model_copy(
                update={"artifact_id": f"art_{'f' * 64}"}
            ),
        }
    )
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(proxima.model_dump_json() + "\n" + '{"sequencia": 99, "ti')
    observacao = fetch_source(
        _local(tmp_path, dbc_sintetico("D"), FormatoArquivo.DBC), caminho.parent
    )
    assert Manifesto(caminho).ler().observacoes[-1] == observacao
    (fragmento,) = caminho.parent.glob("manifesto.jsonl.fragmento.*")
    assert proxima.model_dump_json() in fragmento.read_text(encoding="utf-8")


class _Resposta(io.BytesIO):
    def __init__(self, url: str) -> None:
        super().__init__(b"%PDF-1.4\n%%EOF\n")
        self.headers: dict[str, str] = {}
        self.url = url

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> _Resposta:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@pytest.mark.parametrize("destino", ["http://exemplo.invalid/d.pdf", "ftp://exemplo.invalid/d"])
def test_redirecionamento_que_sai_do_https_e_recusado(destino: str) -> None:
    import urllib.request

    from sustemporal.acquisition.transport import ErroTransporte, RedirecionamentoSoHTTPS

    manipulador = RedirecionamentoSoHTTPS()
    requisicao = urllib.request.Request("https://exemplo.invalid/d.pdf")
    with pytest.raises(ErroTransporte, match="redirecionamento_fora_de_https"):
        manipulador.redirect_request(requisicao, io.BytesIO(), 302, "Found", {}, destino)
    seguro = manipulador.redirect_request(
        requisicao, io.BytesIO(), 302, "Found", {}, "https://outro.invalid/d.pdf"
    )
    assert seguro is not None
    assert seguro.full_url == "https://outro.invalid/d.pdf"


def test_url_final_do_https_fica_nos_metadados(monkeypatch: pytest.MonkeyPatch) -> None:
    from sustemporal.acquisition import transport

    final = "https://espelho.invalid/d.pdf"
    monkeypatch.setattr(transport.TransporteHTTPS, "_abrir", lambda _self, _req: _Resposta(final))
    destino = io.BytesIO()
    recebimento = transport.TransporteHTTPS().baixar("https://exemplo.invalid/d.pdf", destino, 1000)
    assert recebimento.metadados["url_final"] == final
