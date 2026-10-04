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
FREEZE = f"frz_{'a' * 64}"
G0_CONTINUAR = (
    "portao: G0\ndecisao: CONTINUAR\ndata: 2025-01-15\nresponsaveis: [orientacao]\n"
    "registrado_por_humano: true\n"
)
G2_ABRIR = (
    "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2025-06-01\nresponsaveis: [orientacao]\n"
    f"registrado_por_humano: true\nfreeze_id: {FREEZE}\n"
)
CONFIG_CONFIRMATORIA = (
    f'versao: "1"\nmodo: CONFIRMATORIO\norigem_dados: REAL\nfreeze_id: {FREEZE}\n'
    "bootstrap:\n  correcao: HOLM\n"
)


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


def test_modulo_ausente_cujo_nome_e_prefixo_textual_do_comando_nao_e_mascarado(
    config_valida: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pacote = tmp_path / "pacote_cli1"
    pacote.mkdir()
    (pacote / "__init__.py").write_text("", encoding="utf-8")
    (pacote / "comando_cli.py").write_text("import pacote_cli1.comando\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    argumentos = ["ingest", "--config", str(config_valida)]
    monkeypatch.setitem(cli.MANIPULADORES, "ingest", "sustemporal.nao_existe.cli:executar")
    assert cli.main(argumentos) == ExitCode.NAO_IMPLEMENTADO
    monkeypatch.setitem(cli.MANIPULADORES, "ingest", "pacote_cli1.comando_cli:executar")
    with pytest.raises(ModuleNotFoundError, match=r"pacote_cli1\.comando"):
        cli.main(argumentos)


def test_manipulador_stub_retorna_nao_implementado(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "pilot-report", "executar_nao_implementado")
    argumentos = ["pilot-report", "--config", str(config_valida)]
    assert cli.main(argumentos) == ExitCode.NAO_IMPLEMENTADO


def test_stub_interno_do_projeto_retorna_nao_implementado(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "pilot-report", "executar_chama_stub_interno")
    argumentos = ["pilot-report", "--config", str(config_valida)]
    assert cli.main(argumentos) == ExitCode.NAO_IMPLEMENTADO


def test_not_implemented_de_biblioteca_nao_vira_comando_nao_implementado(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "acquire", "executar_falha_de_biblioteca")
    with pytest.raises(NotImplementedError, match="zip file version"):
        cli.main(["acquire", "--config", str(config_valida)])


def test_portao_recusado_retorna_codigo_4(
    config_valida: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_portao")
    argumentos = ["evaluate", "--freeze", FREEZE, "--exploratory", "--config", str(config_valida)]
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


def _registrar_decisao(raiz: Path, nome: str, conteudo: str) -> None:
    diretorio = raiz / "experiments" / "decisions"
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


@pytest.mark.parametrize("freeze", ["latest", "../x", f"frz_{'A' * 64}", "frz_curto"])
def test_freeze_fora_do_padrao_e_recusado_pelo_parser(
    config_valida: Path, freeze: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_ok")
    valido = ["evaluate", "--freeze", FREEZE, "--exploratory", "--config", str(config_valida)]
    assert cli.main(valido) == ExitCode.OK
    assert manipuladores_falsos.CHAMADAS == ["evaluate:1:padrao"]
    with pytest.raises(SystemExit):
        cli.main(["evaluate", "--freeze", freeze, "--config", str(config_valida)])
    assert manipuladores_falsos.CHAMADAS == ["evaluate:1:padrao"]


@pytest.mark.parametrize("run", ["../x", "", "run 1", "a/b"])
def test_run_fora_do_padrao_e_recusado_pelo_parser(config_valida: Path, run: str) -> None:
    with pytest.raises(SystemExit):
        cli.main(["explain", "--run", run, "--row", "x", "--config", str(config_valida)])


def test_freeze_exige_g0_antes_do_manipulador(
    config_valida: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "freeze", "executar_ok")
    monkeypatch.chdir(tmp_path)
    argumentos = ["freeze", "--config", str(config_valida)]
    assert cli.main(argumentos) == ExitCode.PORTAO_RECUSADO
    assert manipuladores_falsos.CHAMADAS == []
    _registrar_decisao(tmp_path, "g0.yaml", G0_CONTINUAR)
    assert cli.main(argumentos) == ExitCode.OK


def test_evaluate_confirmatorio_exige_g2_antes_do_manipulador(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_ok")
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "confirmatoria.yaml"
    config.write_text(CONFIG_CONFIRMATORIA, encoding="utf-8")
    argumentos = ["evaluate", "--freeze", FREEZE, "--config", str(config)]
    assert cli.main(argumentos) == ExitCode.PORTAO_RECUSADO
    assert manipuladores_falsos.CHAMADAS == []
    _registrar_decisao(tmp_path, "g2.yaml", G2_ABRIR)
    assert cli.main(argumentos) == ExitCode.OK


def test_evaluate_sem_exploratory_exige_g2_mesmo_com_config_exploratoria(
    config_valida: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_ok")
    monkeypatch.chdir(tmp_path)
    argumentos = ["evaluate", "--freeze", FREEZE, "--config", str(config_valida)]
    assert cli.main(argumentos) == ExitCode.PORTAO_RECUSADO
    assert manipuladores_falsos.CHAMADAS == []
    assert cli.main([*argumentos, "--exploratory"]) == ExitCode.OK


def test_evaluate_exploratory_com_config_confirmatoria_e_recusado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_ok")
    monkeypatch.chdir(tmp_path)
    _registrar_decisao(tmp_path, "g2.yaml", G2_ABRIR)
    config = tmp_path / "confirmatoria.yaml"
    config.write_text(CONFIG_CONFIRMATORIA, encoding="utf-8")
    argumentos = ["evaluate", "--freeze", FREEZE, "--exploratory", "--config", str(config)]
    assert cli.main(argumentos) == ExitCode.PORTAO_RECUSADO
    assert manipuladores_falsos.CHAMADAS == []


def test_evaluate_confirmatorio_exige_o_freeze_da_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apontar(monkeypatch, "evaluate", "executar_ok")
    monkeypatch.chdir(tmp_path)
    _registrar_decisao(tmp_path, "g2.yaml", G2_ABRIR)
    config = tmp_path / "confirmatoria.yaml"
    config.write_text(CONFIG_CONFIRMATORIA, encoding="utf-8")
    outro = f"frz_{'b' * 64}"
    assert cli.main(["evaluate", "--freeze", outro, "--config", str(config)]) == 4
    assert manipuladores_falsos.CHAMADAS == []
