"""Revisão do orquestrador no PR #7: ZIP ilegível, bomba, DBC inteiro, limites e documentos."""

from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest
from tests.fixtures.aquisicao_dados import dbc_sintetico, servidor_ftp

from sustemporal import cli
from sustemporal.acquisition import fetch as modulo_fetch
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto, ManifestoCorrompido
from sustemporal.acquisition.sources import carregar_catalogo, requisicoes_documentos
from sustemporal.acquisition.transport import (
    ErroTransporte,
    LimiteExcedido,
    TransferenciaInterrompida,
    TransporteArquivo,
    TransporteFTP,
    _Gravador,
)
from sustemporal.acquisition.validation import LimitesZip, validar_conteudo
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    LinhaManifesto,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
    TipoLinhaManifesto,
    calcular_artifact_id,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte
from sustemporal.errors import ExitCode

CATALOGO = Path("catalog/sources.yaml")


def _requisicao(localizador: str, formato: FormatoArquivo) -> SourceRequest:
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIGTAP,
        competencia_arquivo="201801",
        canal=CanalPublicacao.ATUAL,
        nome_original="t.zip",
    )
    return SourceRequest(
        chave=chave,
        localizador=localizador,
        formato_esperado=formato,
        tamanho_maximo_bytes=50_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def _local(tmp_path: Path, conteudo: bytes, formato: FormatoArquivo) -> SourceRequest:
    arquivo = tmp_path / "origem.bin"
    arquivo.write_bytes(conteudo)
    return _requisicao(arquivo.as_uri(), formato)


def _zip_ilegivel(variante: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("tb_x.txt", b"1")
    dados = bytearray(buffer.getvalue())
    central = dados.index(b"PK\x01\x02")
    if variante == "versao_alta":
        dados[central + 6] = 0xFF
    else:
        dados[central + 9] |= 0x08
        dados[central + 46] = 0xFF
    return bytes(dados)


@pytest.mark.parametrize("variante", ["versao_alta", "utf8_invalido"])
def test_zip_ilegivel_vira_quarentena_com_observacao(tmp_path: Path, variante: str) -> None:
    store = tmp_path / "store"
    requisicao = _local(tmp_path, _zip_ilegivel(variante), FormatoArquivo.ZIP)
    observacao = fetch_source(requisicao, store)
    assert observacao.resultado is ResultadoTentativa.CONTEUDO_INVALIDO
    estado = Manifesto(store / "manifesto.jsonl").ler()
    assert estado.observacoes == (observacao,)
    versao = estado.versoes[str(observacao.artifact_id)]
    assert versao.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert versao.caminho_conteudo.startswith("quarentena/")


def test_falha_inesperada_na_guarda_registra_observacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explodir(*_args: object) -> None:
        raise RuntimeError("inesperado")

    monkeypatch.setattr(modulo_fetch, "validar_conteudo", explodir)
    store = tmp_path / "store"
    observacao = fetch_source(_local(tmp_path, dbc_sintetico(), FormatoArquivo.DBC), store)
    assert observacao.resultado is ResultadoTentativa.FALHA_ARMAZENAMENTO
    assert Manifesto(store / "manifesto.jsonl").ler().observacoes == (observacao,)
    assert not any(p.is_file() for p in (store / "tmp").rglob("*"))


def test_falha_ao_criar_temporario_registra_observacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sem_espaco(*_args: object, **_kwargs: object) -> tuple[int, str]:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(modulo_fetch.tempfile, "mkstemp", sem_espaco)
    store = tmp_path / "store"
    observacao = fetch_source(_local(tmp_path, dbc_sintetico(), FormatoArquivo.DBC), store)
    assert observacao.resultado is ResultadoTentativa.FALHA_ARMAZENAMENTO
    assert Manifesto(store / "manifesto.jsonl").ler().observacoes == (observacao,)


def _zip(membros: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as arquivo:
        for nome, conteudo in membros.items():
            arquivo.writestr(nome, conteudo)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("limites", "motivo"),
    [
        (LimitesZip(descompactado_bytes=1_000_000), "zip_descompactado_excede"),
        (LimitesZip(razao=100), "zip_razao_excede"),
        (LimitesZip(membros=1), "zip_membros_excede"),
    ],
)
def test_bomba_de_compressao_vai_para_quarentena_antes_de_descompactar(
    tmp_path: Path, limites: LimitesZip, motivo: str
) -> None:
    caminho = tmp_path / "bomba.zip"
    caminho.write_bytes(_zip({"zeros.txt": bytes(4_000_000), "outro.txt": b"1"}))
    veredito = validar_conteudo(caminho, FormatoArquivo.ZIP, limites=limites)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert veredito.motivo is not None
    assert veredito.motivo.startswith(motivo)


def test_limites_padrao_recusam_razao_de_bomba(tmp_path: Path) -> None:
    caminho = tmp_path / "bomba.zip"
    caminho.write_bytes(_zip({"zeros.txt": bytes(20_000_000)}))
    veredito = validar_conteudo(caminho, FormatoArquivo.ZIP)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO


@pytest.mark.parametrize("nomes", [("DADOS.TXT", "dados.txt"), ("café.txt", "café.txt")])
def test_nomes_que_colidem_por_caixa_ou_normalizacao_ficam_inseguros(
    tmp_path: Path, nomes: tuple[str, str]
) -> None:
    caminho = tmp_path / "colisao.zip"
    caminho.write_bytes(_zip(dict.fromkeys(nomes, b"1")))
    veredito = validar_conteudo(caminho, FormatoArquivo.ZIP)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO
    assert [m.seguro for m in veredito.membros] == [True, False]


def _dbc_cortado(tmp_path: Path, corte: int) -> Path:
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbc_sintetico()[:-corte])
    return caminho


def test_dbc_com_fluxo_truncado_fica_em_quarentena(tmp_path: Path) -> None:
    veredito = validar_conteudo(_dbc_cortado(tmp_path, 3), FormatoArquivo.DBC)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_TRUNCADO
    assert not list(tmp_path.glob("*.dbf*"))


def test_dbc_integro_descomprime_e_confere_tamanho(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbc_sintetico())
    assert validar_conteudo(caminho, FormatoArquivo.DBC).integridade is EstadoIntegridade.OK
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.dbc"]


def test_dbc_que_descomprime_menor_que_o_cabecalho_fica_truncado(tmp_path: Path) -> None:
    from tests.fixtures.dbc_encoder import dbf_para_dbc
    from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

    campos = [CampoDbf("PA_X", "C", 4)]
    dbf = escrever_dbf(campos, [("AAAA",), ("BBBB",)], com_eof=False)
    curto = dbf[:-5]
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbf_para_dbc(curto))
    veredito = validar_conteudo(caminho, FormatoArquivo.DBC)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_leitura_recusa_segunda_versao_com_mesmo_artifact_id(tmp_path: Path) -> None:
    store = tmp_path / "store"
    fetch_source(_local(tmp_path, dbc_sintetico(), FormatoArquivo.DBC), store)
    caminho = store / "manifesto.jsonl"
    estado = Manifesto(caminho).ler()
    versao = next(iter(estado.versoes.values()))
    ultima = estado.linhas[-1]
    repetida = LinhaManifesto(
        sequencia=ultima.sequencia + 1,
        tipo=TipoLinhaManifesto.VERSAO,
        versao=versao,
        anterior_sha256=ultima.sha256(),
    )
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(repetida.model_dump_json() + "\n")
    with pytest.raises(ManifestoCorrompido, match="versao_repetida"):
        Manifesto(caminho).ler()


def test_ancora_sincroniza_o_diretorio_depois_de_substituir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ordem: list[str] = []
    substituir, sincronizar = os.replace, os.fsync

    def replace(origem: object, destino: object) -> None:
        ordem.append(f"replace:{Path(str(destino)).name}")
        substituir(str(origem), str(destino))

    def fsync(descritor: int) -> None:
        alvo = Path(os.readlink(f"/proc/self/fd/{descritor}"))
        ordem.append(f"fsync:{'dir' if alvo.is_dir() else alvo.name}")
        sincronizar(descritor)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "fsync", fsync)
    fetch_source(_local(tmp_path, dbc_sintetico(), FormatoArquivo.DBC), tmp_path / "store")
    primeira = ordem.index("replace:manifesto.jsonl.ancora")
    assert ordem[primeira + 1] == "fsync:dir"
    assert ordem.index("fsync:manifesto.jsonl") > primeira + 1


def test_documentos_com_bytes_iguais_tem_versoes_distintas() -> None:
    requisicoes = requisicoes_documentos(carregar_catalogo(CATALOGO))
    ids = {calcular_artifact_id(r.chave, "a" * 64) for r in requisicoes}
    assert len(ids) == len(requisicoes)
    assert all(r.chave.documento_id == r.chave.nome_original for r in requisicoes)


def test_ftp_limite_excedido_preserva_a_causa(tmp_path: Path) -> None:
    (tmp_path / "ftp").mkdir()
    (tmp_path / "ftp" / "grande.bin").write_bytes(bytes(200_000))
    gravados = io.BytesIO()
    with servidor_ftp(tmp_path / "ftp") as porta:
        for limite in (10, 70_000):
            with pytest.raises(LimiteExcedido):
                TransporteFTP(timeout=5).baixar(
                    f"ftp://127.0.0.1:{porta}/grande.bin", gravados, limite
                )


def test_gravador_respeita_prazo_total() -> None:
    gravador = _Gravador(io.BytesIO(), 1000, prazo=time.monotonic() - 1)
    with pytest.raises(TransferenciaInterrompida, match="prazo_total_excedido"):
        gravador(b"x")


def test_transporte_de_arquivo_com_raiz_recusa_fuga_e_link(tmp_path: Path) -> None:
    raiz = tmp_path / "importacao"
    raiz.mkdir()
    (tmp_path / "fora.dbc").write_bytes(b"x")
    (raiz / "link.dbc").symlink_to(tmp_path / "fora.dbc")
    transporte = TransporteArquivo(raiz=raiz)
    for alvo in (raiz / ".." / "fora.dbc", raiz / "link.dbc", Path("/proc/self/environ")):
        with pytest.raises(ErroTransporte, match=r"fora_da_raiz|link_simbolico"):
            transporte.baixar(alvo.as_uri(), io.BytesIO(), 1000)


def test_link_simbolico_e_recusado_mesmo_sem_raiz(tmp_path: Path) -> None:
    (tmp_path / "real.dbc").write_bytes(b"x")
    (tmp_path / "link.dbc").symlink_to(tmp_path / "real.dbc")
    with pytest.raises(ErroTransporte, match="link_simbolico"):
        TransporteArquivo().baixar((tmp_path / "link.dbc").as_uri(), io.BytesIO(), 1000)


def test_acquire_sai_nao_ok_quando_competencia_falta_na_listagem(tmp_path: Path) -> None:
    dados = tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"
    dados.mkdir(parents=True)
    (dados / "PASP1802a.dbc").write_bytes(dbc_sintetico())
    texto = CATALOGO.read_text(encoding="utf-8").replace(
        "ftp://ftp.datasus.gov.br/dissemin/publicos", (tmp_path / "origem").as_uri()
    )
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
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
        + "\n",
        encoding="utf-8",
    )
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.FALHA_OPERACIONAL


def test_observacao_guarda_a_caracterizacao_da_propria_tentativa(tmp_path: Path) -> None:
    store = tmp_path / "store"
    conteudo = dbc_sintetico()
    primeira = fetch_source(_local(tmp_path, conteudo, FormatoArquivo.ZIP), store)
    segunda = fetch_source(_local(tmp_path, conteudo, FormatoArquivo.DBC), store)
    assert primeira.artifact_id == segunda.artifact_id
    assert primeira.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert primeira.formato is FormatoArquivo.ZIP
    assert segunda.resultado is ResultadoTentativa.OBTIDO
    assert segunda.integridade is EstadoIntegridade.OK
    assert segunda.formato is FormatoArquivo.DBC
    estado = Manifesto(store / "manifesto.jsonl").ler()
    assert [x.tipo.value for x in estado.linhas] == ["VERSAO", "OBSERVACAO", "OBSERVACAO"]


@pytest.mark.parametrize(
    ("final", "estado"),
    [(b"\x1a", EstadoIntegridade.OK), (b"\x00", EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO)],
)
def test_dbf_descomprimido_com_byte_extra_exige_0x1a(
    tmp_path: Path, final: bytes, estado: EstadoIntegridade
) -> None:
    from tests.fixtures.dbc_encoder import dbf_para_dbc
    from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

    dbf = escrever_dbf([CampoDbf("PA_X", "C", 4)], [("AAAA",)], com_eof=False) + final
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbf_para_dbc(dbf))
    assert validar_conteudo(caminho, FormatoArquivo.DBC).integridade is estado


def test_competencia_sem_arquivo_na_listagem_e_aviso(caplog: pytest.LogCaptureFixture) -> None:
    from sustemporal.acquisition.sources import requisicoes_da_listagem
    from sustemporal.contracts.temporal import CompetenciaArquivo

    catalogo = carregar_catalogo(CATALOGO)
    with caplog.at_level("INFO"):
        requisicoes_da_listagem(
            catalogo, FamiliaFonte.SIA_PA, "SP", [CompetenciaArquivo("201801")], ["PASP1802a.dbc"]
        )
    avisos = [r for r in caplog.records if "competencia_sem_arquivo" in r.getMessage()]
    assert [r.levelname for r in avisos] == ["WARNING"]
