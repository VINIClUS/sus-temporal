"""Normalização das tabelas do SIGTAP (T04)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import OrigemDados
from sustemporal.ingest.sigtap_zip import LIMITE_MEMBRO_PADRAO

if TYPE_CHECKING:
    from sustemporal.contracts import ArtifactVersion, DatasetRef, LayoutSpec, RuntimeConfig

ESQUEMAS = Path(__file__).resolve().parents[3] / "catalog" / "schemas"
TABELAS: dict[str, str] = {
    "tb_procedimento": "sigtap_procedimento",
    "rl_procedimento_ocupacao": "sigtap_proc_ocupacao",
    "rl_procedimento_registro": "sigtap_proc_registro",
    "tb_registro": "sigtap_registro",
}


def normalize_sigtap(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.REAL,
    limite_membro_bytes: int = LIMITE_MEMBRO_PADRAO,
) -> DatasetRef:
    """Normaliza uma tabela de um pacote TabelaUnificada do SIGTAP."""
    raise NotImplementedError
