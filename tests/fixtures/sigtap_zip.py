"""Gerador de zips TabelaUnificada sintéticos (SINTETICO) com leiautes embutidos alternativos.

Códigos, nomes e valores são fictícios e escolhidos só para exercitar o normalizador; nenhum provém
de arquivo real. As larguras seguem o catálogo, salvo `largura_valor` (VL_SH, VL_SA e VL_SP com 10
ou 12 posições, como nas variações descritas no inventário).
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    ArtifactVersion,
    CanalPublicacao,
    ChaveArtefato,
    EstadoIntegridade,
    FamiliaFonte,
    FormatoArquivo,
    MembroArquivo,
)
from sustemporal.contracts.artifacts import calcular_artifact_id
from sustemporal.store import caminho_conteudo

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "COLUNAS",
    "ColunaSigtap",
    "artefato_sigtap",
    "colunas_com_valor",
    "corromper",
    "membros_tabela",
    "pacote_padrao",
    "registro_procedimento",
    "zip_sigtap",
]

_V, _N, _C = "VARCHAR2", "NUMBER", "CHAR"
_VALORES = ("VL_SH", "VL_SA", "VL_SP")


@dataclass(frozen=True)
class ColunaSigtap:
    nome: str
    tamanho: int
    tipo: str


COLUNAS: dict[str, tuple[ColunaSigtap, ...]] = {
    "tb_procedimento": (
        ColunaSigtap("CO_PROCEDIMENTO", 10, _V),
        ColunaSigtap("NO_PROCEDIMENTO", 250, _V),
        ColunaSigtap("TP_COMPLEXIDADE", 1, _V),
        ColunaSigtap("TP_SEXO", 1, _V),
        ColunaSigtap("QT_MAXIMA_EXECUCAO", 4, _N),
        ColunaSigtap("QT_DIAS_PERMANENCIA", 4, _N),
        ColunaSigtap("QT_PONTOS", 4, _N),
        ColunaSigtap("VL_IDADE_MINIMA", 4, _N),
        ColunaSigtap("VL_IDADE_MAXIMA", 4, _N),
        ColunaSigtap("VL_SH", 12, _N),
        ColunaSigtap("VL_SA", 12, _N),
        ColunaSigtap("VL_SP", 12, _N),
        ColunaSigtap("CO_FINANCIAMENTO", 2, _V),
        ColunaSigtap("CO_RUBRICA", 6, _V),
        ColunaSigtap("QT_TEMPO_PERMANENCIA", 4, _N),
        ColunaSigtap("DT_COMPETENCIA", 6, _C),
    ),
    "rl_procedimento_ocupacao": (
        ColunaSigtap("CO_PROCEDIMENTO", 10, _V),
        ColunaSigtap("CO_OCUPACAO", 6, _V),
        ColunaSigtap("DT_COMPETENCIA", 6, _C),
    ),
    "rl_procedimento_registro": (
        ColunaSigtap("CO_PROCEDIMENTO", 10, _V),
        ColunaSigtap("CO_REGISTRO", 2, _V),
        ColunaSigtap("DT_COMPETENCIA", 6, _C),
    ),
    "tb_registro": (
        ColunaSigtap("CO_REGISTRO", 2, _V),
        ColunaSigtap("NO_REGISTRO", 50, _V),
        ColunaSigtap("DT_COMPETENCIA", 6, _C),
    ),
}


def colunas_com_valor(largura_valor: int) -> tuple[ColunaSigtap, ...]:
    """Colunas de tb_procedimento com VL_SH, VL_SA e VL_SP na largura pedida."""
    return tuple(
        replace(c, tamanho=largura_valor) if c.nome in _VALORES else c
        for c in COLUNAS["tb_procedimento"]
    )


def texto_leiaute(colunas: Sequence[ColunaSigtap]) -> bytes:
    linhas = ["Coluna,Tamanho,Inicio,Fim,Tipo"]
    inicio = 1
    for coluna in colunas:
        fim = inicio + coluna.tamanho - 1
        linhas.append(f"{coluna.nome},{coluna.tamanho},{inicio},{fim},{coluna.tipo}")
        inicio = fim + 1
    return ("\r\n".join(linhas) + "\r\n").encode("latin-1")


def _celula(coluna: ColunaSigtap, valor: str) -> str:
    if len(valor) > coluna.tamanho:
        raise ValueError(f"valor_maior_que_coluna coluna={coluna.nome} valor={valor!r}")
    if coluna.tipo == _N:
        return valor.rjust(coluna.tamanho, "0") if valor.strip() else valor.ljust(coluna.tamanho)
    return valor.ljust(coluna.tamanho)


def texto_tabela(colunas: Sequence[ColunaSigtap], registros: Sequence[Mapping[str, str]]) -> bytes:
    linhas = ["".join(_celula(c, registro[c.nome]) for c in colunas) for registro in registros]
    return "".join(f"{linha}\r\n" for linha in linhas).encode("latin-1")


def membros_tabela(
    tabela: str,
    registros: Sequence[Mapping[str, str]],
    colunas: Sequence[ColunaSigtap] | None = None,
) -> dict[str, bytes]:
    escolhidas = tuple(colunas) if colunas is not None else COLUNAS[tabela]
    return {
        f"{tabela}.txt": texto_tabela(escolhidas, registros),
        f"{tabela}_layout.txt": texto_leiaute(escolhidas),
    }


def registro_procedimento(codigo: str, competencia: str, **sobrescritas: str) -> dict[str, str]:
    registro = {
        "CO_PROCEDIMENTO": codigo,
        "NO_PROCEDIMENTO": "PROCEDIMENTO SINTETICO ÁÉÇ",
        "TP_COMPLEXIDADE": "1",
        "TP_SEXO": "I",
        "QT_MAXIMA_EXECUCAO": "1",
        "QT_DIAS_PERMANENCIA": "0",
        "QT_PONTOS": "0",
        "VL_IDADE_MINIMA": "0",
        "VL_IDADE_MAXIMA": "1560",
        "VL_SH": "0",
        "VL_SA": "1234",
        "VL_SP": "0",
        "CO_FINANCIAMENTO": "06",
        "CO_RUBRICA": "",
        "QT_TEMPO_PERMANENCIA": "0",
        "DT_COMPETENCIA": competencia,
    }
    registro.update(sobrescritas)
    return registro


def pacote_padrao(competencia: str = "201801", *, largura_valor: int = 12) -> dict[str, bytes]:
    """Quatro tabelas pequenas e coerentes entre si (SINTETICO)."""
    procedimentos = [
        registro_procedimento("0101010010", competencia),
        registro_procedimento("0201010020", competencia, VL_IDADE_MINIMA="9999"),
        registro_procedimento("0301010030", competencia, VL_IDADE_MAXIMA="9999", VL_SH="1"),
    ]
    ocupacoes = [
        {"CO_PROCEDIMENTO": p, "CO_OCUPACAO": c, "DT_COMPETENCIA": competencia}
        for p, c in (
            ("0101010010", "225125"),
            ("0101010010", "2231F9"),
            ("0201010020", "225125"),
            ("0301010030", "322205"),
        )
    ]
    registros = [
        {"CO_PROCEDIMENTO": p, "CO_REGISTRO": r, "DT_COMPETENCIA": competencia}
        for p, r in (("0101010010", "01"), ("0101010010", "02"), ("0201010020", "06"))
    ]
    dominio = [
        {"CO_REGISTRO": r, "NO_REGISTRO": n, "DT_COMPETENCIA": competencia}
        for r, n in (("01", "BPA CONSOLIDADO"), ("02", "BPA INDIVIDUALIZADO"), ("06", "APAC"))
    ]
    return {
        **membros_tabela("tb_procedimento", procedimentos, colunas_com_valor(largura_valor)),
        **membros_tabela("rl_procedimento_ocupacao", ocupacoes),
        **membros_tabela("rl_procedimento_registro", registros),
        **membros_tabela("tb_registro", dominio),
    }


def corromper(dados: bytes, posicao: int, mascara: int = 0xFF) -> bytes:
    """Troca um byte do zip (posição módulo o tamanho) por XOR com a máscara."""
    indice = posicao % len(dados)
    return dados[:indice] + bytes([dados[indice] ^ mascara]) + dados[indice + 1 :]


def zip_sigtap(membros: Mapping[str, bytes], *, compressao: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compressao) as arquivo:
        for nome, dados in membros.items():
            info = zipfile.ZipInfo(nome, date_time=(2018, 1, 1, 0, 0, 0))
            arquivo.writestr(info, dados, compress_type=compressao)
    return buffer.getvalue()


def artefato_sigtap(
    pasta: Path,
    dados: bytes,
    *,
    competencia: str | None = "201801",
    geracao: str = "1801101010",
    integridade: EstadoIntegridade = EstadoIntegridade.OK,
    declarado: bytes | None = None,
) -> ArtifactVersion:
    """Artefato endereçado por conteúdo; `declarado` é o zip cujos membros a aquisição listou
    (permite gravar bytes corrompidos depois da listagem)."""
    sha256 = hashlib.sha256(dados).hexdigest()
    nome = f"TabelaUnificada_{competencia or 'SEM'}_v{geracao}.zip"
    caminho = caminho_conteudo(pasta, sha256, "zip")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados)
    with zipfile.ZipFile(io.BytesIO(declarado if declarado is not None else dados)) as arquivo:
        membros = tuple(
            MembroArquivo(nome=info.filename, tamanho_bytes=info.file_size, seguro=True)
            for info in arquivo.infolist()
        )
    chave = ChaveArtefato.model_validate(
        {
            "fonte": FamiliaFonte.SIGTAP,
            "competencia_arquivo": competencia,
            "canal": CanalPublicacao.ATUAL,
            "nome_original": nome,
            "versao_publicacao": geracao,
        }
    )
    return ArtifactVersion(
        artifact_id=calcular_artifact_id(chave, sha256),
        chave=chave,
        localizador=f"sintetico://{nome}",
        sha256=sha256,
        tamanho_bytes=len(dados),
        formato=FormatoArquivo.ZIP,
        caminho_conteudo=str(caminho),
        integridade=integridade,
        membros=membros,
    )
