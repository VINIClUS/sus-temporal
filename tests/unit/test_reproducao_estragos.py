"""Estragos de arquivo da varredura do `reproduce` (T14): o estrago e a restauração dele.

`estragado` estraga o arquivo de verdade e o devolve como estava, com ou sem erro no bloco;
`estragado_na_abertura` só faz a abertura falhar, sem tocar no arquivo, e `aberturas` lista o que o
Python abre para ler.
"""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

from sustemporal.reporting.reproduce_leituras import Dano
from tests.fixtures.reproducao_estragos import (
    BYTES_ILEGIVEIS,
    aberturas,
    estragado,
    estragado_na_abertura,
)

if TYPE_CHECKING:
    from pathlib import Path


def _arquivo(pasta: Path, conteudo: bytes = b"a: 1\nb: 2\n") -> Path:
    caminho = pasta / "catalogo.yaml"
    caminho.write_bytes(conteudo)
    caminho.chmod(0o640)
    return caminho


def test_diretorio_no_lugar_do_arquivo_e_o_arquivo_de_volta_depois(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado(caminho, Dano.DIRETORIO):
        assert caminho.is_dir()
        with pytest.raises(IsADirectoryError):
            caminho.read_bytes()
    assert caminho.is_file()
    assert caminho.read_bytes() == b"a: 1\nb: 2\n"
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o640


def test_diretorio_que_a_cadeia_encheu_sai_inteiro_e_o_arquivo_volta(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado(caminho, Dano.DIRETORIO):
        (caminho / "sobra.txt").write_text("x", encoding="utf-8")
    assert caminho.is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["catalogo.yaml"]


def test_sem_permissao_o_arquivo_nao_abre_e_o_modo_volta_depois(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado(caminho, Dano.PERMISSAO):
        assert stat.S_IMODE(caminho.stat().st_mode) == 0
        with pytest.raises(PermissionError):
            caminho.read_bytes()
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o640
    assert caminho.read_bytes() == b"a: 1\nb: 2\n"


def test_texto_com_bytes_ilegiveis_nao_decodifica_como_utf8(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado(caminho, Dano.BYTES):
        assert caminho.read_bytes() == BYTES_ILEGIVEIS
        with pytest.raises(UnicodeDecodeError):
            caminho.read_text(encoding="utf-8")
    assert caminho.read_bytes() == b"a: 1\nb: 2\n"


def test_binario_com_bytes_ilegiveis_fica_com_a_metade_do_arquivo(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path, bytes(range(100)))
    with estragado(caminho, Dano.BYTES, binario=True):
        assert caminho.read_bytes() == bytes(range(50))
    assert caminho.read_bytes() == bytes(range(100))


def test_arquivo_de_um_byte_nao_fica_vazio_ao_truncar(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path, b"x")
    with estragado(caminho, Dano.BYTES, binario=True):
        assert caminho.read_bytes() == b"x"


@pytest.mark.parametrize("dano", list(Dano))
def test_o_arquivo_volta_como_estava_mesmo_com_erro_no_bloco(tmp_path: Path, dano: Dano) -> None:
    caminho = _arquivo(tmp_path)
    with pytest.raises(ZeroDivisionError), estragado(caminho, dano):
        raise ZeroDivisionError
    assert caminho.is_file()
    assert caminho.read_bytes() == b"a: 1\nb: 2\n"
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o640


@pytest.mark.parametrize(
    ("dano", "erro"),
    [
        (Dano.DIRETORIO, IsADirectoryError),
        (Dano.PERMISSAO, PermissionError),
        (Dano.BYTES, UnicodeDecodeError),
    ],
)
def test_a_abertura_estragada_falha_como_o_dano_e_o_arquivo_nao_muda(
    tmp_path: Path, dano: Dano, erro: type[Exception]
) -> None:
    caminho = _arquivo(tmp_path)
    antes = (caminho.read_bytes(), caminho.stat().st_mode, caminho.stat().st_mtime_ns)
    with estragado_na_abertura(caminho, dano), pytest.raises(erro) as falha:
        caminho.read_text(encoding="utf-8")
    assert getattr(falha.value, "filename", None) in (None, str(caminho))
    assert (caminho.read_bytes(), caminho.stat().st_mode, caminho.stat().st_mtime_ns) == antes


def test_a_abertura_estragada_leva_o_nome_do_arquivo_no_erro(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado_na_abertura(caminho, Dano.PERMISSAO), pytest.raises(PermissionError) as falha:
        caminho.open("rb")
    assert falha.value.filename == str(caminho)


def test_so_o_arquivo_estragado_falha_e_a_escrita_dele_segue(tmp_path: Path) -> None:
    caminho, outro = _arquivo(tmp_path), tmp_path / "outro.yaml"
    outro.write_text("x: 1\n", encoding="utf-8")
    with estragado_na_abertura(caminho, Dano.PERMISSAO):
        assert outro.read_text(encoding="utf-8") == "x: 1\n"
        caminho.write_text("novo\n", encoding="utf-8")
        with pytest.raises(PermissionError):
            caminho.read_text(encoding="utf-8")
    assert caminho.read_text(encoding="utf-8") == "novo\n"


def test_a_abertura_falha_em_toda_leitura_do_bloco_e_volta_ao_normal_depois(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with estragado_na_abertura(caminho, Dano.DIRETORIO):
        for _ in range(3):
            with pytest.raises(IsADirectoryError):
                caminho.read_text(encoding="utf-8")
    assert caminho.read_text(encoding="utf-8") == "a: 1\nb: 2\n"


def test_a_abertura_volta_ao_normal_mesmo_com_erro_no_bloco(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with pytest.raises(ZeroDivisionError), estragado_na_abertura(caminho, Dano.BYTES):
        raise ZeroDivisionError
    assert caminho.read_text(encoding="utf-8") == "a: 1\nb: 2\n"


def test_o_caminho_relativo_da_abertura_vale_pelo_absoluto(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caminho = _arquivo(tmp_path)
    monkeypatch.chdir(tmp_path)
    with estragado_na_abertura(caminho, Dano.PERMISSAO), pytest.raises(PermissionError):
        open("catalogo.yaml", encoding="utf-8")  # noqa: SIM115


def test_blocos_aninhados_estragam_cada_um_o_seu_arquivo(tmp_path: Path) -> None:
    primeiro, segundo = _arquivo(tmp_path), tmp_path / "segundo.yaml"
    segundo.write_text("s: 1\n", encoding="utf-8")
    with (
        estragado_na_abertura(primeiro, Dano.PERMISSAO),
        estragado_na_abertura(segundo, Dano.BYTES),
    ):
        with pytest.raises(PermissionError):
            primeiro.read_text(encoding="utf-8")
        with pytest.raises(UnicodeDecodeError):
            segundo.read_text(encoding="utf-8")
    assert primeiro.read_text(encoding="utf-8") == "a: 1\nb: 2\n"
    assert segundo.read_text(encoding="utf-8") == "s: 1\n"


def test_as_aberturas_listam_o_que_se_abre_para_ler_com_o_caminho_absoluto(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    novo = tmp_path / "novo.txt"
    with aberturas() as lidas:
        caminho.read_text(encoding="utf-8")
        novo.write_text("só escrita", encoding="utf-8")
        with caminho.open("ab"):
            pass
    nomes = [nome for nome, _ in lidas]
    assert str(caminho) in nomes
    assert str(novo) not in nomes
    assert dict(lidas)[str(caminho)] in {"r", "a", "ab"}


def test_as_aberturas_so_valem_dentro_do_bloco(tmp_path: Path) -> None:
    caminho = _arquivo(tmp_path)
    with aberturas() as lidas:
        pass
    caminho.read_text(encoding="utf-8")
    assert lidas == []


def test_abertura_com_descritor_de_so_escrita_nao_conta_como_leitura(tmp_path: Path) -> None:
    caminho = tmp_path / "so_escrita.bin"
    with aberturas() as lidas:
        descritor = os.open(caminho, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(descritor)
        descritor = os.open(caminho, os.O_RDONLY)
        os.close(descritor)
    assert [nome for nome, _ in lidas] == [str(caminho)]
