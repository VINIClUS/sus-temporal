"""Catálogos congelados conferidos pelo digest antes da confirmação (T11, SINTETICO).

Os digests são recalculados pelos mesmos caminhos (`config.catalogos`) e pela mesma função com
que `congelar` os gravou. Cenário sintético rotulado REAL só nos contratos; decisões G0/G2 só
em diretórios temporários.
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    catalogo_da_config,
    config_confirmatoria_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    CATALOGO_SIA_PA,
    CONFIG_PROTOCOLO,
    Confirmatorio,
    montar_confirmatorio,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.config import RunConfig
from sustemporal.errors import ConfigInvalida, ExitCode, PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import verificar_congelamento_completo
from sustemporal.evaluation.metrics import evaluate_runs

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.protocolo_dados import Cenario


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def catalogo(tmp_path: Path) -> Path:
    copia = tmp_path / "catalogos" / CATALOGO_SIA_PA.name
    copia.parent.mkdir()
    shutil.copyfile(CATALOGO_SIA_PA, copia)
    return copia


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario, catalogo: Path) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario, catalogo=catalogo)


def _mensagem(conf: Confirmatorio) -> str:
    base = f"freeze_incompativel campos=catalogos freeze={conf.manifesto.freeze_id}"
    return f"^{re.escape(base)}$"


def _alterar(catalogo: Path) -> None:
    catalogo.write_text(catalogo.read_text(encoding="utf-8") + "\n# alterado\n", encoding="utf-8")


def test_catalogo_alterado_depois_do_congelamento_e_recusado(
    confirmatorio: Confirmatorio, catalogo: Path
) -> None:
    verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado)
    _alterar(catalogo)
    with pytest.raises(PortaoRecusado, match=_mensagem(confirmatorio)):
        verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado)


def test_catalogo_ausente_e_recusado(confirmatorio: Confirmatorio, catalogo: Path) -> None:
    catalogo.unlink()
    with pytest.raises(PortaoRecusado, match=_mensagem(confirmatorio)):
        verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado)


def test_catalogo_regravado_com_o_mesmo_conteudo_passa(
    confirmatorio: Confirmatorio, catalogo: Path
) -> None:
    catalogo.write_bytes(catalogo.read_bytes())
    verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado)


def test_confirmatorio_recusa_o_catalogo_alterado_antes_de_ler_qualquer_dado(
    tmp_path: Path, cenario: Cenario, catalogo: Path
) -> None:
    conf = montar_confirmatorio(tmp_path, cenario, catalogo=catalogo)
    _alterar(catalogo)
    with pytest.raises(PortaoRecusado, match=_mensagem(conf)):
        evaluate_runs(
            conf.runs,
            conf.rotulos,
            conf.cenario.split,
            tmp_path / "av",
            bootstrap=conf.manifesto.bootstrap,
            congelamento=conf.referencia(),
        )
    assert not (tmp_path / "av").exists()


def test_congelar_recusa_catalogos_que_a_config_nao_declara(
    tmp_path: Path, cenario: Cenario, catalogo: Path
) -> None:
    config = RunConfig.model_validate(
        {**CONFIG_PROTOCOLO, "catalogos": {"esquema_sia_pa": str(catalogo.with_name("outro.yaml"))}}
    )
    with pytest.raises(ConfigInvalida, match="congelamento_catalogos_fora_da_config"):
        montar_confirmatorio(tmp_path, cenario, catalogo=catalogo, config=config)


@pytest.mark.parametrize("estado", ["alterado", "ausente"])
def test_cli_recusa_o_confirmatorio_com_catalogo_alterado_ou_ausente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    estado: str,
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    gravar_runs(tmp_path, runs_da_cli(tmp_path, cenario, freeze))
    config = config_confirmatoria_yaml(tmp_path, freeze)
    arquivo = catalogo_da_config(tmp_path)
    if estado == "alterado":
        _alterar(arquivo)
    else:
        arquivo.unlink()
    argumentos = ["evaluate", "--config", str(config), "--freeze", freeze]
    assert executar_cli(argumentos) == ExitCode.PORTAO_RECUSADO
    assert f"freeze_incompativel campos=catalogos freeze={freeze}" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
