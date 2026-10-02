"""Leitura segura do zip TabelaUnificada do SIGTAP e do leiaute embutido em cada competência.

O zip é lido em memória, sem extração para disco; cada membro tem nome validado e tamanho
descomprimido limitado. As posições vêm do `<tabela>_layout.txt` do próprio zip e são conferidas
contra o catálogo: divergência vai para quarentena, nunca para leitura aproximada.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import EstadoIntegridade, FamiliaFonte, FormatoLeiaute, LayoutSpec
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura, compactar
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import IO

    from sustemporal.contracts import CampoLeiaute

__all__ = [
    "CATALOGO_LEIAUTES",
    "LIMITE_MEMBRO_PADRAO",
    "ColunaZip",
    "carregar_leiautes_sigtap",
    "conferir_leiaute",
    "fatiar",
    "ler_leiaute_zip",
    "ler_membro",
    "tabela_do_leiaute",
]

CATALOGO_LEIAUTES = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "sigtap.yaml"
LIMITE_MEMBRO_PADRAO = 256 * 1024 * 1024
_BLOCO = 1024 * 1024
_NOME_MEMBRO = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_LAYOUT_ID = re.compile(r"sigtap\.([a-z_]+)")
_CABECALHO = ("Coluna", "Tamanho", "Inicio", "Fim", "Tipo")
_NUMERO = re.compile(r"[0-9]{1,6}")
_NOME_COLUNA = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


@dataclass(frozen=True)
class ColunaZip:
    nome: str
    tamanho: int
    inicio: int
    fim: int
    tipo: str


def _leiaute(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_LEIAUTE, motivo)


def _inesperado(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, motivo)


def carregar_leiautes_sigtap(caminho: Path = CATALOGO_LEIAUTES) -> dict[str, LayoutSpec]:
    """Leiautes do catálogo por tabela (`sigtap.<tabela>`).

    Raises:
        ValueError: leiaute repetido ou fora do padrão de identificação.
    """
    leiautes: dict[str, LayoutSpec] = {}
    for bruto in carregar_yaml(caminho)["leiautes"]:
        layout = LayoutSpec.model_validate(bruto)
        tabela = tabela_do_leiaute(layout)
        if tabela in leiautes:
            raise ValueError(f"leiaute_repetido tabela={tabela}")
        leiautes[tabela] = layout
    return leiautes


def tabela_do_leiaute(layout: LayoutSpec) -> str:
    """Tabela identificada pelo `layout_id` `sigtap.<tabela>`.

    Raises:
        QuarentenaLeitura: leiaute de outra fonte, de outro formato ou fora do padrão.
    """
    casado = _LAYOUT_ID.fullmatch(layout.layout_id)
    if layout.fonte is not FamiliaFonte.SIGTAP or casado is None:
        raise _leiaute(f"leiaute_nao_sigtap layout={layout.layout_id} fonte={layout.fonte}")
    if layout.formato is not FormatoLeiaute.LARGURA_FIXA:
        raise _leiaute(f"leiaute_nao_largura_fixa layout={layout.layout_id}")
    return casado.group(1)


def _info_unica(arquivo: zipfile.ZipFile, nome: str) -> zipfile.ZipInfo | None:
    if _NOME_MEMBRO.fullmatch(nome) is None or ".." in nome:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO, f"nome_de_membro_invalido nome={nome!r}"
        )
    candidatos = [info for info in arquivo.infolist() if info.filename.lower() == nome.lower()]
    if len(candidatos) > 1:
        raise _inesperado(f"membro_ambiguo nome={nome} ocorrencias={len(candidatos)}")
    if candidatos and candidatos[0].filename != nome:
        raise _inesperado(f"membro_ambiguo nome={nome} lido={compactar(candidatos[0].filename)}")
    return candidatos[0] if candidatos else None


def _ler_limitado(arquivo: zipfile.ZipFile, info: zipfile.ZipInfo, limite: int) -> bytes:
    excesso = _inesperado(f"membro_excede_limite nome={info.filename} limite={limite}")
    if info.file_size > limite:
        raise excesso
    try:
        with arquivo.open(info) as membro:
            return _acumular(membro, limite, excesso)
    except (zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError) as erro:
        raise _inesperado(
            f"membro_ilegivel nome={info.filename} erro={type(erro).__name__}"
        ) from erro


def _acumular(membro: IO[bytes], limite: int, excesso: QuarentenaLeitura) -> bytes:
    """Lê por blocos e recusa ao passar do limite, mesmo que o tamanho declarado minta."""
    partes: list[bytes] = []
    lidos = 0
    while bloco := membro.read(min(_BLOCO, limite + 1 - lidos)):
        lidos += len(bloco)
        if lidos > limite:
            raise excesso
        partes.append(bloco)
    return b"".join(partes)


def ler_membro(arquivo: zipfile.ZipFile, nome: str, limite: int) -> bytes:
    """Bytes de um membro do zip, com nome validado e tamanho descomprimido limitado.

    Raises:
        ArquivoAusente: membro inexistente (componente ausente; inconclusivo).
        QuarentenaLeitura: nome inseguro, membro ambíguo, ilegível ou acima do limite.
    """
    info = _info_unica(arquivo, nome)
    if info is None:
        raise ArquivoAusente(f"membro_ausente nome={nome}")
    return _ler_limitado(arquivo, info, limite)


def _coluna(campos: list[str], indice: int) -> ColunaZip:
    if len(campos) != len(_CABECALHO):
        raise _leiaute(f"leiaute_linha_invalida linha={indice}")
    nome, tamanho, inicio, fim, tipo = (campo.strip() for campo in campos)
    numeros = (tamanho, inicio, fim)
    if _NOME_COLUNA.fullmatch(nome) is None or not all(_NUMERO.fullmatch(n) for n in numeros):
        raise _leiaute(f"leiaute_linha_invalida linha={indice}")
    coluna = ColunaZip(nome, int(tamanho), int(inicio), int(fim), tipo)
    if coluna.tamanho < 1 or coluna.fim - coluna.inicio + 1 != coluna.tamanho or not tipo:
        raise _leiaute(f"leiaute_posicoes_incoerentes coluna={nome}")
    return coluna


def ler_leiaute_zip(dados: bytes) -> tuple[ColunaZip, ...]:
    """Colunas do `*_layout.txt` embutido, com posições contíguas a partir de 1.

    Raises:
        QuarentenaLeitura: cabeçalho, linha ou posições incoerentes.
    """
    linhas = [linha for linha in dados.decode("latin-1").splitlines() if linha.strip()]
    if not linhas or tuple(c.strip() for c in linhas[0].split(",")) != _CABECALHO:
        raise _leiaute("leiaute_cabecalho_invalido")
    colunas = tuple(_coluna(linha.split(","), i) for i, linha in enumerate(linhas[1:], 1))
    if not colunas:
        raise _leiaute("leiaute_sem_colunas")
    proximo = 1
    for coluna in colunas:
        if coluna.inicio != proximo:
            raise _leiaute(f"leiaute_posicoes_incoerentes coluna={coluna.nome}")
        proximo = coluna.fim + 1
    nomes = [coluna.nome for coluna in colunas]
    if len(set(nomes)) != len(nomes):
        raise _leiaute("leiaute_coluna_repetida")
    return colunas


def conferir_leiaute(
    colunas: Sequence[ColunaZip], layout: LayoutSpec
) -> tuple[tuple[ColunaZip, CampoLeiaute], ...]:
    """Casa o leiaute do zip com o do catálogo: mesmas colunas e ordem, tipo igual e largura
    até a máxima do catálogo; campos com `obrigatorio` falso podem faltar.

    Raises:
        QuarentenaLeitura: coluna faltante, extra ou fora de ordem, tipo ou largura divergente.
    """
    presentes = {coluna.nome for coluna in colunas}
    esperados = [c for c in layout.campos if c.obrigatorio or c.nome_fisico in presentes]
    if [c.nome for c in colunas] != [c.nome_fisico for c in esperados]:
        raise _leiaute(
            f"colunas_divergentes layout={layout.layout_id} "
            f"lidas={compactar([c.nome for c in colunas])}"
        )
    for coluna, campo in zip(colunas, esperados, strict=True):
        if coluna.tipo != campo.tipo_fisico:
            raise _leiaute(f"tipo_divergente coluna={coluna.nome} lido={compactar(coluna.tipo)}")
        if coluna.tamanho > campo.largura:
            raise _leiaute(
                f"largura_acima_da_maxima coluna={coluna.nome} lida={coluna.tamanho} "
                f"maxima={campo.largura}"
            )
    return tuple(zip(colunas, esperados, strict=True))


def _registros(dados: bytes) -> list[str]:
    linhas = dados.decode("latin-1").split("\n")
    if linhas and linhas[-1] == "":
        linhas.pop()
    return [linha.removesuffix("\r") for linha in linhas]


def fatiar(dados: bytes, colunas: Sequence[ColunaZip]) -> tuple[list[str], ...]:
    """Recorta os registros de largura fixa em colunas de texto latin-1, sem aparar.

    Raises:
        QuarentenaLeitura: registro com largura divergente (último registro curto: truncado).
    """
    largura = colunas[-1].fim
    registros = _registros(dados)
    for indice, registro in enumerate(registros):
        if len(registro) != largura:
            ultimo = indice == len(registros) - 1 and len(registro) < largura
            estado = (
                EstadoIntegridade.QUARENTENA_TRUNCADO
                if ultimo
                else EstadoIntegridade.QUARENTENA_LEIAUTE
            )
            raise QuarentenaLeitura(
                estado, f"registro_com_largura_divergente linha={indice} lida={len(registro)}"
            )
    return tuple([r[c.inicio - 1 : c.fim] for r in registros] for c in colunas)
