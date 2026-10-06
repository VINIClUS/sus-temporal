"""Arquivo local que a reprodução não consegue ler: erro de entrada, nunca traceback (T14).

Diretório no lugar do arquivo, falta de permissão, bytes que não decodificam e catálogo ausente ou
inválido saem da cadeia como `ConfigInvalida` (saída 2) com `chave=valor`, ou como falha
operacional (saída 5) se o arquivo é do destino da própria reprodução; qualquer outra exceção
passa sem tradução, para a falha de programação não virar erro de entrada.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pytest

from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro, RedeProibida
from sustemporal.reporting.reproduce_leitura import arquivo_sob, entradas_legiveis
from sustemporal.reporting.reproduce_leituras import Dano
from sustemporal.rules.catalog import CatalogoInvalido, carregar_esquema
from tests.fixtures.reproducao_estragos import estragado

if TYPE_CHECKING:
    from pathlib import Path

MENSAGEM = re.compile(r"^reproduce_entrada_ilegivel arquivo=\S+ erro=\w+ onde=\S+$")
FALHAS_DE_LEITURA = [
    pytest.param(IsADirectoryError(21, "Is a directory", "/x/a.yaml"), id="diretorio"),
    pytest.param(PermissionError(13, "Permission denied", "/x/a.yaml"), id="permissao"),
    pytest.param(FileNotFoundError(2, "No such file", "/x/a.yaml"), id="ausente"),
    pytest.param(OSError(5, "Input/output error", "/x/a.yaml"), id="entrada_e_saida"),
    pytest.param(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), id="bytes"),
    pytest.param(CatalogoInvalido("esquema_ausente x"), id="catalogo_invalido"),
]
OUTRAS = [
    pytest.param(ValueError("x"), id="value_error"),
    pytest.param(KeyError("x"), id="key_error"),
    pytest.param(RuntimeError("x"), id="runtime_error"),
    pytest.param(ConfigInvalida("config_x"), id="config_invalida"),
    pytest.param(FalhaOperacionalErro("falha_x"), id="falha_operacional"),
    pytest.param(RedeProibida("rede_x"), id="rede_proibida"),
]


@pytest.mark.parametrize("erro", FALHAS_DE_LEITURA)
def test_falha_de_leitura_que_a_cadeia_nao_tratou_vira_erro_de_entrada(
    tmp_path: Path, erro: Exception
) -> None:
    with pytest.raises(ConfigInvalida) as saida, entradas_legiveis(tmp_path / "saida"):
        raise erro
    assert MENSAGEM.match(str(saida.value)), str(saida.value)
    assert f"erro={type(erro).__name__} " in str(saida.value)
    assert saida.value.__cause__ is erro


def test_a_mensagem_traz_o_arquivo_do_erro_e_sem_arquivo_traz_o_hifen(tmp_path: Path) -> None:
    com_arquivo = PermissionError(13, "Permission denied", "/x/catalogo.yaml")
    sem_arquivo = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    mensagens = []
    for erro in (com_arquivo, sem_arquivo):
        with pytest.raises(ConfigInvalida) as saida, entradas_legiveis(tmp_path):
            raise erro
        mensagens.append(str(saida.value))
    assert mensagens[0].startswith("reproduce_entrada_ilegivel arquivo=/x/catalogo.yaml erro=")
    assert mensagens[1].startswith("reproduce_entrada_ilegivel arquivo=- erro=UnicodeDecodeError")


def test_a_mensagem_diz_a_funcao_do_projeto_que_estava_lendo(tmp_path: Path) -> None:
    with (
        pytest.raises(ConfigInvalida, match=r"onde=rules\.catalog\.carregar_esquema$"),
        entradas_legiveis(tmp_path / "saida"),
    ):
        carregar_esquema("nao_existe", tmp_path)


def test_a_funcao_do_projeto_e_a_mais_funda_da_pilha_e_nao_a_primeira(tmp_path: Path) -> None:
    esquema = tmp_path / "x.yaml"
    esquema.write_text("a: 1\n", encoding="utf-8")
    with (
        estragado(esquema, Dano.BYTES),
        pytest.raises(ConfigInvalida, match=r"erro=UnicodeDecodeError onde=yamlio\.carregar_yaml$"),
        entradas_legiveis(tmp_path / "saida"),
    ):
        carregar_esquema("x", tmp_path)


def test_a_mensagem_sem_funcao_do_projeto_traz_o_hifen(tmp_path: Path) -> None:
    with pytest.raises(ConfigInvalida, match=r"onde=-$"), entradas_legiveis(tmp_path):
        raise PermissionError(13, "Permission denied", "/x/a.yaml")


def test_arquivo_do_destino_que_nao_abre_e_falha_operacional(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    erro = PermissionError(13, "Permission denied", str(saida / "runs" / "val_1" / "r.json"))
    with pytest.raises(FalhaOperacionalErro) as falha, entradas_legiveis(saida):
        raise erro
    assert str(falha.value).startswith("reproduce_saida_ilegivel arquivo=")
    assert not isinstance(falha.value, ConfigInvalida)
    assert falha.value.__cause__ is erro


def test_arquivo_fora_do_destino_com_o_mesmo_prefixo_e_entrada(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    vizinho = tmp_path / "saida_antiga" / "r.json"
    with pytest.raises(ConfigInvalida), entradas_legiveis(saida):
        raise PermissionError(13, "Permission denied", str(vizinho))


@pytest.mark.parametrize("erro", OUTRAS)
def test_excecao_que_nao_e_de_leitura_passa_sem_traducao(tmp_path: Path, erro: Exception) -> None:
    with pytest.raises(type(erro)) as saida, entradas_legiveis(tmp_path):
        raise erro
    assert saida.value is erro


def test_sem_erro_o_bloco_roda_inteiro_e_nada_e_traduzido(tmp_path: Path) -> None:
    passos = []
    with entradas_legiveis(tmp_path):
        passos.append("dentro")
    assert passos == ["dentro"]


def test_a_traducao_registra_uma_linha_de_log_com_o_arquivo_e_o_erro(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    erro = IsADirectoryError(21, "Is a directory", "/x/a.yaml")
    with (
        caplog.at_level(logging.WARNING, logger="sustemporal.reporting.reproduce_leitura"),
        pytest.raises(ConfigInvalida),
        entradas_legiveis(tmp_path),
    ):
        raise erro
    assert caplog.messages == [
        "arquivo_ilegivel arquivo=/x/a.yaml erro=IsADirectoryError onde=-",
    ]


def test_arquivo_sob_da_o_caminho_relativo_a_raiz_em_texto_posix(tmp_path: Path) -> None:
    erro = PermissionError(13, "Permission denied", str(tmp_path / "raw" / "ab" / "x.dbc"))
    assert arquivo_sob(erro, tmp_path) == "raw/ab/x.dbc"


def test_arquivo_sob_nao_confunde_pasta_irma_de_mesmo_prefixo(tmp_path: Path) -> None:
    erro = PermissionError(13, "Permission denied", str(tmp_path / "dados2" / "x.dbc"))
    assert arquivo_sob(erro, tmp_path / "dados") is None


def test_arquivo_sob_de_arquivo_fora_da_raiz_ou_sem_arquivo_e_nulo(tmp_path: Path) -> None:
    fora = PermissionError(13, "Permission denied", "/outro/x.dbc")
    sem_arquivo = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    assert arquivo_sob(fora, tmp_path) is None
    assert arquivo_sob(sem_arquivo, tmp_path) is None
    assert arquivo_sob(OSError("sem nome"), tmp_path) is None


def test_arquivo_sob_aceita_o_nome_em_bytes(tmp_path: Path) -> None:
    erro = PermissionError(13, "Permission denied", bytes(tmp_path / "a" / "b.dbc"))
    assert arquivo_sob(erro, tmp_path) == "a/b.dbc"


def test_arquivo_sob_resolve_caminho_relativo_pelo_diretorio_de_trabalho(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    erro = PermissionError(13, "Permission denied", "dados/raw/x.dbc")
    assert arquivo_sob(erro, tmp_path / "dados") == "raw/x.dbc"
