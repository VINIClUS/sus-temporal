"""Leiaute embutido no zip do SIGTAP e coerência do catálogo com os esquemas (SINTETICO)."""

from __future__ import annotations

import functools
import io
import zipfile

import pytest

from sustemporal.contracts import EsquemaCanonico, EstadoIntegridade, LayoutSpec, PapelColuna
from sustemporal.ingest.dbf import QuarentenaLeitura
from sustemporal.ingest.sigtap import ESQUEMAS, TABELAS
from sustemporal.ingest.sigtap_zip import (
    carregar_leiautes_sigtap,
    conferir_leiaute,
    fatiar,
    ler_leiaute_zip,
    ler_membro,
)
from tests.fixtures.sigtap_zip import COLUNAS, texto_leiaute, zip_sigtap


@functools.cache
def _leiautes() -> dict[str, LayoutSpec]:
    return carregar_leiautes_sigtap()


def test_catalogo_tem_um_leiaute_por_tabela_normalizada() -> None:
    assert set(_leiautes()) == set(TABELAS)
    assert all(layout.layout_id == f"sigtap.{tabela}" for tabela, layout in _leiautes().items())


@pytest.mark.parametrize("tabela", sorted(TABELAS))
def test_leiaute_do_catalogo_cobre_o_esquema_canonico(tabela: str) -> None:
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{TABELAS[tabela]}.yaml")
    derivadas = set(esquema.colunas_com_papel(PapelColuna.BRUTO))
    derivadas |= set(esquema.colunas_com_papel(PapelColuna.MOTIVO)) | {"artifact_id"}
    canonicos = {campo.nome_canonico for campo in _leiautes()[tabela].campos}
    assert canonicos == {c.nome for c in esquema.colunas} - derivadas
    tipos = {c.nome: c.tipo for c in esquema.colunas}
    assert all(
        campo.tipo_canonico is tipos[campo.nome_canonico] for campo in _leiautes()[tabela].campos
    )


def test_leiaute_do_catalogo_e_a_confirmar_e_nao_oficial() -> None:
    for layout in _leiautes().values():
        assert layout.confirmacao.value == "A_CONFIRMAR"
        assert not layout.proveniencia.value.startswith("OFICIAL")


def test_le_leiaute_embutido_com_posicoes_contiguas() -> None:
    colunas = ler_leiaute_zip(texto_leiaute(COLUNAS["rl_procedimento_ocupacao"]))
    assert [(c.nome, c.inicio, c.fim) for c in colunas] == [
        ("CO_PROCEDIMENTO", 1, 10),
        ("CO_OCUPACAO", 11, 16),
        ("DT_COMPETENCIA", 17, 22),
    ]


@pytest.mark.parametrize(
    "texto",
    [
        b"Coluna,Tamanho,Inicio,Fim\r\nCO_REGISTRO,2,1,2\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nCO_REGISTRO,2,1,3,VARCHAR2\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nCO_REGISTRO,2,2,3,VARCHAR2\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nA,2,1,2,CHAR\r\nB,2,4,5,CHAR\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nA,2,1,2,CHAR\r\nA,2,3,4,CHAR\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nA,x,1,2,CHAR\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\nA,0,1,0,CHAR\r\n",
        b"Coluna,Tamanho,Inicio,Fim,Tipo\r\n",
    ],
    ids=[
        "cabecalho",
        "fim_incoerente",
        "nao_comeca_em_1",
        "lacuna",
        "nome_repetido",
        "nao_numerico",
        "tamanho_zero",
        "sem_colunas",
    ],
)
def test_leiaute_embutido_incoerente_vai_para_quarentena(texto: bytes) -> None:
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_leiaute_zip(texto)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_tipo_fisico_divergente_vai_para_quarentena() -> None:
    texto = texto_leiaute(COLUNAS["tb_registro"]).replace(b"CHAR", b"DATE")
    with pytest.raises(QuarentenaLeitura, match="tipo_divergente"):
        conferir_leiaute(ler_leiaute_zip(texto), _leiautes()["tb_registro"])


def test_coluna_extra_vai_para_quarentena() -> None:
    texto = texto_leiaute(COLUNAS["tb_registro"]) + b"EXTRA,1,59,59,CHAR\r\n"
    with pytest.raises(QuarentenaLeitura, match="colunas_divergentes"):
        conferir_leiaute(ler_leiaute_zip(texto), _leiautes()["tb_registro"])


def test_fatiar_aceita_lf_e_crlf_e_preserva_espacos() -> None:
    colunas = ler_leiaute_zip(texto_leiaute(COLUNAS["tb_registro"]))
    linha = "01" + "BPA".ljust(50) + "201801"
    recortes = fatiar(f"{linha}\r\n{linha}\n{linha}".encode("latin-1"), colunas)
    assert recortes[0] == ["01", "01", "01"]
    assert recortes[1] == ["BPA".ljust(50)] * 3


def test_fatiar_recusa_linha_com_largura_divergente_no_meio() -> None:
    colunas = ler_leiaute_zip(texto_leiaute(COLUNAS["tb_registro"]))
    linha = "01" + "BPA".ljust(50) + "201801"
    with pytest.raises(QuarentenaLeitura) as erro:
        fatiar(f"{linha}X\r\n{linha}\r\n".encode("latin-1"), colunas)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


def _zip(membros: dict[str, bytes]) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(zip_sigtap(membros)))


@pytest.mark.parametrize("nome", ["../tb_registro.txt", "pasta/tb_registro.txt", ""])
def test_nome_de_membro_invalido_e_recusado(nome: str) -> None:
    with _zip({"tb_registro.txt": b"x"}) as arquivo, pytest.raises(QuarentenaLeitura) as erro:
        ler_membro(arquivo, nome, 1000)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO


def test_membro_repetido_ou_com_caixa_diferente_vai_para_quarentena() -> None:
    membros = {"tb_registro.txt": b"x", "TB_REGISTRO.TXT": b"y"}
    with _zip(membros) as arquivo, pytest.raises(QuarentenaLeitura, match="membro_ambiguo"):
        ler_membro(arquivo, "tb_registro.txt", 1000)


def test_membro_le_bytes_dentro_do_limite() -> None:
    with _zip({"tb_registro.txt": b"abc"}) as arquivo:
        assert ler_membro(arquivo, "tb_registro.txt", 3) == b"abc"
