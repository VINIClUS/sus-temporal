import dataclasses
import struct
from importlib import metadata
from typing import Any

import dbfread
import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sustemporal.contracts import EstadoIntegridade, VerificacaoFidelidade
from sustemporal.ingest.dbc import descomprimir_dbc, ler_dbc, verificar_fidelidade
from sustemporal.ingest.dbf import COLUNA_DELETADO, QuarentenaLeitura, ler_dbf
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

CAMPOS = (CampoDbf("PA_CODUNI", "C", 7), CampoDbf("PA_QTDAPR", "N", 5))
REGISTROS = (("0012345", "5"), ("0000001", "0"), ("ÁÇ\xff", "012"), ("0000002", "1"))


def _dbf(**kwargs: Any) -> bytes:
    return escrever_dbf(CAMPOS, REGISTROS, **kwargs)


def _estado(dados: bytes) -> EstadoIntegridade:
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbc(dados)
    return erro.value.estado


@pytest.mark.parametrize("dicionario", [4, 5, 6])
def test_ler_dbc_equivale_a_ler_o_dbf_original(dicionario: int) -> None:
    dbf = _dbf(deletados={1}, byte_driver=0x58)
    resultado = ler_dbc(dbf_para_dbc(dbf, dicionario))
    assert resultado.leitura.tabela.equals(ler_dbf(dbf).tabela)
    assert resultado.leitura.n_deletados == 1
    assert resultado.leitura.cabecalho.byte_driver == 0x58
    assert resultado.metadados.dicionario == dicionario
    assert resultado.metadados.flag_literais == 0


def test_metadados_registram_bytes_pos_cabecalho_e_bibliotecas() -> None:
    dbc = bytearray(dbf_para_dbc(_dbf()))
    h = struct.unpack_from("<H", dbc, 8)[0]
    dbc[h : h + 4] = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    metadados = ler_dbc(bytes(dbc)).metadados
    assert metadados.bytes_pos_cabecalho_hex == "deadbeef"
    assert metadados.tam_cabecalho == h
    assert ("datasus-dbc", metadata.version("datasus-dbc")) in metadados.bibliotecas


def test_descomprimir_nao_reescreve_o_cabecalho() -> None:
    dbf = _dbf()
    assert descomprimir_dbc(dbf_para_dbc(dbf))[0] == dbf


@pytest.mark.parametrize("cortar", [1, 5, 30])
def test_dbc_truncado_vai_para_quarentena_truncado(cortar: int) -> None:
    dbc = dbf_para_dbc(_dbf())
    assert _estado(dbc[:-cortar]) is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_dbc_cortado_no_cabecalho_vai_para_quarentena_truncado() -> None:
    assert _estado(dbf_para_dbc(_dbf())[:50]) is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_dbf_truncado_dentro_de_dbc_valido_vai_para_quarentena_truncado() -> None:
    dbc = dbf_para_dbc(_dbf(truncar_bytes=4))
    assert _estado(dbc) is EstadoIntegridade.QUARENTENA_TRUNCADO


@pytest.mark.parametrize("dados", [b"", b"<!DOCTYPE html><html>erro 404</html>" * 4, b"\x03" * 9])
def test_conteudo_que_nao_e_dbc_vai_para_quarentena_conteudo_inesperado(dados: bytes) -> None:
    assert _estado(dados) is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO


@pytest.mark.parametrize(("posicao", "valor"), [(4, 2), (5, 3), (5, 7)])
def test_bytes_iniciais_dcl_invalidos_vao_para_quarentena(posicao: int, valor: int) -> None:
    dbc = bytearray(dbf_para_dbc(_dbf()))
    h = struct.unpack_from("<H", dbc, 8)[0]
    dbc[h + posicao] = valor
    assert _estado(bytes(dbc)) is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO


def test_cabecalho_sem_terminador_no_dbc_vai_para_quarentena_de_leiaute() -> None:
    dbc = bytearray(dbf_para_dbc(_dbf()))
    h = struct.unpack_from("<H", dbc, 8)[0]
    dbc[h - 1] = 0x00
    assert _estado(bytes(dbc)) is EstadoIntegridade.QUARENTENA_LEIAUTE


@pytest.mark.parametrize("modo", ["COMPLETA", "AMOSTRAL"])
def test_fidelidade_confirma_leitura_correta(modo: VerificacaoFidelidade) -> None:
    dbc = dbf_para_dbc(_dbf(deletados={0, 3}))
    relatorio = verificar_fidelidade(dbc, ler_dbc(dbc).leitura, modo, amostra=2)
    assert relatorio.verificado
    assert relatorio.fiel
    assert relatorio.registros_comparados == (4 if modo == "COMPLETA" else 2)
    nomes = {nome for nome, _ in relatorio.bibliotecas}
    assert {"datasus-dbc", "dbc-to-dbf", "dbfread"} <= nomes


def test_fidelidade_desligada_nao_afirma_fidelidade() -> None:
    dbc = dbf_para_dbc(_dbf())
    relatorio = verificar_fidelidade(dbc, ler_dbc(dbc).leitura, "DESLIGADA")
    assert not relatorio.verificado
    assert not relatorio.fiel


def _adulterar(tabela: pa.Table, coluna: str, linha: int, valor: object) -> pa.Table:
    valores = tabela.column(coluna).to_pylist()
    valores[linha] = valor
    indice = tabela.column_names.index(coluna)
    return tabela.set_column(indice, coluna, pa.array(valores, tabela.schema.field(coluna).type))


@pytest.mark.parametrize(
    ("coluna", "linha", "valor"),
    [("PA_CODUNI", 2, "0012346"), (COLUNA_DELETADO, 1, True), ("PA_QTDAPR", 3, "    2")],
)
def test_fidelidade_detecta_leitura_divergente(coluna: str, linha: int, valor: object) -> None:
    dbc = dbf_para_dbc(_dbf(deletados={0}))
    leitura = ler_dbc(dbc).leitura
    adulterada = dataclasses.replace(
        leitura, tabela=_adulterar(leitura.tabela, coluna, linha, valor)
    )
    relatorio = verificar_fidelidade(dbc, adulterada, "COMPLETA")
    assert relatorio.verificado
    assert not relatorio.fiel
    assert relatorio.divergencias


def test_fidelidade_detecta_linha_omitida() -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    omitida = dataclasses.replace(leitura, tabela=leitura.tabela.slice(0, 3))
    assert not verificar_fidelidade(dbc, omitida, "COMPLETA").fiel


@st.composite
def _entrada(draw: st.DrawFn) -> tuple[list[CampoDbf], bytes]:
    campos = [
        CampoDbf(f"C{i}", draw(st.sampled_from("CN")), draw(st.integers(1, 9)))
        for i in range(draw(st.integers(1, 4)))
    ]
    registros = [
        tuple(draw(st.binary(max_size=c.largura)) for c in campos)
        for _ in range(draw(st.integers(0, 20)))
    ]
    deletados = draw(st.sets(st.integers(0, len(registros) - 1))) if registros else set()
    dbf = escrever_dbf(campos, registros, deletados=deletados, com_eof=draw(st.booleans()))
    return campos, dbf_para_dbc(dbf, draw(st.sampled_from([4, 5, 6])))


@given(entrada=_entrada())
def test_propriedade_diferencial_contra_dbfread(
    entrada: tuple[list[CampoDbf], bytes], tmp_path_factory: pytest.TempPathFactory
) -> None:
    campos, dbc = entrada
    leitura = ler_dbc(dbc).leitura
    caminho = tmp_path_factory.mktemp("dbf") / "ref.dbf"
    caminho.write_bytes(descomprimir_dbc(dbc)[0])
    referencia = dbfread.DBF(str(caminho), raw=True, load=True)
    flags = leitura.tabela.column(COLUNA_DELETADO).to_pylist()
    for nome in (c.nome for c in campos):
        valores = [v.encode("latin-1") for v in leitura.tabela.column(nome).to_pylist()]
        assert [v for v, d in zip(valores, flags, strict=True) if not d] == [
            r[nome] for r in referencia.records
        ]
        assert [v for v, d in zip(valores, flags, strict=True) if d] == [
            r[nome] for r in referencia.deleted
        ]
    assert verificar_fidelidade(dbc, leitura).fiel
