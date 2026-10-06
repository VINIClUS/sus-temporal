"""Recusas do `reproduce` que não dependem de refazer o fluxo (T14); config SINTETICO."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sustemporal.config import load_config
from sustemporal.contracts.experiment import ModoExecucao
from sustemporal.errors import ConfigInvalida, RedeProibida
from sustemporal.reporting.reproduce import configurar_parser, executar_reproduce, reproduce
from sustemporal.reporting.reproduce_leituras import Dano
from tests.fixtures.reproducao_estragos import estragado
from tests.fixtures.reproducao_mundo import Mundo, escrever_config

if TYPE_CHECKING:
    from sustemporal.contracts import RunConfig

FREEZE = "frz_" + "a" * 64


def _config(tmp_path: Path, **mudancas: object) -> RunConfig:
    config = load_config(escrever_config(Mundo(tmp_path), "unidade", ("202401",)))
    return config.model_copy(update=mudancas)


def _argumentos(freeze: str = FREEZE, *, offline: bool = True) -> argparse.Namespace:
    return argparse.Namespace(freeze=freeze, offline=offline, saida=None)


def test_reproduce_exige_freeze_id_na_config(tmp_path: Path) -> None:
    destino = tmp_path / "out"
    with pytest.raises(ConfigInvalida, match=r"^reproduce_exige_freeze_id$"):
        reproduce(_config(tmp_path), destino)
    assert not destino.exists()


def test_reproduce_recusa_config_que_permite_rede(tmp_path: Path) -> None:
    config = _config(tmp_path)
    permissiva = config.runtime.model_copy(update={"rede_permitida": True})
    destino = tmp_path / "out"
    with pytest.raises(RedeProibida, match=r"^reproduce_com_rede_permitida$"):
        reproduce(_config(tmp_path, freeze_id=FREEZE, runtime=permissiva), destino)
    assert not destino.exists()


def test_reproduce_nao_reproduz_o_confirmatorio(tmp_path: Path) -> None:
    config = _config(tmp_path, freeze_id=FREEZE, modo=ModoExecucao.CONFIRMATORIO)
    padrao = f"^reproduce_confirmatorio_nao_suportado freeze={FREEZE}$"
    with pytest.raises(ConfigInvalida, match=padrao):
        reproduce(config, tmp_path / "out")


def test_reproduce_de_congelamento_ausente_nao_cria_o_destino(tmp_path: Path) -> None:
    destino = tmp_path / "out"
    with pytest.raises(ConfigInvalida, match=f"^congelamento_ausente freeze={FREEZE} diretorio="):
        reproduce(_config(tmp_path, freeze_id=FREEZE), destino)
    assert not destino.exists()


@pytest.fixture
def congelamento_lido(monkeypatch: pytest.MonkeyPatch) -> None:
    """O congelamento já lido: o destino é conferido logo depois dele e antes de usá-lo."""
    monkeypatch.setattr("sustemporal.reporting.reproduce.carregar_freeze", lambda *_a, **_k: None)


@pytest.mark.usefixtures("congelamento_lido")
def test_destino_que_nao_se_lista_sai_2_e_nao_traceback(tmp_path: Path) -> None:
    destino = tmp_path / "out"
    destino.mkdir()
    with (
        estragado(destino, Dano.PERMISSAO),
        pytest.raises(ConfigInvalida, match=r"^reproduce_destino_ilegivel caminho=.* erro=\w+$"),
    ):
        reproduce(_config(tmp_path, freeze_id=FREEZE), destino)


@pytest.mark.usefixtures("congelamento_lido")
def test_destino_numa_pasta_que_nao_se_acessa_sai_2_e_nao_traceback(tmp_path: Path) -> None:
    pai = tmp_path / "pai"
    pai.mkdir()
    with (
        estragado(pai, Dano.PERMISSAO),
        pytest.raises(ConfigInvalida, match=r"^reproduce_destino_ilegivel caminho=.*pai/out erro="),
    ):
        reproduce(_config(tmp_path, freeze_id=FREEZE), pai / "out")


@pytest.mark.usefixtures("congelamento_lido")
def test_destino_que_nao_se_cria_diz_o_erro_do_sistema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def sem_espaco(self: Path, **_nomeados: object) -> None:
        raise OSError(28, "No space left on device", str(self))

    monkeypatch.setattr(Path, "mkdir", sem_espaco)
    padrao = r"^reproduce_destino_ilegivel caminho=.* erro=OSError$"
    with pytest.raises(ConfigInvalida, match=padrao):
        reproduce(_config(tmp_path, freeze_id=FREEZE), tmp_path / "out")


def test_executar_reproduce_exige_offline(tmp_path: Path) -> None:
    with pytest.raises(ConfigInvalida, match=r"^reproduce_exige_offline$"):
        executar_reproduce(_argumentos(offline=False), _config(tmp_path, freeze_id=FREEZE))


def test_executar_reproduce_recusa_freeze_diferente_do_da_config(tmp_path: Path) -> None:
    outro = "frz_" + "b" * 64
    config = _config(tmp_path, freeze_id=outro)
    padrao = f"^reproduce_freeze_diverge_da_config freeze={FREEZE} config={outro}$"
    with pytest.raises(ConfigInvalida, match=padrao):
        executar_reproduce(_argumentos(), config)


def test_configurar_parser_aceita_saida() -> None:
    parser = argparse.ArgumentParser(prog="sustemporal reproduce")
    configurar_parser(parser)
    assert parser.parse_args(["--saida", "relativo/saida"]).saida == Path("relativo/saida")
    assert parser.parse_args([]).saida is None
