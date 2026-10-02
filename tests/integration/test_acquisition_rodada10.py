"""Rodada do Codex em 42b7a78: DBC sem teto de saída, temporário local e conflito de prefixo."""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.aquisicao_dados import dbc_sintetico
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

from sustemporal.acquisition import fetch as modulo_fetch
from sustemporal.acquisition import validation as modulo_validacao
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.validation import validar_conteudo
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    MotivoRequisicao,
    ResultadoTentativa,
    SourceRequest,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte

if TYPE_CHECKING:
    from pathlib import Path


def _dbf() -> bytes:
    return escrever_dbf([CampoDbf("PA_X", "C", 1)], [("A",)])


def test_dbc_que_declara_mais_que_o_teto_nao_e_descomprimido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def proibido(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("descompressao_nao_deveria_rodar")

    monkeypatch.setattr(modulo_validacao, "descomprimir_limitado", proibido, raising=False)
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbf_para_dbc(_dbf()))
    veredito = validar_conteudo(caminho, FormatoArquivo.DBC, limite_dbf_bytes=10)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert veredito.motivo is not None
    assert veredito.motivo.startswith("dbc_declarado_excede")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.dbc"]


def test_fluxo_que_produz_mais_que_o_declarado_para_no_teto(tmp_path: Path) -> None:
    dbf = _dbf()
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbf_para_dbc(dbf + b"x" * 50_000))
    veredito = validar_conteudo(caminho, FormatoArquivo.DBC)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert veredito.motivo is not None
    assert veredito.motivo.startswith("dbc_descomprimido_excede")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.dbc"]


def test_dbc_legitimo_continua_ok_com_teto(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(dbf_para_dbc(_dbf()))
    veredito = validar_conteudo(caminho, FormatoArquivo.DBC, limite_dbf_bytes=len(_dbf()))
    assert veredito.integridade is EstadoIntegridade.OK


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
        motivo=MotivoRequisicao.PRIMARIA,
    )


class _FechamentoFalho(io.BytesIO):
    def close(self) -> None:
        super().close()
        raise OSError(5, "Input/output error")


def _abrir_falho(_caminho: Path) -> io.BytesIO:
    raise OSError(13, "Permission denied")


@pytest.mark.parametrize("abrir", [_abrir_falho, lambda _c: _FechamentoFalho()])
def test_falha_ao_abrir_ou_fechar_o_temporario_e_falha_de_armazenamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, abrir: object
) -> None:
    monkeypatch.setattr(modulo_fetch, "_abrir_temporario", abrir)
    origem = tmp_path / "a.dbc"
    origem.write_bytes(dbc_sintetico())
    observacao = fetch_source(_requisicao(origem.as_uri()), tmp_path / "store")
    assert observacao.resultado is ResultadoTentativa.FALHA_ARMAZENAMENTO
    assert observacao.erro is not None
    assert "temporario" in observacao.erro


@pytest.mark.parametrize(
    "nomes",
    [("dados", "dados/"), ("dados", "dados/arquivo.txt"), ("Dados", "dados/x.txt")],
)
def test_conflito_entre_arquivo_e_diretorio_fica_inseguro(
    tmp_path: Path, nomes: tuple[str, ...]
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        for nome in nomes:
            arquivo.writestr(zipfile.ZipInfo(nome), b"" if nome.endswith("/") else b"1")
    caminho = tmp_path / "x.zip"
    caminho.write_bytes(buffer.getvalue())
    veredito = validar_conteudo(caminho, FormatoArquivo.ZIP)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO
