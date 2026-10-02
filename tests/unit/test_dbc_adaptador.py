import dataclasses
import re
import struct
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

import dbfread
import pyarrow as pa
import pytest
from dbctodbf import DBCDecompress
from hypothesis import given
from hypothesis import strategies as st

from sustemporal.contracts import EstadoIntegridade, VerificacaoFidelidade
from sustemporal.ingest import dbc as dbc_mod
from sustemporal.ingest.dbc import (
    descomprimir_dbc,
    ler_dbc,
    ler_dbc_arquivo,
    verificar_fidelidade,
)
from sustemporal.ingest.dbf import (
    COLUNA_DELETADO,
    COLUNA_INDICE,
    ArquivoAusente,
    QuarentenaLeitura,
    ler_dbf,
)
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
    [
        ("PA_CODUNI", 2, "0012346"),
        (COLUNA_DELETADO, 1, True),
        ("PA_QTDAPR", 3, "    2"),
        ("PA_CODUNI", 0, "9999999"),
    ],
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
def _entrada(draw: st.DrawFn) -> tuple[list[CampoDbf], bytes, bytes, set[int]]:
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
    return campos, dbf, dbf_para_dbc(dbf, draw(st.sampled_from([4, 5, 6]))), deletados


@given(entrada=_entrada())
def test_propriedade_diferencial_contra_dbfread(
    entrada: tuple[list[CampoDbf], bytes, bytes, set[int]],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    campos, dbf_original, dbc, deletados = entrada
    leitura = ler_dbc(dbc).leitura
    caminho = tmp_path_factory.mktemp("dbf") / "ref.dbf"
    caminho.write_bytes(dbf_original)
    referencia = dbfread.DBF(str(caminho), raw=True, load=True)
    flags = leitura.tabela.column(COLUNA_DELETADO).to_pylist()
    assert flags == [i in deletados for i in range(len(flags))]
    assert len(flags) == len(referencia.records) + len(referencia.deleted)
    for nome in (c.nome for c in campos):
        valores = [v.encode("latin-1") for v in leitura.tabela.column(nome).to_pylist()]
        assert [v for v, d in zip(valores, flags, strict=True) if not d] == [
            r[nome] for r in referencia.records
        ]
        assert [v for v, d in zip(valores, flags, strict=True) if d] == [
            r[nome] for r in referencia.deleted
        ]
    assert verificar_fidelidade(dbc, leitura).fiel


class _DescompressorAdulterado:
    def __init__(self, alterar: Callable[[bytes], bytes]) -> None:
        self._alterar = alterar

    def decompress(self, dados: bytes) -> bytes:
        return self._alterar(bytes(DBCDecompress().decompress(dados)))


def _falhar(dados: bytes) -> bytes:
    raise EOFError("Not enough input data")


@pytest.mark.parametrize(
    "alterar",
    [
        lambda b: b[:-1] + bytes([b[-1] ^ 1]),
        lambda b: b + b"\x00",
        lambda b: b[:120] + b"Z" + b[121:],
    ],
)
def test_fidelidade_detecta_bytes_divergentes_do_leitor_independente(
    alterar: Callable[[bytes], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    dbc = dbf_para_dbc(_dbf(com_eof=False))
    leitura = ler_dbc(dbc).leitura
    monkeypatch.setattr(dbc_mod, "DBCDecompress", lambda: _DescompressorAdulterado(alterar))
    relatorio = verificar_fidelidade(dbc, leitura, "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("bytes_divergentes") for d in relatorio.divergencias)


def test_fidelidade_com_leitor_independente_falhando_nao_compara_registros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    monkeypatch.setattr(dbc_mod, "DBCDecompress", lambda: _DescompressorAdulterado(_falhar))
    relatorio = verificar_fidelidade(dbc, leitura, "COMPLETA")
    assert not relatorio.fiel
    assert relatorio.registros_comparados == 0
    assert any(d.startswith("dbctodbf_falhou") for d in relatorio.divergencias)


def test_fidelidade_recusa_leitura_de_outro_arquivo_com_mesmos_registros() -> None:
    dbc = dbf_para_dbc(_dbf(byte_driver=0x58))
    outra = ler_dbc(dbf_para_dbc(_dbf(byte_driver=0x03, data=(2019, 5, 6)))).leitura
    relatorio = verificar_fidelidade(dbc, outra, "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("cabecalho_divergente") for d in relatorio.divergencias)


@pytest.mark.parametrize("indices", [[0, 0, 2, 3], [1, 2, 3, 4], [0, 2, 1, 3]])
def test_fidelidade_detecta_indice_fisico_corrompido(indices: list[int]) -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    tabela = leitura.tabela.set_column(0, COLUNA_INDICE, pa.array(indices, pa.int64()))
    relatorio = verificar_fidelidade(dbc, dataclasses.replace(leitura, tabela=tabela), "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("indices_fisicos_divergentes") for d in relatorio.divergencias)


@pytest.mark.parametrize("alterar", [lambda b: b[:0], lambda b: b[:40], lambda b: b[:-7]])
def test_fidelidade_com_saida_independente_malformada_nao_levanta(
    alterar: Callable[[bytes], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    dbc = dbf_para_dbc(_dbf(com_eof=False))
    leitura = ler_dbc(dbc).leitura
    monkeypatch.setattr(dbc_mod, "DBCDecompress", lambda: _DescompressorAdulterado(alterar))
    relatorio = verificar_fidelidade(dbc, leitura, "COMPLETA")
    assert relatorio.verificado
    assert not relatorio.fiel
    assert relatorio.registros_comparados == 0


@pytest.mark.parametrize(
    "alterar",
    [
        {"tipo": "C"},
        {"decimais": 3},
        {"largura": 6},
    ],
)
def test_fidelidade_detecta_descritor_de_campo_divergente(alterar: dict[str, Any]) -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    campos = list(leitura.cabecalho.campos)
    campos[1] = dataclasses.replace(campos[1], **alterar)
    cabecalho = dataclasses.replace(leitura.cabecalho, campos=tuple(campos))
    relatorio = verificar_fidelidade(dbc, dataclasses.replace(leitura, cabecalho=cabecalho))
    assert not relatorio.fiel
    assert "campos_divergentes" in relatorio.divergencias


@pytest.mark.parametrize("n_deletados", [0, 2, 5])
def test_fidelidade_detecta_contagem_de_deletados_informada_errada(n_deletados: int) -> None:
    dbc = dbf_para_dbc(_dbf(deletados={1}))
    leitura = dataclasses.replace(ler_dbc(dbc).leitura, n_deletados=n_deletados)
    relatorio = verificar_fidelidade(dbc, leitura, "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("contagens_divergentes") for d in relatorio.divergencias)


def test_fidelidade_detecta_flags_de_delecao_trocados_entre_registros_identicos() -> None:
    dbf = escrever_dbf(CAMPOS, [("0000001", "1"), ("0000001", "1")], deletados={0})
    dbc = dbf_para_dbc(dbf)
    leitura = ler_dbc(dbc).leitura
    tabela = _adulterar(
        _adulterar(leitura.tabela, COLUNA_DELETADO, 0, False), COLUNA_DELETADO, 1, True
    )
    relatorio = verificar_fidelidade(dbc, dataclasses.replace(leitura, tabela=tabela), "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("flags_delecao_divergentes") for d in relatorio.divergencias)


@pytest.mark.parametrize(
    "alterar",
    [{"versao": 0x83}, {"tem_eof": False}],
)
def test_fidelidade_compara_versao_e_eof_com_os_bytes_independentes(
    alterar: dict[str, Any],
) -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    if "versao" in alterar:
        cabecalho = dataclasses.replace(leitura.cabecalho, versao=alterar["versao"])
        leitura = dataclasses.replace(leitura, cabecalho=cabecalho)
    else:
        leitura = dataclasses.replace(leitura, tem_eof=alterar["tem_eof"])
    relatorio = verificar_fidelidade(dbc, leitura, "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("cabecalho_divergente") for d in relatorio.divergencias)


def _sufixos() -> list[Callable[[bytes], bytes]]:
    return [lambda d: d + b"\x00", lambda d: d + b"\x00" * 1000, lambda d: d + d]


@pytest.mark.parametrize("sufixo", _sufixos())
def test_bytes_apos_o_fim_dcl_vao_para_quarentena(sufixo: Callable[[bytes], bytes]) -> None:
    dbc = sufixo(dbf_para_dbc(_dbf()))
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbc(dbc)
    assert erro.value.estado is EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO
    assert erro.value.motivo.startswith("bytes_apos_fim_dcl")


@pytest.mark.parametrize("sufixo", _sufixos())
def test_fidelidade_detecta_bytes_apos_o_fim_dcl(sufixo: Callable[[bytes], bytes]) -> None:
    dbc = dbf_para_dbc(_dbf())
    leitura = ler_dbc(dbc).leitura
    relatorio = verificar_fidelidade(sufixo(dbc), leitura, "COMPLETA")
    assert not relatorio.fiel
    assert any(d.startswith("bytes_apos_fim_dcl") for d in relatorio.divergencias)


def test_ler_dbc_arquivo_equivale_a_ler_em_memoria(tmp_path: Path) -> None:
    dbc = dbf_para_dbc(_dbf(deletados={2}, byte_driver=0x58))
    caminho = tmp_path / "PASP1801.dbc"
    caminho.write_bytes(dbc)
    temporario = tmp_path / "tmp"
    temporario.mkdir()
    por_arquivo = ler_dbc_arquivo(caminho, dir_temporario=temporario, tamanho_bloco=2)
    em_memoria = ler_dbc(dbc)
    assert por_arquivo.leitura.tabela.equals(em_memoria.leitura.tabela)
    assert por_arquivo.leitura.cabecalho == em_memoria.leitura.cabecalho
    assert por_arquivo.metadados == em_memoria.metadados
    assert list(temporario.iterdir()) == []


@pytest.mark.parametrize(
    ("alterar", "estado"),
    [
        (lambda d: d[:-3], EstadoIntegridade.QUARENTENA_TRUNCADO),
        (lambda d: d[:50], EstadoIntegridade.QUARENTENA_TRUNCADO),
        (lambda d: d + b"\x00", EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO),
        (lambda d: b"<html>" + d, EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO),
    ],
)
def test_ler_dbc_arquivo_vai_para_quarentena(
    alterar: Callable[[bytes], bytes], estado: EstadoIntegridade, tmp_path: Path
) -> None:
    caminho = tmp_path / "x.dbc"
    caminho.write_bytes(alterar(dbf_para_dbc(_dbf())))
    temporario = tmp_path / "tmp"
    temporario.mkdir()
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbc_arquivo(caminho, dir_temporario=temporario)
    assert erro.value.estado is estado
    assert list(temporario.iterdir()) == []


def test_dbc_ausente_nunca_vira_conjunto_vazio(tmp_path: Path) -> None:
    with pytest.raises(ArquivoAusente) as erro:
        ler_dbc_arquivo(tmp_path / "nao_existe.dbc")
    assert erro.value.motivo.startswith("arquivo_ausente")


def test_metadados_registram_versoes_de_numpy_e_pyarrow() -> None:
    nomes = {nome for nome, _ in ler_dbc(dbf_para_dbc(_dbf())).metadados.bibliotecas}
    assert {"datasus-dbc", "numpy", "pyarrow", "sus-temporal"} <= nomes


_MOTIVO = re.compile(r"^[a-z_]+( [a-z_]+=[^\s]+)*$")


@pytest.mark.parametrize(
    "dados",
    [
        lambda d: d[:-1],
        lambda d: d[:50],
        lambda d: b"<html>" + d,
        lambda d: d + b"\x00",
    ],
)
def test_motivos_de_quarentena_em_chave_valor_sem_espacos(dados: Callable[[bytes], bytes]) -> None:
    with pytest.raises(QuarentenaLeitura) as erro:
        ler_dbc(dados(dbf_para_dbc(_dbf())))
    assert _MOTIVO.fullmatch(erro.value.motivo), erro.value.motivo
