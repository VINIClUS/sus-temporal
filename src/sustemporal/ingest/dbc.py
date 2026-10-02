"""Descompressão DBC (datasus-dbc) e verificação independente de fidelidade (ADR 0002).

A produção usa o datasus-dbc e o parser próprio de `sustemporal.ingest.dbf`. A verificação
usa uma cadeia sem código em comum: dbc-to-dbf (Python puro) para os bytes e dbfread para os
registros. O dbc-to-dbf reescreve o último byte do cabeçalho com 0x0D; esse byte é comparado à
parte, porque o parser próprio já exige o terminador no arquivo original.
"""

from __future__ import annotations

import logging
import struct
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from datasus_dbc import decompress_bytes
from dbctodbf import DBCDecompress  # type: ignore[import-untyped]  # override cita dbc_to_dbf
from dbfread import DBF

from sustemporal.contracts import EstadoIntegridade
from sustemporal.ingest.dbf import (
    COLUNA_DELETADO,
    COLUNA_INDICE,
    TAMANHO_BLOCO_PADRAO,
    VERSOES_DBASE,
    QuarentenaLeitura,
    ler_dbf,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from numpy.typing import NDArray

    from sustemporal.contracts import VerificacaoFidelidade
    from sustemporal.ingest.dbf import LeituraDbf

logger = logging.getLogger(__name__)

FLAGS_LITERAIS = frozenset({0, 1})
DICIONARIOS = frozenset({4, 5, 6})
_TAM_POS_CABECALHO = 4
_MAX_DIVERGENCIAS = 20


@dataclass(frozen=True)
class MetadadosDbc:
    tam_cabecalho: int
    bytes_pos_cabecalho_hex: str
    flag_literais: int
    dicionario: int
    bibliotecas: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LeituraDbc:
    leitura: LeituraDbf
    metadados: MetadadosDbc


@dataclass(frozen=True)
class RelatorioFidelidade:
    modo: VerificacaoFidelidade
    verificado: bool
    registros_comparados: int
    divergencias: tuple[str, ...]
    bibliotecas: tuple[tuple[str, str], ...]

    @property
    def fiel(self) -> bool:
        return self.verificado and not self.divergencias


def _versoes(*pacotes: str) -> tuple[tuple[str, str], ...]:
    return tuple((pacote, metadata.version(pacote)) for pacote in pacotes)


def _inesperado(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, motivo)


def _conferir_envelope(dados: bytes) -> tuple[int, int, int]:
    if len(dados) < 12 or dados[0] not in VERSOES_DBASE:
        raise _inesperado(f"envelope_dbc_invalido tamanho={len(dados)}")
    (tam_cabecalho,) = struct.unpack_from("<H", dados, 8)
    if tam_cabecalho < 33:
        raise _inesperado(f"cabecalho_dbc_incoerente cabecalho={tam_cabecalho}")
    inicio_fluxo = tam_cabecalho + _TAM_POS_CABECALHO
    if len(dados) < inicio_fluxo + 2:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO,
            f"dbc_sem_fluxo tamanho={len(dados)} cabecalho={tam_cabecalho}",
        )
    flag, dicionario = dados[inicio_fluxo], dados[inicio_fluxo + 1]
    if flag not in FLAGS_LITERAIS or dicionario not in DICIONARIOS:
        raise _inesperado(f"inicio_dcl_invalido flag={flag} dicionario={dicionario}")
    return tam_cabecalho, flag, dicionario


def _descomprimir(dados: bytes) -> bytes:
    try:
        return bytes(decompress_bytes(dados))
    except ValueError as erro:
        texto = str(erro)
        if "end of input" in texto:
            raise QuarentenaLeitura(
                EstadoIntegridade.QUARENTENA_TRUNCADO, f"fluxo_dcl_incompleto erro={texto}"
            ) from erro
        raise _inesperado(f"fluxo_dcl_invalido erro={texto}") from erro


def descomprimir_dbc(dados: bytes) -> tuple[bytes, MetadadosDbc]:
    """DBF descomprimido pelo datasus-dbc, sem reescrever bytes do cabeçalho."""
    tam_cabecalho, flag, dicionario = _conferir_envelope(dados)
    dbf = _descomprimir(dados)
    if len(dbf) < tam_cabecalho:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO,
            f"dbf_menor_que_cabecalho tamanho={len(dbf)} cabecalho={tam_cabecalho}",
        )
    if dbf[:tam_cabecalho] != dados[:tam_cabecalho]:
        raise _inesperado(f"cabecalho_alterado_na_descompressao cabecalho={tam_cabecalho}")
    pos_cabecalho = dados[tam_cabecalho : tam_cabecalho + _TAM_POS_CABECALHO]
    metadados = MetadadosDbc(
        tam_cabecalho=tam_cabecalho,
        bytes_pos_cabecalho_hex=pos_cabecalho.hex(),
        flag_literais=flag,
        dicionario=dicionario,
        bibliotecas=_versoes("datasus-dbc", "sus-temporal"),
    )
    return dbf, metadados


def ler_dbc(dados: bytes, *, tamanho_bloco: int = TAMANHO_BLOCO_PADRAO) -> LeituraDbc:
    """Descomprime e lê o DBF com as checagens físicas do parser próprio."""
    dbf, metadados = descomprimir_dbc(dados)
    leitura = ler_dbf(dbf, tamanho_bloco=tamanho_bloco)
    logger.info(
        "dbc_lido bytes=%s dbf_bytes=%s pos_cabecalho=%s",
        len(dados),
        len(dbf),
        metadados.bytes_pos_cabecalho_hex,
    )
    return LeituraDbc(leitura, metadados)


def _bytes_independentes(dbc: bytes, h: int) -> tuple[bytes | None, list[str]]:
    producao = _descomprimir(dbc)
    try:
        independente = bytes(DBCDecompress().decompress(dbc))
    except Exception as erro:
        return None, [f"dbctodbf_falhou erro={type(erro).__name__}"]
    ajustado = independente[: h - 1] + producao[h - 1 : h] + independente[h:]
    if ajustado != producao:
        return None, [
            f"bytes_divergentes producao={len(producao)} independente={len(independente)}"
        ]
    return independente, []


def _indices_coincidem(leitura: LeituraDbf) -> list[str]:
    indices = leitura.tabela.column(COLUNA_INDICE).to_numpy()
    if np.array_equal(indices, np.arange(leitura.tabela.num_rows, dtype=np.int64)):
        return []
    return [f"indices_fisicos_divergentes linhas={leitura.tabela.num_rows}"]


def _cabecalho_coincide(independente: bytes, leitura: LeituraDbf) -> list[str]:
    cabecalho = leitura.cabecalho
    lido = (
        leitura.tamanho_bytes,
        cabecalho.data_atualizacao,
        cabecalho.n_registros,
        cabecalho.tam_cabecalho,
        cabecalho.tam_registro,
        cabecalho.byte_driver,
    )
    if len(independente) < 32:
        return [f"cabecalho_divergente independente={len(independente)}"]
    n, h, r = struct.unpack_from("<IHH", independente, 4)
    referencia = (len(independente), independente[1:4], n, h, r, independente[29])
    if lido != referencia:
        return [f"cabecalho_divergente lido={lido} independente={referencia}"]
    return []


def _posicoes(n: int, modo: VerificacaoFidelidade, amostra: int) -> NDArray[np.int64]:
    if modo == "COMPLETA" or n <= amostra:
        return np.arange(n, dtype=np.int64)
    return np.unique(np.linspace(0, n - 1, max(amostra, 1)).round().astype(np.int64))


def _coletar(registros: Iterable[Any], ranks: set[int]) -> tuple[int, dict[int, Any]]:
    total, guardados = 0, {}
    for total, registro in enumerate(registros, start=1):
        if total - 1 in ranks:
            guardados[total - 1] = registro
    return total, guardados


def _referencia(
    dbf: bytes, ranks_a: set[int], ranks_d: set[int]
) -> tuple[list[tuple[str, str, int, int]], tuple[int, dict[int, Any]], tuple[int, dict[int, Any]]]:
    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "referencia.dbf"
        caminho.write_bytes(dbf)
        ref = DBF(str(caminho), raw=True, load=False, ignore_missing_memofile=True)
        descritores = [(f.name, f.type, f.length, f.decimal_count) for f in ref.fields]
        return descritores, _coletar(ref.records, ranks_a), _coletar(ref.deleted, ranks_d)


def _comparar_registros(dbf: bytes, leitura: LeituraDbf, posicoes: NDArray[np.int64]) -> list[str]:
    tabela = leitura.tabela
    flags = tabela.column(COLUNA_DELETADO).to_numpy().astype(bool)
    rank_deletado = np.cumsum(flags) - flags
    rank = np.where(flags, rank_deletado, np.arange(flags.size) - rank_deletado)
    nomes = [campo.nome for campo in leitura.cabecalho.campos]
    ranks_d = {int(rank[p]) for p in posicoes if flags[p]}
    ranks_a = {int(rank[p]) for p in posicoes if not flags[p]}
    descritores_ref, (n_ativos, ativos), (n_deletados, deletados) = _referencia(
        dbf, ranks_a, ranks_d
    )
    descritores = [(c.nome, c.tipo, c.largura, c.decimais) for c in leitura.cabecalho.campos]
    divergencias = [] if descritores_ref == descritores else ["campos_divergentes"]
    contagem_coluna = int(flags.sum())
    lidas = (int((~flags).sum()), contagem_coluna, leitura.n_deletados)
    if (n_ativos, n_deletados, n_deletados) != lidas:
        divergencias.append(f"contagens_divergentes ativos={n_ativos} deletados={n_deletados}")
    proprios = tabela.take(posicoes).select(nomes).to_pylist()
    for posicao, proprio in zip(posicoes.tolist(), proprios, strict=True):
        origem = deletados if flags[posicao] else ativos
        esperado = origem.get(int(rank[posicao]))
        obtido = {nome: valor.encode("latin-1") for nome, valor in proprio.items()}
        if esperado is None or dict(esperado) != obtido:
            divergencias.append(f"registro_divergente indice={posicao}")
    return divergencias


def verificar_fidelidade(
    dbc: bytes,
    leitura: LeituraDbf,
    modo: VerificacaoFidelidade = "COMPLETA",
    *,
    amostra: int = 1_000,
) -> RelatorioFidelidade:
    """Compara datasus-dbc × dbc-to-dbf (bytes) e parser próprio × dbfread (registros)."""
    bibliotecas = _versoes("datasus-dbc", "dbc-to-dbf", "dbfread")
    if modo == "DESLIGADA":
        return RelatorioFidelidade(modo, False, 0, (), bibliotecas)
    independente, divergencias = _bytes_independentes(dbc, leitura.cabecalho.tam_cabecalho)
    divergencias += _indices_coincidem(leitura)
    posicoes = _posicoes(leitura.tabela.num_rows, modo, amostra)
    if independente is None:
        posicoes = posicoes[:0]
    else:
        divergencias += _cabecalho_coincide(independente, leitura)
        try:
            divergencias += _comparar_registros(independente, leitura, posicoes)
        except Exception as erro:
            posicoes = posicoes[:0]
            divergencias.append(f"dbfread_falhou erro={type(erro).__name__}")
    logger.info(
        "fidelidade_verificada modo=%s comparados=%s divergencias=%s",
        modo,
        posicoes.size,
        len(divergencias),
    )
    return RelatorioFidelidade(
        modo, True, int(posicoes.size), tuple(divergencias[:_MAX_DIVERGENCIAS]), bibliotecas
    )
