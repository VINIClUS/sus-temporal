"""Manifesto de congelamento ilegível vira falha controlada, não exceção solta (T11, SINTETICO).

`carregar_freeze` só protegia o contrato (`ValidationError`): bytes que não são UTF-8 levantavam
`UnicodeDecodeError` e um erro do sistema de arquivos (`OSError`, como a permissão negada)
escapava da CLI com traceback. Os dois passam a sair como `ConfigInvalida` (código 2), com o
mesmo formato `chave=valor` das demais recusas do módulo. Nenhum resultado empírico.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures.protocolo_cli import config_yaml, executar_cli

from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.evaluation.freeze import carregar_freeze

FREEZE = f"frz_{'a' * 64}"
CONTEUDOS = {
    "utf8_invalido": b"\xff\xfe\x00{",
    "vazio": b"",
    "json_truncado": b'{"freeze_id": "frz_',
    "fora_do_contrato": b"{}",
}


def _manifesto(diretorio: Path, conteudo: bytes) -> Path:
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = diretorio / f"{FREEZE}.json"
    caminho.write_bytes(conteudo)
    return caminho


def _carregar(diretorio: Path) -> str:
    """Resultado de `carregar_freeze` como texto; uma exceção solta vira texto, para falhar por
    asserção."""
    try:
        carregar_freeze(diretorio, FREEZE)
    except ConfigInvalida as erro:
        return f"ConfigInvalida {erro}"
    except Exception as erro:
        return f"excecao={type(erro).__name__}"
    return "carregado"


def _negar(monkeypatch: pytest.MonkeyPatch, operacao: str, alvo: Path) -> None:
    """Permissão negada no sistema de arquivos, só para `alvo` (fronteira de E/S)."""
    original = getattr(Path, operacao)

    def negada(self: Path, *argumentos: Any, **opcoes: Any) -> Any:
        if self == alvo:
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return original(self, *argumentos, **opcoes)

    monkeypatch.setattr(Path, operacao, negada)


@pytest.mark.parametrize("nome", sorted(CONTEUDOS))
def test_manifesto_de_conteudo_invalido_e_config_invalida(tmp_path: Path, nome: str) -> None:
    _manifesto(tmp_path / "frozen", CONTEUDOS[nome])
    assert _carregar(tmp_path / "frozen") == f"ConfigInvalida congelamento_invalido freeze={FREEZE}"


@pytest.mark.parametrize("operacao", ["is_file", "read_text"])
def test_manifesto_que_o_sistema_nega_ler_e_config_invalida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operacao: str
) -> None:
    caminho = _manifesto(tmp_path / "frozen", b"{}")
    _negar(monkeypatch, operacao, caminho)
    esperado = f"ConfigInvalida congelamento_ilegivel freeze={FREEZE} motivo=PermissionError"
    assert _carregar(tmp_path / "frozen") == esperado


def test_manifesto_ausente_continua_sendo_config_invalida(tmp_path: Path) -> None:
    pasta = tmp_path / "frozen"
    esperado = f"ConfigInvalida congelamento_ausente freeze={FREEZE} diretorio={pasta}"
    assert _carregar(pasta) == esperado


def _avaliar(raiz: Path) -> int | str:
    """Código de saída do `evaluate`; uma exceção que escapa da CLI vira texto."""
    argumentos = ["evaluate", "--config", str(config_yaml(raiz)), "--freeze", FREEZE]
    try:
        return executar_cli([*argumentos, "--exploratory"])
    except Exception as erro:
        return f"excecao={type(erro).__name__}"


@pytest.mark.parametrize("nome", ["utf8_invalido", "json_truncado"])
def test_cli_evaluate_com_manifesto_ilegivel_sai_com_codigo_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], nome: str
) -> None:
    _manifesto(tmp_path / "frozen", CONTEUDOS[nome])
    assert _avaliar(tmp_path) == ExitCode.CONFIG_INVALIDA
    assert f"congelamento_invalido freeze={FREEZE}" in capsys.readouterr().err


def test_cli_evaluate_com_manifesto_que_o_sistema_nega_ler_sai_com_codigo_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    caminho = _manifesto(tmp_path / "frozen", b"{}")
    _negar(monkeypatch, "read_text", caminho)
    assert _avaliar(tmp_path) == ExitCode.CONFIG_INVALIDA
    erro = capsys.readouterr().err
    assert f"congelamento_ilegivel freeze={FREEZE} motivo=PermissionError" in erro
