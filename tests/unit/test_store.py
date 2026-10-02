import hashlib
from pathlib import Path

import pytest

from sustemporal.errors import FalhaOperacionalErro
from sustemporal.store import caminho_conteudo, promover_sem_sobrescrever


def _temporario(tmp_path: Path, nome: str, conteudo: bytes) -> Path:
    caminho = tmp_path / "tmp" / nome
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def test_caminho_e_enderecado_pelo_hash(tmp_path: Path) -> None:
    sha = hashlib.sha256(b"x").hexdigest()
    assert caminho_conteudo(tmp_path, sha, ".DBC") == tmp_path / "sha256" / sha[:2] / f"{sha}.dbc"


def test_promove_conteudo_novo(tmp_path: Path) -> None:
    destino = tmp_path / "raw" / "a.dbc"
    assert promover_sem_sobrescrever(_temporario(tmp_path, "a", b"abc"), destino) is True
    assert destino.read_bytes() == b"abc"


def test_conteudo_repetido_nao_regrava(tmp_path: Path) -> None:
    destino = tmp_path / "raw" / "a.dbc"
    promover_sem_sobrescrever(_temporario(tmp_path, "a", b"abc"), destino)
    segundo = _temporario(tmp_path, "b", b"abc")
    assert promover_sem_sobrescrever(segundo, destino) is False
    assert not segundo.exists()


def test_nunca_sobrescreve_original_divergente(tmp_path: Path) -> None:
    destino = tmp_path / "raw" / "a.dbc"
    promover_sem_sobrescrever(_temporario(tmp_path, "a", b"abc"), destino)
    with pytest.raises(FalhaOperacionalErro):
        promover_sem_sobrescrever(_temporario(tmp_path, "b", b"xyz"), destino)
    assert destino.read_bytes() == b"abc"
