from pathlib import Path

import pytest

from sustemporal import cli
from sustemporal.errors import ExitCode
from tests.fixtures.sintetico import manipuladores_falsos

COMANDOS_DO_PLANO = {
    "acquire",
    "ingest",
    "pilot-report",
    "validate",
    "explain",
    "counterfactual",
    "freeze",
    "evaluate",
    "annotation-export",
    "reproduce",
}
FALSOS = "tests.fixtures.sintetico.manipuladores_falsos"


@pytest.fixture
def config_valida(tmp_path: Path) -> Path:
    caminho = tmp_path / "config.yaml"
    caminho.write_text('versao: "1"\nmodo: EXPLORATORIO\n', encoding="utf-8")
    return caminho


@pytest.fixture(autouse=True)
def _limpa_chamadas() -> None:
    manipuladores_falsos.CHAMADAS.clear()


def _apontar(monkeypatch: pytest.MonkeyPatch, comando: str, funcao: str) -> None:
    monkeypatch.setitem(cli.MANIPULADORES, comando, f"{FALSOS}:{funcao}")


def test_todos_os_comandos_do_plano_existem() -> None:
    assert COMANDOS_DO_PLANO | {"watch"} == set(cli.MANIPULADORES)


def test_config_invalida_bloqueia_antes_de_processar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "ingest", "executar_ok")
    invalida = tmp_path / "invalida.yaml"
    invalida.write_text('versao: "1"\nmodo: CONFIRMATORIO\n', encoding="utf-8")
    assert cli.main(["ingest", "--config", str(invalida)]) == ExitCode.CONFIG_INVALIDA
    assert manipuladores_falsos.CHAMADAS == []


def test_config_ausente_retorna_codigo_de_config_invalida(tmp_path: Path) -> None:
    ausente = tmp_path / "nao_existe.yaml"
    assert cli.main(["ingest", "--config", str(ausente)]) == ExitCode.CONFIG_INVALIDA


def test_campo_desconhecido_na_config_e_rejeitado(tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text('versao: "1"\nfallback_mes_vizinho: "true"\n', encoding="utf-8")
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.CONFIG_INVALIDA


def test_comando_sem_modulo_retorna_nao_implementado(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(cli.MANIPULADORES, "ingest", "sustemporal.nao_existe:executar")
    assert cli.main(["ingest", "--config", str(config_valida)]) == ExitCode.NAO_IMPLEMENTADO


def test_manipulador_stub_retorna_nao_implementado(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "freeze", "executar_nao_implementado")
    assert cli.main(["freeze", "--config", str(config_valida)]) == ExitCode.NAO_IMPLEMENTADO


def test_portao_recusado_retorna_codigo_4(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_portao")
    argumentos = ["evaluate", "--freeze", "frz_x", "--config", str(config_valida)]
    assert cli.main(argumentos) == ExitCode.PORTAO_RECUSADO


def test_rede_proibida_retorna_codigo_6(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "acquire", "executar_rede")
    assert cli.main(["acquire", "--config", str(config_valida)]) == ExitCode.REDE_PROIBIDA


def test_modulo_do_comando_pode_acrescentar_argumentos(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "ingest", "executar_ok")
    argumentos = ["ingest", "--config", str(config_valida), "--extra-falso", "sim"]
    assert cli.main(argumentos) == ExitCode.OK
    assert manipuladores_falsos.CHAMADAS == ["ingest:1:sim"]


def test_validate_exige_politica_do_plano(config_valida: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["validate", "--config", str(config_valida), "--policy", "mes_vizinho"])


@pytest.mark.parametrize("conteudo", ["versao: [\n", "versao: \x07\n"])
def test_yaml_malformado_retorna_config_invalida(tmp_path: Path, conteudo: str) -> None:
    config = tmp_path / "c.yaml"
    config.write_text(conteudo, encoding="utf-8")
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.CONFIG_INVALIDA
