"""Parser DBF dBASE III estrito e vetorizado (ADR 0002).

Campos saem como texto bruto decodificado em latin-1 (bijetivo: ``valor.encode("latin-1")``
devolve os bytes originais), sem aparar nem converter. Registros deletados ficam na tabela com
o marcador e o índice físico. Qualquer incoerência física vira ``QuarentenaLeitura``.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray

from sustemporal.contracts import EstadoIntegridade, FormatoLeiaute
from sustemporal.errors import FalhaOperacionalErro

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import LayoutSpec

logger = logging.getLogger(__name__)

COLUNA_INDICE = "_indice_fisico"
COLUNA_DELETADO = "_deletado"
TAMANHO_BLOCO_PADRAO = 100_000
VERSOES_DBASE = frozenset({0x03, 0x83})
_TAM_PREFIXO = 32
_TAM_DESCRITOR = 32
_TERMINADOR = 0x0D
_EOF = 0x1A
_ATIVO = 0x20
_DELETADO = 0x2A

Bytes = NDArray[np.uint8]


class QuarentenaLeitura(FalhaOperacionalErro):
    """Arquivo que não pode ser lido com segurança; nunca vira conjunto vazio."""

    def __init__(self, estado: EstadoIntegridade, motivo: str) -> None:
        super().__init__(f"quarentena estado={estado} motivo={motivo}")
        self.estado = estado
        self.motivo = motivo


@dataclass(frozen=True)
class DescritorCampo:
    nome: str
    tipo: str
    largura: int
    decimais: int
    inicio: int


@dataclass(frozen=True)
class CabecalhoDbf:
    versao: int
    data_atualizacao: bytes
    n_registros: int
    tam_cabecalho: int
    tam_registro: int
    byte_driver: int
    campos: tuple[DescritorCampo, ...]


@dataclass(frozen=True)
class LeituraDbf:
    cabecalho: CabecalhoDbf
    tabela: pa.Table
    n_deletados: int
    tem_eof: bool
    tamanho_bytes: int


def _leiaute(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_LEIAUTE, motivo)


def _conferir_prefixo(dados: Bytes) -> None:
    if dados.size == 0 or int(dados[0]) not in VERSOES_DBASE:
        primeiro = int(dados[0]) if dados.size else None
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, f"versao_dbf_invalida byte={primeiro}"
        )
    if dados.size < _TAM_PREFIXO:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO, f"cabecalho_curto tamanho={dados.size}"
        )


def _descritor(bruto: bytes, inicio: int) -> DescritorCampo:
    nome_bruto = bruto[:11].split(b"\x00", 1)[0]
    if not nome_bruto or not all(0x21 <= b <= 0x7E for b in nome_bruto):
        raise _leiaute(f"nome_de_campo_invalido nome={nome_bruto!r}")
    tipo, largura, decimais = chr(bruto[11]), bruto[16], bruto[17]
    if not tipo.isascii() or not tipo.isalpha() or largura == 0:
        raise _leiaute(f"descritor_invalido nome={nome_bruto!r} tipo={tipo!r} largura={largura}")
    return DescritorCampo(nome_bruto.decode("ascii"), tipo, largura, decimais, inicio)


def _descritores(cabecalho: bytes) -> tuple[DescritorCampo, ...]:
    campos: list[DescritorCampo] = []
    posicao, inicio = _TAM_PREFIXO, 1
    while posicao + _TAM_DESCRITOR < len(cabecalho) and cabecalho[posicao] != _TERMINADOR:
        campo = _descritor(cabecalho[posicao : posicao + _TAM_DESCRITOR], inicio)
        campos.append(campo)
        posicao += _TAM_DESCRITOR
        inicio += campo.largura
    if posicao != len(cabecalho) - 1 or cabecalho[posicao] != _TERMINADOR:
        raise _leiaute(f"terminador_ausente posicao={posicao} cabecalho={len(cabecalho)}")
    nomes = [campo.nome for campo in campos]
    if not campos or len(set(nomes)) != len(nomes):
        raise _leiaute(f"campos_vazios_ou_repetidos campos={nomes}")
    return tuple(campos)


def _ler_cabecalho(dados: Bytes) -> CabecalhoDbf:
    _conferir_prefixo(dados)
    prefixo = dados[:_TAM_PREFIXO].tobytes()
    n_registros, tam_cabecalho, tam_registro = struct.unpack_from("<IHH", prefixo, 4)
    if tam_cabecalho < _TAM_PREFIXO + 1:
        raise _leiaute(f"tamanho_cabecalho_invalido cabecalho={tam_cabecalho}")
    if dados.size < tam_cabecalho:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO,
            f"cabecalho_incompleto tamanho={dados.size} cabecalho={tam_cabecalho}",
        )
    campos = _descritores(dados[:tam_cabecalho].tobytes())
    soma = 1 + sum(campo.largura for campo in campos)
    if soma != tam_registro:
        raise _leiaute(f"tamanho_registro_incoerente registro={tam_registro} campos={soma}")
    return CabecalhoDbf(
        versao=prefixo[0],
        data_atualizacao=prefixo[1:4],
        n_registros=n_registros,
        tam_cabecalho=tam_cabecalho,
        tam_registro=tam_registro,
        byte_driver=prefixo[29],
        campos=campos,
    )


def ler_cabecalho(dados: bytes) -> CabecalhoDbf:
    """Lê cabeçalho e descritores; recusa estrutura incoerente com quarentena."""
    return _ler_cabecalho(np.frombuffer(dados, dtype=np.uint8))


def _conferir_tamanho(dados: Bytes, cabecalho: CabecalhoDbf) -> bool:
    esperado = cabecalho.tam_cabecalho + cabecalho.n_registros * cabecalho.tam_registro
    if dados.size < esperado:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO,
            f"registros_incompletos tamanho={dados.size} esperado={esperado}",
        )
    tem_eof = dados.size == esperado + 1 and int(dados[-1]) == _EOF
    if dados.size != esperado and not tem_eof:
        raise _leiaute(f"bytes_excedentes tamanho={dados.size} esperado={esperado}")
    return tem_eof


def _texto_latin1(bloco: Bytes) -> pa.Array:
    """Transcodifica latin-1 → UTF-8 por vetores; cada byte vira exatamente um caractere."""
    linhas, largura = bloco.shape
    if linhas == 0:
        return pa.array([], type=pa.large_string())
    plano = np.ascontiguousarray(bloco).reshape(-1)
    alto = plano >= 0x80
    tamanhos = 1 + alto.astype(np.int64)
    fim = np.cumsum(tamanhos)
    inicio = fim - tamanhos
    saida = np.empty(int(fim[-1]), dtype=np.uint8)
    saida[inicio] = np.where(alto, 0xC0 | (plano >> 6), plano)
    saida[inicio[alto] + 1] = 0x80 | (plano[alto] & 0x3F)
    deslocamentos = np.zeros(linhas + 1, dtype=np.int64)
    np.cumsum(tamanhos.reshape(linhas, largura).sum(axis=1), out=deslocamentos[1:])
    return pa.LargeStringArray.from_buffers(
        linhas, pa.py_buffer(deslocamentos), pa.py_buffer(saida)
    )


def _ler_bloco(bloco: Bytes, primeiro: int, campos: tuple[DescritorCampo, ...]) -> list[pa.Array]:
    flags = bloco[:, 0]
    invalidas = np.flatnonzero((flags != _ATIVO) & (flags != _DELETADO))
    if invalidas.size:
        posicao = primeiro + int(invalidas[0])
        raise _leiaute(f"flag_delecao_invalida registro={posicao} byte={int(flags[invalidas[0]])}")
    indices = np.arange(primeiro, primeiro + bloco.shape[0], dtype=np.int64)
    colunas = [pa.array(indices), pa.array(flags == _DELETADO)]
    colunas += [_texto_latin1(bloco[:, c.inicio : c.inicio + c.largura]) for c in campos]
    return colunas


def _ler(dados: Bytes, tamanho_bloco: int) -> LeituraDbf:
    if tamanho_bloco < 1:
        raise ValueError(f"tamanho_bloco_invalido tamanho_bloco={tamanho_bloco}")
    cabecalho = _ler_cabecalho(dados)
    tem_eof = _conferir_tamanho(dados, cabecalho)
    n, r, h = cabecalho.n_registros, cabecalho.tam_registro, cabecalho.tam_cabecalho
    registros = dados[h : h + n * r].reshape(n, r)
    nomes = [COLUNA_INDICE, COLUNA_DELETADO, *(c.nome for c in cabecalho.campos)]
    tipos = [pa.int64(), pa.bool_(), *(pa.large_string() for _ in cabecalho.campos)]
    pedacos: list[list[pa.Array]] = [[] for _ in nomes]
    for primeiro in range(0, n, tamanho_bloco):
        bloco = registros[primeiro : primeiro + tamanho_bloco]
        for destino, coluna in zip(
            pedacos, _ler_bloco(bloco, primeiro, cabecalho.campos), strict=True
        ):
            destino.append(coluna)
    tabela = pa.Table.from_arrays(
        [pa.chunked_array(p, type=t) for p, t in zip(pedacos, tipos, strict=True)], names=nomes
    )
    n_deletados = pc.sum(tabela.column(COLUNA_DELETADO)).as_py() or 0
    logger.info("dbf_lido registros=%s deletados=%s eof=%s", n, n_deletados, tem_eof)
    return LeituraDbf(cabecalho, tabela, n_deletados, tem_eof, int(dados.size))


def ler_dbf(dados: bytes, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbf:
    """Lê todos os registros, inclusive deletados, como texto bruto latin-1."""
    return _ler(np.frombuffer(dados, dtype=np.uint8), tamanho_bloco)


def ler_dbf_arquivo(caminho: Path, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbf:
    """Como `ler_dbf`, mapeando o arquivo em memória (memmap) e lendo em blocos."""
    if caminho.stat().st_size == 0:
        return ler_dbf(b"", tamanho_bloco=tamanho_bloco)
    mapa: Bytes = np.memmap(caminho, dtype=np.uint8, mode="r")
    return _ler(mapa, tamanho_bloco)


def conferir_leiaute(cabecalho: CabecalhoDbf, layout: LayoutSpec) -> None:
    """Descritores devem coincidir com o leiaute (nome, tipo, largura, decimais, ordem)."""
    if layout.formato is not FormatoLeiaute.DBF:
        raise _leiaute(f"leiaute_nao_dbf layout={layout.layout_id} formato={layout.formato}")
    lidos = [(c.nome, c.tipo, c.largura, c.decimais) for c in cabecalho.campos]
    esperados = [(c.nome_fisico, c.tipo_fisico, c.largura, c.decimais) for c in layout.campos]
    if lidos == esperados:
        return
    divergente = next(
        (i for i, (a, b) in enumerate(zip(lidos, esperados, strict=False)) if a != b),
        min(len(lidos), len(esperados)),
    )
    raise _leiaute(
        f"descritores_divergentes layout={layout.layout_id} posicao={divergente} "
        f"lidos={len(lidos)} esperados={len(esperados)}"
    )
