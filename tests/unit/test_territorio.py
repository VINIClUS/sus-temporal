"""Carga e checagem do território do piloto (catálogo SECUNDARIA, A_CONFIRMAR)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sustemporal.errors import ConfigInvalida
from sustemporal.ingest.territorio import carregar_territorio, municipios_ibge6

DRS_XI = Path(__file__).resolve().parents[2] / "catalog" / "territorio" / "drs_xi.yaml"


def test_carrega_drs_xi_com_45_municipios_e_codigos_de_6_digitos() -> None:
    territorio = carregar_territorio(DRS_XI, uf="SP")
    codigos = municipios_ibge6(territorio)
    assert len(codigos) == 45
    assert "354130" in codigos
    assert all(len(codigo) == 6 for codigo in codigos)


def _copia(tmp_path: Path, antigo: str, novo: str) -> Path:
    destino = tmp_path / "territorio.yaml"
    texto = DRS_XI.read_text(encoding="utf-8")
    assert antigo in texto
    destino.write_text(texto.replace(antigo, novo, 1), encoding="utf-8")
    return destino


def test_digito_verificador_invalido_recusa_o_territorio(tmp_path: Path) -> None:
    caminho = _copia(tmp_path, "ibge7: 3514403", "ibge7: 3514404")
    with pytest.raises(ConfigInvalida, match="territorio_digito_verificador"):
        carregar_territorio(caminho, uf="SP")


def test_uf_diferente_da_do_piloto_recusa_o_territorio() -> None:
    with pytest.raises(ConfigInvalida, match="territorio_uf_divergente"):
        carregar_territorio(DRS_XI, uf="PR")


def test_territorio_ilegivel_recusa(tmp_path: Path) -> None:
    caminho = _copia(tmp_path, "uf: SP", "uf: 35")
    with pytest.raises(ConfigInvalida, match="territorio_invalido"):
        carregar_territorio(caminho, uf="SP")
