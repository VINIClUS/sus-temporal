"""Herança `base:` das configurações: confinada ao diretório da config raiz, sem null na filha."""

import re
from pathlib import Path

import pytest

from sustemporal.config import load_config
from sustemporal.errors import ConfigInvalida

BASE = "versao: 1\nruntime:\n  duckdb_threads: 2\nvigilancia:\n  janela_competencias: 3\n"


@pytest.fixture
def diretorio(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    (config / "sub").mkdir(parents=True)
    (config / "runtime.yaml").write_text(BASE, encoding="utf-8")
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "runtime.yaml").write_text(BASE, encoding="utf-8")
    return config


def _gravar(diretorio: Path, texto: str, nome: str = "filha.yaml") -> Path:
    caminho = diretorio / nome
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_base_relativa_no_mesmo_diretorio_e_aceita(diretorio: Path) -> None:
    config = load_config(_gravar(diretorio, "base: runtime.yaml\nsemente: 7\n"))
    assert (config.semente, config.runtime.duckdb_threads) == (7, 2)


def test_base_aninhada_que_volta_ao_diretorio_raiz_e_aceita(diretorio: Path) -> None:
    _gravar(diretorio / "sub", "base: ../runtime.yaml\nsemente: 9\n", "meio.yaml")
    config = load_config(_gravar(diretorio, "base: sub/meio.yaml\n"))
    assert (config.semente, config.runtime.duckdb_threads) == (9, 2)


def test_base_absoluta_e_recusada_mesmo_dentro_do_diretorio(diretorio: Path) -> None:
    caminho = _gravar(diretorio, f"base: {diretorio / 'runtime.yaml'}\n")
    with pytest.raises(ConfigInvalida, match="config_base_fora_do_diretorio"):
        load_config(caminho)


@pytest.mark.parametrize("base", ["../fora/runtime.yaml", "sub/../../fora/runtime.yaml"])
def test_base_que_sai_do_diretorio_da_config_raiz_e_recusada(diretorio: Path, base: str) -> None:
    with pytest.raises(ConfigInvalida, match="config_base_fora_do_diretorio"):
        load_config(_gravar(diretorio, f"base: {base}\n"))


def test_base_aninhada_que_sai_do_diretorio_da_config_raiz_e_recusada(diretorio: Path) -> None:
    _gravar(diretorio / "sub", "base: ../../fora/runtime.yaml\n", "meio.yaml")
    with pytest.raises(ConfigInvalida, match="config_base_fora_do_diretorio"):
        load_config(_gravar(diretorio, "base: sub/meio.yaml\n"))


def test_base_por_link_simbolico_para_fora_e_recusada(diretorio: Path) -> None:
    (diretorio / "atalho.yaml").symlink_to(diretorio.parent / "fora" / "runtime.yaml")
    with pytest.raises(ConfigInvalida, match="config_base_fora_do_diretorio"):
        load_config(_gravar(diretorio, "base: atalho.yaml\n"))


@pytest.mark.parametrize(
    ("texto", "chave"),
    [
        ("vigilancia: null\n", "vigilancia"),
        ("vigilancia: ~\n", "vigilancia"),
        ("runtime:\n", "runtime"),
        ("runtime:\n  duckdb_threads: null\n", "runtime.duckdb_threads"),
        ("vigilancia:\n  janela_competencias:\n", "vigilancia.janela_competencias"),
    ],
)
def test_null_explicito_na_config_filha_e_recusado(diretorio: Path, texto: str, chave: str) -> None:
    caminho = _gravar(diretorio, f"base: runtime.yaml\n{texto}")
    padrao = rf"config_null_nao_permitido chave={re.escape(chave)}( |$)"
    with pytest.raises(ConfigInvalida, match=padrao):
        load_config(caminho)


def test_null_em_base_intermediaria_tambem_e_recusado(diretorio: Path) -> None:
    _gravar(diretorio / "sub", "base: ../runtime.yaml\nvigilancia: null\n", "meio.yaml")
    with pytest.raises(ConfigInvalida, match="config_null_nao_permitido chave=vigilancia"):
        load_config(_gravar(diretorio, "base: sub/meio.yaml\nsemente: 3\n"))


def test_null_em_config_sem_base_continua_permitido(diretorio: Path) -> None:
    config = load_config(_gravar(diretorio, "versao: 1\nvigilancia: null\n"))
    assert config.vigilancia is None
