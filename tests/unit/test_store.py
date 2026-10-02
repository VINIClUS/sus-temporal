import errno
import hashlib
import os
from pathlib import Path

import pytest

from sustemporal.errors import FalhaOperacionalErro
from sustemporal.store import caminho_conteudo, promover_sem_sobrescrever

ABC = b"abc"
SHA_ABC = hashlib.sha256(ABC).hexdigest()
SHA_XYZ = hashlib.sha256(b"xyz").hexdigest()


def _temporario(tmp_path: Path, nome: str, conteudo: bytes) -> Path:
    caminho = tmp_path / "tmp" / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def _destino(tmp_path: Path, conteudo: bytes = ABC) -> Path:
    return caminho_conteudo(tmp_path / "raw", hashlib.sha256(conteudo).hexdigest(), "dbc")


def _gravar(caminho: Path, conteudo: bytes) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def test_caminho_e_enderecado_pelo_hash(tmp_path: Path) -> None:
    sha = hashlib.sha256(b"x").hexdigest()
    assert caminho_conteudo(tmp_path, sha, ".DBC") == tmp_path / "sha256" / sha[:2] / f"{sha}.dbc"


@pytest.mark.parametrize(
    "sha256", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "../" + "a" * 61, "", f"{SHA_ABC}\n"]
)
def test_caminho_de_conteudo_rejeita_sha256_invalido(tmp_path: Path, sha256: str) -> None:
    with pytest.raises(ValueError, match="sha256_invalido"):
        caminho_conteudo(tmp_path, sha256, "dbc")


@pytest.mark.parametrize(
    "extensao", ["", ".", "d/c", "../dbc", "db c", "dbc\n", "abcdefghi", "dé", "d\\c"]
)
def test_caminho_de_conteudo_rejeita_extensao_invalida(tmp_path: Path, extensao: str) -> None:
    with pytest.raises(ValueError, match="extensao_invalida"):
        caminho_conteudo(tmp_path, SHA_ABC, extensao)


def test_promove_conteudo_novo(tmp_path: Path) -> None:
    destino = _destino(tmp_path)
    assert promover_sem_sobrescrever(_temporario(tmp_path, "a", ABC), destino) is True
    assert destino.read_bytes() == ABC


def test_conteudo_repetido_nao_regrava(tmp_path: Path) -> None:
    destino = _destino(tmp_path)
    promover_sem_sobrescrever(_temporario(tmp_path, "a", ABC), destino)
    segundo = _temporario(tmp_path, "b", ABC)
    assert promover_sem_sobrescrever(segundo, destino) is False
    assert not segundo.exists()


def test_nunca_sobrescreve_original_divergente(tmp_path: Path) -> None:
    destino = _gravar(_destino(tmp_path), b"corrompido")
    temporario = _temporario(tmp_path, "a", ABC)
    with pytest.raises(FalhaOperacionalErro, match="destino_com_conteudo_divergente"):
        promover_sem_sobrescrever(temporario, destino)
    assert destino.read_bytes() == b"corrompido"
    assert temporario.read_bytes() == ABC


@pytest.mark.parametrize(
    "relativo",
    [
        "raw/a.dbc",
        f"raw/{SHA_ABC}.dbc",
        f"raw/sha256/{SHA_ABC[:2]}/{SHA_XYZ}.dbc",
        f"raw/sha256/{SHA_XYZ[:2]}/{SHA_ABC}.dbc",
        f"raw/outro/{SHA_ABC[:2]}/{SHA_ABC}.dbc",
        f"raw/sha256/{SHA_ABC[:2]}/{SHA_ABC}.DBC",
        f"raw/sha256/{SHA_ABC[:2]}/{SHA_ABC}",
    ],
)
def test_recusa_destino_que_nao_e_caminho_de_conteudo_do_temporario(
    tmp_path: Path, relativo: str
) -> None:
    temporario = _temporario(tmp_path, "a", ABC)
    destino = tmp_path / relativo
    with pytest.raises(FalhaOperacionalErro, match="destino_nao_corresponde_ao_conteudo"):
        promover_sem_sobrescrever(temporario, destino)
    assert temporario.read_bytes() == ABC
    assert not destino.exists()


def test_recusa_promover_arquivo_sobre_si_mesmo(tmp_path: Path) -> None:
    destino = _gravar(_destino(tmp_path), ABC)
    pelo_pai = destino.parent / ".." / destino.parent.name / destino.name
    for temporario in (destino, pelo_pai):
        with pytest.raises(FalhaOperacionalErro, match="temporario_e_destino_sao_o_mesmo_arquivo"):
            promover_sem_sobrescrever(temporario, destino)
        assert destino.read_bytes() == ABC


@pytest.mark.parametrize("alvo_existe", [True, False])
def test_recusa_destino_que_e_link_simbolico(tmp_path: Path, alvo_existe: bool) -> None:
    alvo = tmp_path / "fora.dbc"
    if alvo_existe:
        alvo.write_bytes(ABC)
    destino = _destino(tmp_path)
    destino.parent.mkdir(parents=True)
    destino.symlink_to(alvo)
    temporario = _temporario(tmp_path, "a", ABC)
    with pytest.raises(FalhaOperacionalErro, match="destino_e_link_simbolico"):
        promover_sem_sobrescrever(temporario, destino)
    assert temporario.read_bytes() == ABC
    assert destino.is_symlink()


def test_link_entre_dispositivos_vira_falha_operacional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _link_entre_dispositivos(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

    monkeypatch.setattr(os, "link", _link_entre_dispositivos)
    temporario = _temporario(tmp_path, "a", ABC)
    with pytest.raises(FalhaOperacionalErro, match="promocao_falhou"):
        promover_sem_sobrescrever(temporario, _destino(tmp_path))
    assert temporario.read_bytes() == ABC


def test_temporario_ausente_vira_falha_operacional(tmp_path: Path) -> None:
    with pytest.raises(FalhaOperacionalErro, match="promocao_falhou"):
        promover_sem_sobrescrever(tmp_path / "ausente", _destino(tmp_path))


def test_promocao_sincroniza_arquivo_e_diretorio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sincronizados: list[tuple[int, int]] = []
    fsync_original = os.fsync

    def _registrar(descritor: int) -> None:
        estado = os.fstat(descritor)
        sincronizados.append((estado.st_dev, estado.st_ino))
        fsync_original(descritor)

    monkeypatch.setattr(os, "fsync", _registrar)
    destino = _destino(tmp_path)
    assert promover_sem_sobrescrever(_temporario(tmp_path, "a", ABC), destino) is True
    esperados = {
        (estado.st_dev, estado.st_ino) for estado in (destino.stat(), destino.parent.stat())
    }
    assert esperados <= set(sincronizados)
