import subprocess
from pathlib import Path

from sustemporal.runtime_info import ambiente, versao_codigo

RAIZ = Path(__file__).resolve().parents[2]


def test_ambiente_registra_pacotes_e_trava(tmp_path: Path) -> None:
    registro = ambiente(RAIZ)
    assert registro.pacotes["duckdb"] != "ausente"
    assert registro.uv_lock_sha256 is not None
    assert ambiente(tmp_path).uv_lock_sha256 is None


def test_sem_git_o_codigo_e_marcado_sujo(tmp_path: Path) -> None:
    versao = versao_codigo(tmp_path)
    assert versao.commit == "desconhecido"
    assert versao.sujo is True


def _git_local(raiz: Path, *argumentos: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=teste@exemplo.invalid",
            "-c",
            "user.name=teste",
            "-c",
            "commit.gpgsign=false",
            *argumentos,
        ],
        cwd=raiz,
        check=True,
        capture_output=True,
    )


def _repositorio(tmp_path: Path) -> Path:
    raiz = tmp_path / "repo"
    raiz.mkdir()
    _git_local(raiz, "init", "-q")
    (raiz / "modulo.py").write_text("VALOR = 1\n", encoding="utf-8")
    _git_local(raiz, "add", "modulo.py")
    _git_local(raiz, "commit", "-q", "-m", "inicial")
    return raiz


def test_codigo_limpo_nao_tem_hash_de_diferencas(tmp_path: Path) -> None:
    versao = versao_codigo(_repositorio(tmp_path))
    assert versao.sujo is False
    assert versao.diff_sha256 is None


def test_arvores_sujas_diferentes_no_mesmo_commit_tem_hashes_diferentes(tmp_path: Path) -> None:
    raiz = _repositorio(tmp_path)
    (raiz / "modulo.py").write_text("VALOR = 2\n", encoding="utf-8")
    primeira = versao_codigo(raiz)
    (raiz / "modulo.py").write_text("VALOR = 3\n", encoding="utf-8")
    segunda = versao_codigo(raiz)
    assert primeira.commit == segunda.commit
    assert primeira.sujo is segunda.sujo is True
    assert primeira.diff_sha256 is not None
    assert segunda.diff_sha256 is not None
    assert primeira.diff_sha256 != segunda.diff_sha256


def test_hash_de_diferencas_e_deterministico(tmp_path: Path) -> None:
    raiz = _repositorio(tmp_path)
    (raiz / "modulo.py").write_text("VALOR = 2\n", encoding="utf-8")
    assert versao_codigo(raiz) == versao_codigo(raiz)


def test_arquivo_nao_rastreado_entra_no_hash_de_diferencas(tmp_path: Path) -> None:
    raiz = _repositorio(tmp_path)
    novo = raiz / "novo.py"
    novo.write_text("A = 1\n", encoding="utf-8")
    primeira = versao_codigo(raiz)
    novo.write_text("A = 2\n", encoding="utf-8")
    segunda = versao_codigo(raiz)
    assert primeira.sujo is segunda.sujo is True
    assert primeira.diff_sha256 is not None
    assert primeira.diff_sha256 != segunda.diff_sha256


def test_sem_git_nao_ha_hash_de_diferencas(tmp_path: Path) -> None:
    assert versao_codigo(tmp_path).diff_sha256 is None


def test_subdiretorio_ve_as_diferencas_do_repositorio_inteiro(tmp_path: Path) -> None:
    raiz = _repositorio(tmp_path)
    sub = raiz / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("B = 1\n", encoding="utf-8")
    _git_local(raiz, "add", "sub/b.py")
    _git_local(raiz, "commit", "-q", "-m", "sub")
    topo = raiz / "topo.py"
    topo.write_text("T = 1\n", encoding="utf-8")
    primeira = versao_codigo(sub)
    topo.write_text("T = 2\n", encoding="utf-8")
    segunda = versao_codigo(sub)
    assert primeira.diff_sha256 is not None
    assert primeira.diff_sha256 != segunda.diff_sha256
    assert versao_codigo(sub) == versao_codigo(raiz)
