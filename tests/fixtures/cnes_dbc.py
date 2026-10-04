"""Fábrica de arquivos CNES PF e ST sintéticos (SINTETICO), montados pelo leiaute do catálogo.

Todos os valores são fictícios e escolhidos só para exercitar o normalizador. Os campos pessoais
do PF (CPF, CNS, nome, registro) recebem valores obviamente falsos, para que os testes provem que
nada deles chega à tabela canônica.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    ArtifactVersion,
    CanalPublicacao,
    ChaveArtefato,
    EstadoIntegridade,
    FamiliaFonte,
    FormatoArquivo,
)
from sustemporal.contracts.artifacts import calcular_artifact_id
from sustemporal.ingest.cnes import carregar_leiautes_cnes
from sustemporal.store import caminho_conteudo
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "IDENTIFICADORES_FALSOS",
    "artefato_cnes",
    "campos_cnes",
    "dbc_cnes",
    "registro_pf",
    "registro_st",
]

IDENTIFICADORES_FALSOS = {
    "CPF_PROF": "12345678909",
    "CNS_PROF": "700000000000000",
    "NOMEPROF": "PROFISSIONAL FICTICIO",
    "REGISTRO": "CRMFICTICIO1",
    "UFMUNRES": "350000",
    "CPF_CNPJ": "00000000000191",
}


def campos_cnes(fonte: FamiliaFonte) -> list[CampoDbf]:
    layout = carregar_leiautes_cnes()[fonte]
    return [CampoDbf(c.nome_fisico, c.tipo_fisico, c.largura, c.decimais) for c in layout.campos]


def registro_pf(cnes: str, cbo: str, competencia: str = "201801", **outros: str) -> dict[str, str]:
    registro = {campo.nome: "" for campo in campos_cnes(FamiliaFonte.CNES_PF)}
    registro.update(IDENTIFICADORES_FALSOS)
    registro.update(
        {"CNES": cnes, "CODUFMUN": "354140", "CBO": cbo, "COMPETEN": competencia, "PROF_SUS": "1"}
    )
    registro.update({"HORAOUTR": "  0", "HORAHOSP": "  0", "HORA_AMB": " 20"})
    registro.update(outros)
    return registro


def registro_st(cnes: str, competencia: str = "201801", **outros: str) -> dict[str, str]:
    registro = {
        "CNES": cnes,
        "CODUFMUN": "354140",
        "TPGESTAO": "M",
        "TP_UNID": "02",
        "NAT_JUR": "1244",
        "COMPETEN": competencia,
    }
    registro.update(outros)
    return registro


def dbc_cnes(
    fonte: FamiliaFonte,
    registros: Sequence[Mapping[str, str]],
    *,
    deletados: Collection[int] = (),
    campos: Sequence[CampoDbf] | None = None,
    truncar_bytes: int = 0,
) -> bytes:
    escolhidos = list(campos) if campos is not None else campos_cnes(fonte)
    linhas = [tuple(registro.get(c.nome, "") for c in escolhidos) for registro in registros]
    dbf = escrever_dbf(escolhidos, linhas, deletados=deletados, truncar_bytes=truncar_bytes)
    return dbf_para_dbc(dbf)


def artefato_cnes(
    pasta: Path,
    dados: bytes,
    fonte: FamiliaFonte = FamiliaFonte.CNES_PF,
    *,
    competencia: str = "201801",
    integridade: EstadoIntegridade = EstadoIntegridade.OK,
    formato: FormatoArquivo = FormatoArquivo.DBC,
    uf: str = "SP",
) -> ArtifactVersion:
    sha256 = hashlib.sha256(dados).hexdigest()
    extensao = formato.value.lower()
    grupo = fonte.value.removeprefix("CNES_")
    nome = f"{grupo}{uf}{competencia[2:]}.{extensao}"
    caminho = caminho_conteudo(pasta, sha256, extensao)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados)
    chave = ChaveArtefato.model_validate(
        {
            "fonte": fonte,
            "uf": uf,
            "competencia_arquivo": competencia,
            "canal": CanalPublicacao.ATUAL,
            "nome_original": nome,
        }
    )
    return ArtifactVersion(
        artifact_id=calcular_artifact_id(chave, sha256),
        chave=chave,
        localizador=f"sintetico://{nome}",
        sha256=sha256,
        tamanho_bytes=len(dados),
        formato=formato,
        caminho_conteudo=str(caminho),
        integridade=integridade,
    )
