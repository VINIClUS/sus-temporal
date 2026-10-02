"""Normalização do SIA-PA preservando multiplicidade (T03)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts import OrigemDados

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import (
        ArtifactVersion,
        CampoLeiaute,
        DatasetRef,
        LayoutSpec,
        RuntimeConfig,
    )
    from sustemporal.ingest.dbf import CabecalhoDbf

PADROES: dict[str, str] = {
    "cnes": r"^[0-9]{7}$",
    "municipio_estabelecimento": r"^[0-9]{6}$",
    "tipo_unidade": r"^[0-9]{2}$",
    "competencia_processamento": r"^[0-9]{4}(0[1-9]|1[0-2])$",
    "competencia_atendimento": r"^[0-9]{4}(0[1-9]|1[0-2])$",
    "procedimento": r"^[0-9]{10}$",
    "instrumento": r"^[CIPSAB]$",
    "cbo": r"^[0-9A-Z]{6}$",
    "cid_principal": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "cid_secundario": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "cid_causas_associadas": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "carater_atendimento": r"^[0-9]{2}$",
    "sexo": r"^[MF]$",
}
CAMPOS_DESCARTADOS = frozenset(
    {"pa_cnpjcpf", "pa_cnpjmnt", "pa_cnpj_cc", "pa_autoriz", "pa_cnsmed", "pa_fntorc"}
)
DIMENSOES_PERFIL = (
    "competencia_processamento",
    "competencia_atendimento",
    "instrumento",
    "cnes",
)


@dataclass(frozen=True)
class PerfilPa:
    """Perfil por estrato do bruto e do canônico, com reconciliação das contagens."""

    caminho: str
    linhas: int
    totais: dict[tuple[str, str], int]
    reconciliado: bool


def casar_leiaute(cabecalho: CabecalhoDbf, layout: LayoutSpec) -> tuple[CampoLeiaute, ...]:
    """Campos do leiaute presentes no arquivo, na ordem física; o resto vai para quarentena."""
    raise NotImplementedError


def normalize_pa(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.REAL,
    esquema: Path | None = None,
) -> DatasetRef:
    """Normaliza um artefato SIA-PA para o esquema canônico sia_pa.v1."""
    raise NotImplementedError


def perfil_pa(dataset: DatasetRef, out: Path, *, runtime: RuntimeConfig | None = None) -> PerfilPa:
    """Contagens por competência, instrumento e estabelecimento, do bruto e do canônico."""
    raise NotImplementedError
