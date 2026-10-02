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
