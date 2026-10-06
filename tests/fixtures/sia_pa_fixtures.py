"""Fábrica de arquivos PA sintéticos (SINTETICO): DBC montado a partir do leiaute do catálogo.

Todos os valores são fictícios e escolhidos só para exercitar o normalizador; nenhum provém de
arquivo real.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    ArtifactVersion,
    CanalPublicacao,
    ChaveArtefato,
    EstadoIntegridade,
    FamiliaFonte,
    FormatoArquivo,
    LayoutSpec,
)
from sustemporal.contracts.artifacts import calcular_artifact_id
from sustemporal.store import caminho_conteudo
from sustemporal.yamlio import carregar_yaml
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

RAIZ = Path(__file__).resolve().parents[2]
CAMINHO_LEIAUTE = RAIZ / "catalog" / "layouts" / "sia_pa.yaml"
CAMINHO_CODEBOOK = RAIZ / "catalog" / "labels" / "sia_pa.yaml"
CAMINHO_ESQUEMA = RAIZ / "catalog" / "schemas" / "sia_pa.yaml"
CAMINHO_ESQUEMA_ROTULOS = RAIZ / "catalog" / "schemas" / "sia_pa_rotulos.yaml"

PADRAO: dict[str, str] = {
    "PA_CODUNI": "0012345",
    "PA_GESTAO": "350000",
    "PA_CONDIC": "EP",
    "PA_UFMUN": "354140",
    "PA_REGCT": "0000",
    "PA_INCOUT": "0000",
    "PA_INCURG": "0000",
    "PA_TPUPS": "05",
    "PA_TIPPRE": "00",
    "PA_MN_IND": "M",
    "PA_CNPJCPF": "0" * 14,
    "PA_CNPJMNT": "0" * 14,
    "PA_CNPJ_CC": "0" * 14,
    "PA_MVM": "201801",
    "PA_CMP": "201712",
    "PA_PROC_ID": "0301010072",
    "PA_TPFIN": "06",
    "PA_SUBFIN": "0000",
    "PA_NIVCPL": "2",
    "PA_DOCORIG": "I",
    "PA_AUTORIZ": "0" * 13,
    "PA_CNSMED": "0" * 15,
    "PA_CBOCOD": "225125",
    "PA_MOTSAI": "00",
    "PA_OBITO": "0",
    "PA_ENCERR": "0",
    "PA_PERMAN": "0",
    "PA_ALTA": "0",
    "PA_TRANSF": "0",
    "PA_CIDPRI": "J069",
    "PA_CIDSEC": "",
    "PA_CIDCAS": "",
    "PA_CATEND": "01",
    "PA_IDADE": "034",
    "IDADEMIN": "0",
    "IDADEMAX": "130",
    "PA_FLIDADE": "1",
    "PA_SEXO": "F",
    "PA_RACACOR": "03",
    "PA_MUNPCN": "354140",
    "PA_QTDPRO": "1",
    "PA_QTDAPR": "1",
    "PA_VALPRO": "10.00",
    "PA_VALAPR": "10.00",
    "PA_UFDIF": "0",
    "PA_MNDIF": "0",
    "PA_DIF_VAL": "0.00",
    "NU_VPA_TOT": "0.00",
    "NU_PA_TOT": "0.00",
    "PA_INDICA": "5",
    "PA_CODOCO": "1",
    "PA_FLQT": "K",
    "PA_FLER": "0",
    "PA_ETNIA": "",
    "PA_VL_CF": "0.00",
    "PA_VL_CL": "0.00",
    "PA_VL_INC": "0.00",
    "PA_SRV_C": "",
    "PA_INE": "",
    "PA_NAT_JUR": "1023",
    "PA_FNTORC": "",
}


def leiaute_pa() -> LayoutSpec:
    return LayoutSpec.model_validate(carregar_yaml(CAMINHO_LEIAUTE))


def campos_pa(n_colunas: int = 60) -> list[CampoDbf]:
    """Primeiros `n_colunas` campos do leiaute do catálogo (54, 60 ou 61)."""
    return [
        CampoDbf(c.nome_fisico, c.tipo_fisico, c.largura, c.decimais)
        for c in leiaute_pa().campos[:n_colunas]
    ]


def registro_pa(**sobrescritas: str) -> dict[str, str]:
    desconhecidos = set(sobrescritas) - set(PADRAO)
    if desconhecidos:
        raise ValueError(f"campo_desconhecido campos={sorted(desconhecidos)}")
    return {**PADRAO, **sobrescritas}


def dbc_pa(
    registros: Sequence[Mapping[str, str]],
    *,
    n_colunas: int = 60,
    deletados: Collection[int] = (),
    campos: Sequence[CampoDbf] | None = None,
    truncar_bytes: int = 0,
) -> bytes:
    escolhidos = list(campos) if campos is not None else campos_pa(n_colunas)
    linhas = [tuple(registro[c.nome] for c in escolhidos) for registro in registros]
    dbf = escrever_dbf(escolhidos, linhas, deletados=deletados, truncar_bytes=truncar_bytes)
    return dbf_para_dbc(dbf)


def artefato_pa(
    pasta: Path,
    dbc: bytes,
    *,
    competencia: str = "201801",
    parte: str | None = "a",
    integridade: EstadoIntegridade = EstadoIntegridade.OK,
    formato: FormatoArquivo = FormatoArquivo.DBC,
) -> ArtifactVersion:
    sha256 = hashlib.sha256(dbc).hexdigest()
    extensao = formato.value.lower()
    nome = f"PASP{competencia[2:]}{parte or ''}.{extensao}"
    caminho = caminho_conteudo(pasta, sha256, extensao)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dbc)
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf="SP",
        competencia_arquivo=competencia,
        parte=parte,
        canal=CanalPublicacao.ATUAL,
        nome_original=nome,
    )
    return ArtifactVersion(
        artifact_id=calcular_artifact_id(chave, sha256),
        chave=chave,
        localizador=f"sintetico://{nome}",
        sha256=sha256,
        tamanho_bytes=len(dbc),
        formato=formato,
        caminho_conteudo=str(caminho),
        leiaute_id="sia_pa.it_2019_07",
        integridade=integridade,
    )
