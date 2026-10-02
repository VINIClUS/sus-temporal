import struct
from pathlib import Path
from typing import Any

import dbfread
import pytest
from datasus_dbc import decompress_bytes
from dbctodbf import DBCDecompress
from hypothesis import given
from hypothesis import strategies as st

from tests.fixtures.dbc_encoder import comprimir_dcl_literais, dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

CAMPOS = (
    CampoDbf("PA_CODUNI", "C", 7),
    CampoDbf("PA_QTDAPR", "N", 11),
    CampoDbf("PA_VALAPR", "N", 12, 2),
    CampoDbf("PA_DATA", "D", 8),
    CampoDbf("PA_FLAG", "L", 1),
)
REGISTROS = (
    ("0012345", "5", "10.50", "20180131", "T"),
    ("0000001", "0", "0.00", "20251231", "F"),
    ("ÁÉÇ\xff\x80", "12", "1234.56", "", "?"),
)


def _dbf_exemplo(**kwargs: Any) -> bytes:
    return escrever_dbf(CAMPOS, REGISTROS, **kwargs)


def _ida_e_volta(dbf: bytes, dicionario: int = 6) -> tuple[bytes, bytes]:
    dbc = dbf_para_dbc(dbf, dicionario)
    return bytes(decompress_bytes(dbc)), bytes(DBCDecompress().decompress(dbc))


def test_cabecalho_dbf_registra_contagens_tamanhos_e_byte_de_driver() -> None:
    dbf = _dbf_exemplo(byte_driver=0x57, deletados={1})
    assert dbf[0] == 0x03
    assert dbf[1:4] == bytes([126, 1, 1])
    nrec, cabecalho, registro = struct.unpack("<IHH", dbf[4:12])
    assert nrec == 3
    assert cabecalho == 32 + 32 * len(CAMPOS) + 1
    assert registro == 1 + sum(c.largura for c in CAMPOS)
    assert dbf[29] == 0x57
    assert dbf[cabecalho - 1] == 0x0D
    assert len(dbf) == cabecalho + nrec * registro + 1
    assert dbf[-1] == 0x1A
    assert dbf[cabecalho + registro] == ord("*")
    assert dbf[cabecalho] == ord(" ")


def test_descritor_de_campo_tem_nome_tipo_largura_e_decimais() -> None:
    dbf = _dbf_exemplo()
    descritor = dbf[32 + 32 * 2 : 32 + 32 * 3]
    assert descritor[:11] == b"PA_VALAPR\x00\x00"
    assert descritor[11:12] == b"N"
    assert descritor[16] == 12
    assert descritor[17] == 2


def test_sem_eof_e_truncado_alteram_o_tamanho_fisico() -> None:
    completo = _dbf_exemplo()
    assert len(_dbf_exemplo(com_eof=False)) == len(completo) - 1
    assert _dbf_exemplo(truncar_bytes=7) == completo[:-7]


def test_valores_preenchidos_conforme_o_tipo_e_zeros_preservados() -> None:
    dbf = _dbf_exemplo(com_eof=False)
    cabecalho = struct.unpack("<H", dbf[8:10])[0]
    primeiro = dbf[cabecalho + 1 : cabecalho + 1 + 7 + 11 + 12]
    assert primeiro == b"0012345" + b"5".rjust(11) + b"10.50".rjust(12)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        (CampoDbf("NOME_LONGO_X", "C", 3), "a"),
        (CampoDbf("A", "X", 3), "a"),
        (CampoDbf("A", "C", 3), "abcd"),
        (CampoDbf("A", "D", 7), "2018010"),
        (CampoDbf("A", "C", 2), "ŋ"),
    ],
)
def test_rejeita_campo_ou_valor_invalido(campo: CampoDbf, valor: str) -> None:
    with pytest.raises(ValueError, match="="):
        escrever_dbf([campo], [(valor,)])


def test_dbfread_le_registros_e_flags_de_delecao(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbf"
    caminho.write_bytes(_dbf_exemplo(deletados={0, 2}))
    tabela = dbfread.DBF(str(caminho), encoding="latin-1", raw=True, load=True)
    assert [r["PA_CODUNI"] for r in tabela.records] == [b"0000001"]
    assert [r["PA_CODUNI"] for r in tabela.deleted] == [b"0012345", "ÁÉÇ\xff\x80".encode("latin-1")]


@pytest.mark.parametrize("dicionario", [4, 5, 6])
@pytest.mark.parametrize("com_eof", [True, False])
def test_ida_e_volta_dbf_dbc_dbf_identica_nos_dois_decodificadores(
    dicionario: int, com_eof: bool
) -> None:
    dbf = _dbf_exemplo(deletados={1}, com_eof=com_eof, byte_driver=0x03)
    rust, python = _ida_e_volta(dbf, dicionario)
    assert rust == dbf
    assert python == dbf


def test_ida_e_volta_com_zero_registros() -> None:
    dbf = escrever_dbf(CAMPOS, [])
    assert struct.unpack("<I", dbf[4:8])[0] == 0
    assert _ida_e_volta(dbf) == (dbf, dbf)


def test_dbc_preserva_cabecalho_e_crc_zerado() -> None:
    dbf = _dbf_exemplo()
    cabecalho = struct.unpack("<H", dbf[8:10])[0]
    dbc = dbf_para_dbc(dbf, 5)
    assert dbc[:cabecalho] == dbf[:cabecalho]
    assert dbc[cabecalho : cabecalho + 4] == bytes(4)
    assert dbc[cabecalho + 4 : cabecalho + 6] == bytes([0, 5])


def test_fluxo_dcl_de_dados_vazios_e_so_o_codigo_de_fim() -> None:
    fluxo = comprimir_dcl_literais(b"", 4)
    assert fluxo[:2] == bytes([0, 4])
    assert len(fluxo) == 4


@pytest.mark.parametrize("dicionario", [3, 7, 0])
def test_rejeita_dicionario_fora_de_4_a_6(dicionario: int) -> None:
    with pytest.raises(ValueError, match="dicionario="):
        comprimir_dcl_literais(b"a", dicionario)


_TIPOS = st.sampled_from("CNDL")
_BYTES_LATIN1 = st.binary(max_size=12)


@st.composite
def _campos(draw: st.DrawFn) -> list[CampoDbf]:
    n = draw(st.integers(1, 5))
    campos = []
    for i in range(n):
        tipo = draw(_TIPOS)
        largura = {"D": 8, "L": 1}.get(tipo) or draw(st.integers(1, 20))
        decimais = draw(st.integers(0, max(0, largura - 2))) if tipo == "N" else 0
        campos.append(CampoDbf(f"C{i}", tipo, largura, decimais))
    return campos


@st.composite
def _dbf_aleatorio(draw: st.DrawFn) -> bytes:
    campos = draw(_campos())
    registros = [
        tuple(draw(st.binary(min_size=0, max_size=c.largura)) for c in campos)
        for _ in range(draw(st.integers(0, 15)))
    ]
    deletados = draw(st.sets(st.integers(0, max(0, len(registros) - 1))))
    return escrever_dbf(
        campos,
        registros,
        deletados=deletados if registros else (),
        byte_driver=draw(st.integers(0, 255)),
        com_eof=draw(st.booleans()),
    )


@given(dbf=_dbf_aleatorio(), dicionario=st.sampled_from([4, 5, 6]))
def test_propriedade_ida_e_volta_identica_byte_a_byte(dbf: bytes, dicionario: int) -> None:
    rust, python = _ida_e_volta(dbf, dicionario)
    assert rust == dbf
    assert python == dbf


@given(dados=_BYTES_LATIN1, dicionario=st.sampled_from([4, 5, 6]))
def test_propriedade_fluxo_dcl_tem_nove_bits_por_literal(dados: bytes, dicionario: int) -> None:
    fluxo = comprimir_dcl_literais(dados, dicionario)
    bits = 9 * len(dados) + 1 + 7 + 8
    assert len(fluxo) == 2 + (bits + 7) // 8
