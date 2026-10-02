"""Rodada 7 do Codex no PR #7: HTML em comentário, durabilidade do fragmento, disco local."""

from __future__ import annotations

import errno
import io
import os
from typing import TYPE_CHECKING

from tests.fixtures.aquisicao_dados import TransporteFalso, dbc_sintetico

from sustemporal.acquisition import fetch as modulo_fetch
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto
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

    import pytest


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


def test_pdf_valido_com_html_em_comentario_nao_e_html(tmp_path: Path) -> None:
    caminho = tmp_path / "x.pdf"
    caminho.write_bytes(b"%PDF-1.4\n% <html> citado num comentario\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    assert validar_conteudo(caminho, FormatoArquivo.PDF).integridade is EstadoIntegridade.OK


def test_pagina_html_com_preambulo_ainda_e_detectada(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(b"Erro 503\n<html><body>indisponivel</body></html>")
    veredito = validar_conteudo(caminho, FormatoArquivo.DBC)
    assert veredito.integridade is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert veredito.motivo == "html_no_lugar_de_dados"


def test_separacao_de_fragmento_torna_duraveis_fragmento_e_truncamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "store"
    origem = tmp_path / "a.dbc"
    origem.write_bytes(dbc_sintetico())
    fetch_source(_requisicao(origem.as_uri()), store)
    caminho = store / "manifesto.jsonl"
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write('{"sequencia": 3, "par')
    ordem: list[str] = []
    sincronizar, truncar = os.fsync, os.truncate

    def fsync(descritor: int) -> None:
        alvo = os.readlink(f"/proc/self/fd/{descritor}")
        nome = "dir" if os.path.isdir(alvo) else os.path.basename(alvo).split(".")[-1]
        ordem.append(f"fsync:{'fragmento' if '.fragmento.' in alvo else nome}")
        sincronizar(descritor)

    def ftruncate(descritor: int | str, tamanho: int) -> None:
        ordem.append("truncate")
        truncar(descritor, tamanho)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "truncate", ftruncate)
    monkeypatch.setattr(os, "ftruncate", ftruncate)
    Manifesto(caminho).preparar()
    assert ordem[:5] == ["fsync:fragmento", "fsync:dir", "truncate", "fsync:jsonl", "fsync:dir"]


class _DiscoCheio(io.BytesIO):
    def write(self, dados: object) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")


def test_falha_de_escrita_no_temporario_e_falha_de_armazenamento(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo_fetch, "_abrir_temporario", lambda _caminho: _DiscoCheio())
    store = tmp_path / "store"
    observacao = fetch_source(
        _requisicao("ftp://ftp.exemplo.invalid/PASP1801a.dbc"),
        store,
        rede_permitida=True,
        transportes={"ftp": TransporteFalso(conteudo=dbc_sintetico())},
    )
    assert observacao.resultado is ResultadoTentativa.FALHA_ARMAZENAMENTO
    assert observacao.erro is not None
    assert "temporario" in observacao.erro
    assert Manifesto(store / "manifesto.jsonl").ler().observacoes == (observacao,)
