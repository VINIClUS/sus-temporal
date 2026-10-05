"""Manifestos de execução ilegíveis em `runs/` não derrubam o `evaluate` (T11, SINTETICO).

A pasta `runs/` é compartilhada: um `run.json` ou `run_result.json` truncado, com UTF-8 inválido
ou fora do contrato, de qualquer protocolo, derrubava o comando antes da seleção. Agora a
execução ilegível é ignorada com `evaluate_execucao_ilegivel`, e as conferências existentes
(métodos das comparações primárias, cobertura) recusam se faltar uma execução necessária.
Cenário sintético rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.fixtures.protocolo_avaliacao import run_agregados
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
    nome_do_arquivo_da_execucao,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import como_real

from sustemporal.config import load_config
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode
from sustemporal.evaluation.freeze_registro import ler_registro

if TYPE_CHECKING:
    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import RunResult

ILEGIVEL = "evaluate_execucao_ilegivel"
CONTEUDOS = {
    "json_truncado": (b'{"run_id": "run_x", "tipo"', "ValidationError"),
    "utf8_invalido": (b"\xff\xfe\x00{", "UnicodeDecodeError"),
    "fora_do_contrato": (b"{}", "ValidationError"),
    "vazio": (b"", "ValidationError"),
}


def _codigo(argumentos: list[str]) -> int | str:
    """Código de saída da CLI; uma exceção que escapa vira texto, para falhar por asserção."""
    try:
        return executar_cli(argumentos)
    except Exception as erro:
        return f"excecao={type(erro).__name__}"


def _estragada(raiz: Path, arquivo: str, conteudo: bytes) -> Path:
    diretorio = raiz / "saidas" / "runs" / "run_estragada"
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / arquivo).write_bytes(conteudo)
    return diretorio


def _execucao_exploratoria(cenario: Cenario, raiz: Path, config_hash: str) -> RunResult:
    assert cenario.split.particoes is not None
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    resultados = {lp.row_id: "ALERTA" if lp.cnes == "0000000" else "ABSTENCAO" for lp in calibracao}
    return run_agregados(
        MetodoId.M_TEMP,
        resultados,
        raiz / "saidas" / "runs",
        origem=OrigemDados.REAL,
        config_hash=config_hash,
        entradas=(como_real(cenario.split.particoes[Particao.CALIBRACAO]),),
    )


def _avaliar_exploratorio(raiz: Path, freeze: str) -> int | str:
    argumentos = ["evaluate", "--config", str(config_yaml(raiz)), "--freeze", freeze]
    return _codigo([*argumentos, "--exploratory"])


def _avaliar_confirmatorio(raiz: Path, freeze: str) -> int | str:
    config = config_confirmatoria_yaml(raiz, freeze)
    return _codigo(["evaluate", "--config", str(config), "--freeze", freeze])


@pytest.mark.parametrize("arquivo", ["run_result.json", "run.json"])
@pytest.mark.parametrize("nome", sorted(CONTEUDOS))
def test_cli_exploratorio_ignora_execucao_ilegivel_e_avalia_as_validas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arquivo: str,
    nome: str,
) -> None:
    conteudo, motivo = CONTEUDOS[nome]
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    valida = _execucao_exploratoria(
        cenario, tmp_path, load_config(config_yaml(tmp_path)).config_hash
    )
    gravar_runs(tmp_path, [valida])
    _estragada(tmp_path, arquivo, conteudo)
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert entrada["runs"] == [valida.run_id]
    assert f"{ILEGIVEL} run=run_estragada motivo={motivo}" in capsys.readouterr().err


@pytest.mark.parametrize("operacao", ["is_file", "read_text"])
def test_cli_exploratorio_ignora_execucao_que_o_sistema_nega_abrir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operacao: str,
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    valida = _execucao_exploratoria(
        cenario, tmp_path, load_config(config_yaml(tmp_path)).config_hash
    )
    gravar_runs(tmp_path, [valida])
    _estragada(tmp_path, "run_result.json", b"{}")
    original = getattr(Path, operacao)

    def negada(self: Path, *argumentos: Any, **opcoes: Any) -> Any:
        if self.parent.name == "run_estragada":
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return original(self, *argumentos, **opcoes)

    monkeypatch.setattr(Path, operacao, negada)
    assert _avaliar_exploratorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert entrada["runs"] == [valida.run_id]
    assert f"{ILEGIVEL} run=run_estragada motivo=PermissionError" in capsys.readouterr().err


def test_cli_confirmatorio_ignora_execucao_ilegivel_de_outro_protocolo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    _estragada(tmp_path, "run_result.json", CONTEUDOS["json_truncado"][0])
    assert _avaliar_confirmatorio(tmp_path, freeze) == ExitCode.OK
    (entrada,) = ler_registro(tmp_path / "frozen" / REGISTRO)
    assert sorted(entrada["runs"]) == sorted(run.run_id for run in runs)
    assert f"{ILEGIVEL} run=run_estragada motivo=ValidationError" in capsys.readouterr().err


def test_cli_confirmatorio_com_execucao_necessaria_ilegivel_recusa_pela_conferencia_existente(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    b_proc = next(run for run in runs if run.metodo is MetodoId.B_PROC)
    destino = tmp_path / "saidas" / "runs" / b_proc.run_id / nome_do_arquivo_da_execucao(b_proc)
    destino.write_bytes(CONTEUDOS["utf8_invalido"][0])
    assert _avaliar_confirmatorio(tmp_path, freeze) == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert f"{ILEGIVEL} run={b_proc.run_id} motivo=UnicodeDecodeError" in erro
    assert "sem_metodo_das_comparacoes_primarias metodos=B_PROC" in erro
    assert not (tmp_path / "frozen" / REGISTRO).exists()


def test_cli_so_com_execucoes_ilegiveis_sai_como_config_invalida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    _estragada(tmp_path, "run_result.json", CONTEUDOS["vazio"][0])
    assert _avaliar_confirmatorio(tmp_path, freeze) == ExitCode.CONFIG_INVALIDA
    assert "avaliacao_sem_execucoes" in capsys.readouterr().err
    assert not (tmp_path / "frozen" / REGISTRO).exists()
