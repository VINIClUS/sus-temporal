import subprocess
from pathlib import Path

import pytest

from scripts.check_ownership import arquivos_alterados, branch_atual, verificar

ESPECIFICACAO = """versao: 1
integradores: ["ORQ"]
reservados_integradores: ["ruff.toml", "pytest.ini", "conftest.py"]
donos:
  ORQ:
    branches: ["claude/orq-*"]
    caminhos: ["docs/process/*"]
  S1:
    branches: ["claude/s1-*"]
    caminhos: ["src/a/*"]
  S2:
    branches: ["claude/s2-*"]
    caminhos: ["src/b/*", "catalog/territorio/*"]
somente_humanos: ["experiments/decisions/*"]
excecoes_humanos: ["experiments/decisions/MODELO_*"]
"""


def _git(repo: Path, *argumentos: str) -> str:
    comando = ["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@t"]
    resultado = subprocess.run(
        [*comando, *argumentos], cwd=repo, check=True, capture_output=True, text=True
    )
    return resultado.stdout


def _gravar(repo: Path, caminho: str, conteudo: str = "x\n") -> None:
    alvo = repo / caminho
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(conteudo, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _gravar(tmp_path, "docs/process/propriedade.yaml", ESPECIFICACAO)
    _gravar(tmp_path, "src/b/existente.py")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _branch_com(repo: Path, branch: str, caminhos: list[str]) -> None:
    _git(repo, "checkout", "-q", "-b", branch)
    for caminho in caminhos:
        _gravar(repo, caminho)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "mudanca")


def test_caminho_com_acento_nao_escapa_da_regra(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["catalog/territorio/municípios.yaml"])
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_lista_de_alterados_preserva_acentos(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["src/a/decisão.py"])
    ponto = _git(repo, "merge-base", "HEAD", "main").strip()
    assert arquivos_alterados(repo, ponto) == ["src/a/decisão.py"]


def test_renomear_arquivo_de_outro_dono_e_violacao(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    (repo / "src" / "a").mkdir(parents=True)
    _git(repo, "mv", "src/b/existente.py", "src/a/movido.py")
    _git(repo, "commit", "-q", "-m", "mv")
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_apagar_arquivo_de_outro_dono_e_violacao(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    _git(repo, "rm", "-q", "src/b/existente.py")
    _git(repo, "commit", "-q", "-m", "rm")
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_branch_de_agente_sem_dono_falha(repo: Path) -> None:
    _branch_com(repo, "claude/brave-turing-x1y2", ["src/a/x.py"])
    assert verificar(repo, "claude/brave-turing-x1y2", "main") == 1


def test_branch_humano_sem_dono_nao_e_verificado(repo: Path) -> None:
    _branch_com(repo, "decisao-g0", ["experiments/decisions/G0.yaml"])
    assert verificar(repo, "decisao-g0", "main") == 0


def test_alteracao_propria_passa(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["src/a/novo.py", "tests/unit/test_novo.py"])
    assert verificar(repo, "claude/s1-x", "main") == 0


def test_arquivo_reservado_na_propria_area_e_violacao(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["src/a/ruff.toml"])
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_configuracao_de_teste_na_raiz_e_violacao(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["pytest.ini"])
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_decisao_humana_em_qualquer_formato_e_violacao(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["experiments/decisions/G0.md"])
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_regras_vem_da_base_e_nao_do_branch(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/s1-x")
    afrouxada = ESPECIFICACAO.replace('caminhos: ["src/a/*"]', 'caminhos: ["src/a/*", "src/b/*"]')
    _gravar(repo, "docs/process/propriedade.yaml", afrouxada)
    _gravar(repo, "src/b/existente.py", "alterado\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "afrouxa")
    assert verificar(repo, "claude/s1-x", "main") == 1


def test_base_ausente_falha_com_erro_explicito(repo: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["src/a/novo.py"])
    with pytest.raises(Exception, match="base_ausente"):
        verificar(repo, "claude/s1-x", "origin/nao-existe")


def test_variavel_de_ambiente_define_o_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROPRIEDADE_BRANCH", "claude/s2-y")
    monkeypatch.setenv("GITHUB_HEAD_REF", "claude/s1-x")
    assert branch_atual(repo) == "claude/s2-y"
