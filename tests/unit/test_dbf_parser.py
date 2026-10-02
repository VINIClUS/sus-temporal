import struct
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sustemporal.contracts import EstadoIntegridade, LayoutSpec
from sustemporal.ingest.dbf import (
    COLUNA_DELETADO,
    COLUNA_INDICE,
    QuarentenaLeitura,
    conferir_leiaute,
    ler_cabecalho,
    ler_dbf,
    ler_dbf_arquivo,
)
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

CAMPOS = (
    CampoDbf("PA_CODUNI", "C", 7),
    CampoDbf("PA_QTDAPR", "N", 11),
    CampoDbf("PA_VALAPR", "N", 12, 2),
    CampoDbf("PA_DATA", "D", 8),
)
REGISTROS = (
    ("0012345", "5", "10.50", "20180131"),
    ("0000001", "0", "0.00", "20251231"),
    ("ÁÉ\xff\x00\x80", "012", "", ""),
)


def _dbf(**kwargs: Any) -> bytes:
    return escrever_dbf(CAMPOS, REGISTROS, **kwargs)


def _estado(dados: bytes) -> EstadoIntegridade:
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbf(dados)
    return erro.value.estado


def test_le_campos_como_texto_bruto_sem_aparar_nem_converter() -> None:
    tabela = ler_dbf(_dbf()).tabela
    assert tabela.column("PA_CODUNI").to_pylist()[:2] == ["0012345", "0000001"]
    assert tabela.column("PA_QTDAPR").to_pylist() == [
        "          5",
        "          0",
        "        012",
    ]
    assert tabela.column("PA_DATA").to_pylist()[2] == " " * 8


def test_bytes_nao_ascii_e_nulos_preservados_em_latin1_bijetivo() -> None:
    valor = ler_dbf(_dbf()).tabela.column("PA_CODUNI").to_pylist()[2]
    assert valor.encode("latin-1") == "ÁÉ\xff\x00\x80".encode("latin-1") + b"  "


def test_deletados_contados_e_preservados_com_indice_fisico() -> None:
    leitura = ler_dbf(_dbf(deletados={0, 2}))
    assert leitura.tabela.num_rows == 3
    assert leitura.n_deletados == 2
    assert leitura.tabela.column(COLUNA_DELETADO).to_pylist() == [True, False, True]
    assert leitura.tabela.column(COLUNA_INDICE).to_pylist() == [0, 1, 2]


def test_registra_byte_de_driver_e_cabecalho() -> None:
    leitura = ler_dbf(_dbf(byte_driver=0x58, com_eof=False))
    assert leitura.cabecalho.byte_driver == 0x58
    assert leitura.cabecalho.n_registros == 3
    assert [c.nome for c in leitura.cabecalho.campos] == [c.nome for c in CAMPOS]
    assert [c.inicio for c in leitura.cabecalho.campos] == [1, 8, 19, 31]
    assert leitura.tem_eof is False


def test_zero_registros_le_tabela_vazia_com_colunas() -> None:
    leitura = ler_dbf(escrever_dbf(CAMPOS, []))
    assert leitura.tabela.num_rows == 0
    assert leitura.tabela.column_names == [COLUNA_INDICE, COLUNA_DELETADO] + [
        c.nome for c in CAMPOS
    ]


@pytest.mark.parametrize("cortar", [2, 10, 60])
def test_truncado_vai_para_quarentena_truncado(cortar: int) -> None:
    assert _estado(_dbf(truncar_bytes=cortar)) is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_truncado_dentro_do_cabecalho_vai_para_quarentena_truncado() -> None:
    assert _estado(_dbf()[:70]) is EstadoIntegridade.QUARENTENA_TRUNCADO


def test_bytes_excedentes_vao_para_quarentena_de_leiaute() -> None:
    assert _estado(_dbf() + b"x") is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert _estado(_dbf(com_eof=False) + b"xy") is EstadoIntegridade.QUARENTENA_LEIAUTE
    assert _estado(_dbf(com_eof=False) + b"x") is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_tamanho_do_registro_incompativel_com_campos_vai_para_quarentena() -> None:
    dados = bytearray(_dbf())
    tam = struct.unpack_from("<H", dados, 10)[0]
    struct.pack_into("<H", dados, 10, tam + 1)
    assert _estado(bytes(dados)) is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_sem_terminador_de_descritores_vai_para_quarentena_de_leiaute() -> None:
    dados = bytearray(_dbf())
    h = struct.unpack_from("<H", dados, 8)[0]
    dados[h - 1] = 0x00
    assert _estado(bytes(dados)) is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_flag_de_delecao_invalida_vai_para_quarentena_de_leiaute() -> None:
    dados = bytearray(_dbf())
    h = struct.unpack_from("<H", dados, 8)[0]
    dados[h] = ord("X")
    assert _estado(bytes(dados)) is EstadoIntegridade.QUARENTENA_LEIAUTE


def test_nomes_de_campo_repetidos_vao_para_quarentena_de_leiaute() -> None:
    dados = escrever_dbf([CampoDbf("A", "C", 1), CampoDbf("A", "C", 1)], [("x", "y")])
    assert _estado(dados) is EstadoIntegridade.QUARENTENA_LEIAUTE


@pytest.mark.parametrize("dados", [b"", b"<html><body>erro</body></html>", b"\x03" * 31])
def test_conteudo_que_nao_e_dbf_vai_para_quarentena(dados: bytes) -> None:
    assert _estado(dados) in {
        EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO,
        EstadoIntegridade.QUARENTENA_TRUNCADO,
    }
    assert _estado(b"<html><body>erro</body></html>" * 3) is (
        EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    )


def test_ler_cabecalho_isolado() -> None:
    cabecalho = ler_cabecalho(_dbf())
    assert cabecalho.tam_registro == 1 + 7 + 11 + 12 + 8
    assert cabecalho.campos[2].decimais == 2


def test_arquivo_por_memmap_igual_a_bytes(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbf"
    caminho.write_bytes(_dbf(deletados={1}))
    assert ler_dbf_arquivo(caminho, tamanho_bloco=2).tabela.equals(
        ler_dbf(_dbf(deletados={1})).tabela
    )


def test_arquivo_truncado_por_memmap_vai_para_quarentena(tmp_path: Path) -> None:
    caminho = tmp_path / "x.dbf"
    caminho.write_bytes(_dbf(truncar_bytes=5))
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbf_arquivo(caminho)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_TRUNCADO


def _leiaute(campos: tuple[CampoDbf, ...]) -> LayoutSpec:
    return LayoutSpec.model_validate(
        {
            "layout_id": "teste.v1",
            "fonte": "SIA_PA",
            "versao": "1",
            "codificacao": "latin-1",
            "formato": "DBF",
            "proveniencia": "INFERIDA",
            "campos": [
                {
                    "nome_fisico": c.nome,
                    "tipo_fisico": c.tipo,
                    "largura": c.largura,
                    "decimais": c.decimais,
                    "nome_canonico": c.nome.lower(),
                    "tipo_canonico": "TEXTO",
                    "papel": "BRUTO",
                }
                for c in campos
            ],
        }
    )


def test_leiaute_coincidente_e_aceito() -> None:
    conferir_leiaute(ler_cabecalho(_dbf()), _leiaute(CAMPOS))


@pytest.mark.parametrize(
    "campos",
    [
        CAMPOS[:3],
        (*CAMPOS, CampoDbf("EXTRA", "C", 1)),
        (CAMPOS[1], CAMPOS[0], *CAMPOS[2:]),
        (CampoDbf("PA_CODUNI", "C", 8), *CAMPOS[1:]),
        (CampoDbf("PA_CODUNI", "N", 7), *CAMPOS[1:]),
        (CAMPOS[0], CAMPOS[1], CampoDbf("PA_VALAPR", "N", 12, 1), CAMPOS[3]),
    ],
)
def test_leiaute_divergente_vai_para_quarentena_de_leiaute(campos: tuple[CampoDbf, ...]) -> None:
    with pytest.raises(QuarentenaLeitura) as erro:
        conferir_leiaute(ler_cabecalho(_dbf()), _leiaute(campos))
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_LEIAUTE


@st.composite
def _dbf_aleatorio(draw: st.DrawFn) -> tuple[list[CampoDbf], list[tuple[bytes, ...]], set[int]]:
    campos = [
        CampoDbf(f"C{i}", "C", draw(st.integers(1, 12))) for i in range(draw(st.integers(1, 5)))
    ]
    registros = [
        tuple(draw(st.binary(max_size=c.largura)) for c in campos)
        for _ in range(draw(st.integers(0, 25)))
    ]
    deletados = draw(st.sets(st.integers(0, len(registros) - 1))) if registros else set()
    return campos, registros, deletados


@given(entrada=_dbf_aleatorio(), bloco=st.integers(1, 7), eof=st.booleans())
def test_propriedade_blocos_e_bytes_recuperaveis(
    entrada: tuple[list[CampoDbf], list[tuple[bytes, ...]], set[int]], bloco: int, eof: bool
) -> None:
    campos, registros, deletados = entrada
    leitura = ler_dbf(
        escrever_dbf(campos, registros, deletados=deletados, com_eof=eof), tamanho_bloco=bloco
    )
    assert leitura.n_deletados == len(deletados)
    for campo_dbf in campos:
        valores = leitura.tabela.column(campo_dbf.nome).to_pylist()
        esperados = [r[campos.index(campo_dbf)].ljust(campo_dbf.largura) for r in registros]
        assert [v.encode("latin-1") for v in valores] == esperados


def test_campo_com_nome_de_coluna_interna_vai_para_quarentena_de_leiaute() -> None:
    dados = bytearray(escrever_dbf([CampoDbf("X", "C", 1)], [("a",)]))
    dados[32:43] = COLUNA_DELETADO.encode("ascii").ljust(11, b"\x00")
    assert _estado(bytes(dados)) is EstadoIntegridade.QUARENTENA_LEIAUTE
