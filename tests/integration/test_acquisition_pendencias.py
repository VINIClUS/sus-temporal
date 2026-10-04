"""P2 pendentes do T02 tratadas no PR do T06: descritores DBF, bytes pós-cabeçalho e HTTP."""

from __future__ import annotations

import http.client
import io
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

from sustemporal.acquisition import transport
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.transport import TransferenciaInterrompida
from sustemporal.acquisition.validation import validar_conteudo
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    MotivoRequisicao,
    SourceRequest,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte

if TYPE_CHECKING:
    from pathlib import Path


def _dbf_com_largura_errada() -> bytes:
    dbf = bytearray(escrever_dbf([CampoDbf("PA_X", "C", 2)], [("AB",)], com_eof=False))
    dbf[32 + 16] = 3
    return bytes(dbf)


@pytest.mark.parametrize("formato", [FormatoArquivo.DBF, FormatoArquivo.DBC])
def test_larguras_dos_descritores_precisam_somar_r_menos_1(
    tmp_path: Path, formato: FormatoArquivo
) -> None:
    dbf = _dbf_com_largura_errada()
    caminho = tmp_path / f"x.{formato.value.lower()}"
    caminho.write_bytes(dbf if formato is FormatoArquivo.DBF else dbf_para_dbc(dbf))
    veredito = validar_conteudo(caminho, formato)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert veredito.motivo is not None
    assert veredito.motivo.startswith("dbf_larguras_divergentes")


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
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def test_bytes_pos_cabecalho_do_dbc_ficam_na_versao(tmp_path: Path) -> None:
    dbf = escrever_dbf([CampoDbf("PA_X", "C", 1)], [("A",)])
    dbc = bytearray(dbf_para_dbc(dbf))
    cabecalho = int.from_bytes(dbc[8:10], "little")
    dbc[cabecalho : cabecalho + 4] = b"\x12\x34\xab\xcd"
    origem = tmp_path / "a.dbc"
    origem.write_bytes(bytes(dbc))
    store = tmp_path / "store"
    observacao = fetch_source(_requisicao(origem.as_uri()), store)
    versao = Manifesto(store / "manifesto.jsonl").ler().versoes[str(observacao.artifact_id)]
    assert versao.dbc_bytes_pos_cabecalho == "1234abcd"


class _RespostaCortada(io.BytesIO):
    headers: dict[str, str] = {}  # noqa: RUF012

    def geturl(self) -> str:
        return "https://exemplo.invalid/d.pdf"

    def read(self, tamanho: int | None = -1) -> bytes:
        if self.tell() == 0:
            return super().read(5)
        raise http.client.IncompleteRead(b"", 10)

    def __enter__(self) -> _RespostaCortada:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_resposta_http_cortada_e_interrupcao_com_bytes_recebidos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        transport.TransporteHTTPS, "_abrir", lambda _s, _r: _RespostaCortada(b"%PDF-123456789")
    )
    with pytest.raises(TransferenciaInterrompida) as erro:
        transport.TransporteHTTPS().baixar("https://exemplo.invalid/d.pdf", io.BytesIO(), 1000)
    assert erro.value.recebidos == 5


def test_descompressao_recusa_origem_irregular_ou_destino_sem_diretorio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sustemporal.acquisition import descompressao

    def proibido(*_a: object, **_k: object) -> None:
        raise AssertionError("subprocesso_nao_deveria_rodar")

    monkeypatch.setattr(descompressao.subprocess, "run", proibido)
    (tmp_path / "real.dbc").write_bytes(b"x")
    (tmp_path / "link.dbc").symlink_to(tmp_path / "real.dbc")
    casos = [
        (tmp_path, tmp_path / "saida.dbf"),
        (tmp_path / "link.dbc", tmp_path / "saida.dbf"),
        (tmp_path / "real.dbc", tmp_path / "nao_existe" / "saida.dbf"),
    ]
    for origem, destino in casos:
        resultado = descompressao.descomprimir_limitado(origem, destino, 100)
        assert resultado.desfecho is descompressao.DesfechoDescompressao.INVALIDO


def test_descompressao_roda_filho_isolado_com_caminhos_absolutos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import subprocess

    from sustemporal.acquisition import descompressao

    chamadas: list[list[str]] = []

    def capturar(comando: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        chamadas.append(comando)
        return subprocess.CompletedProcess(comando, 0, "", "")

    monkeypatch.setattr(descompressao.subprocess, "run", capturar)
    (tmp_path / "a.dbc").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    descompressao.descomprimir_limitado(type(tmp_path)("a.dbc"), type(tmp_path)("a.dbf"), 100)
    (comando,) = chamadas
    assert "-I" in comando
    assert "-B" in comando
    assert all(os.path.isabs(c) for c in comando[-2:])


class _RespostaComParcial(_RespostaCortada):
    def read(self, tamanho: int | None = -1) -> bytes:
        if self.tell() == 0:
            return super(_RespostaCortada, self).read(5)
        raise http.client.IncompleteRead(b"abc", 10)


def test_bytes_parciais_do_incomplete_read_sao_gravados_e_limitados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sustemporal.acquisition.transport import LimiteExcedido

    monkeypatch.setattr(
        transport.TransporteHTTPS, "_abrir", lambda _s, _r: _RespostaComParcial(b"%PDF-123456789")
    )
    destino = io.BytesIO()
    with pytest.raises(TransferenciaInterrompida) as erro:
        transport.TransporteHTTPS().baixar("https://exemplo.invalid/d.pdf", destino, 1000)
    assert erro.value.recebidos == 8
    assert destino.getvalue() == b"%PDF-abc"
    with pytest.raises(LimiteExcedido):
        transport.TransporteHTTPS().baixar("https://exemplo.invalid/d.pdf", io.BytesIO(), 6)
