import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.check_ownership import arquivos_alterados, branch_atual, verificar

RAIZ = Path(__file__).resolve().parents[2]
CHECADOR = RAIZ / "scripts" / "check_ownership.py"
ESPECIFICACAO = """versao: 1
integradores: ["ORQ"]
reservados_integradores: ["ruff.toml", "pytest.ini", "conftest.py"]
humanos:
  branches: ["humano/*"]
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
somente_humanos: ["experiments/decisions", "experiments/decisions/*"]
excecoes_humanos: ["experiments/decisions/MODELO_*"]
"""
_CONTEXTO = (
    "PROPRIEDADE_BRANCH",
    "GITHUB_EVENT_NAME",
    "GITHUB_HEAD_REF",
    "GITHUB_BASE_REF",
    "GIT_DIR",
    "GIT_WORK_TREE",
)
_PR = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"}


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
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
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


def test_branch_humano_declarado_nao_e_verificado(repo: Path) -> None:
    _branch_com(repo, "humano/decisao-g0", ["experiments/decisions/G0.yaml"])
    assert verificar(repo, "humano/decisao-g0", "main") == 0


def test_branch_sem_dono_fora_de_humanos_falha_em_pr(repo: Path) -> None:
    _branch_com(repo, "decisao-g0", ["experiments/decisions/G0.yaml"])
    assert verificar(repo, "decisao-g0", "main") == 1


def test_branches_humanos_vem_do_mapa_da_base(repo: Path) -> None:
    variante = ESPECIFICACAO.replace('branches: ["humano/*"]', 'branches: ["pesquisador/*"]')
    _gravar(repo, "docs/process/propriedade.yaml", variante)
    _git(repo, "commit", "-q", "-am", "humanos")
    _branch_com(repo, "pesquisador/g0", ["experiments/decisions/G0.yaml"])
    assert verificar(repo, "pesquisador/g0", "main") == 0
    assert verificar(repo, "humano/g0", "main") == 1


def test_decisao_com_caixa_trocada_e_violacao_ate_para_integrador(repo: Path) -> None:
    _branch_com(repo, "claude/orq-x", ["experiments/Decisions/G0.yaml"])
    assert verificar(repo, "claude/orq-x", "main") == 1


def test_arquivo_no_lugar_do_diretorio_de_decisoes_e_violacao(repo: Path) -> None:
    _branch_com(repo, "claude/orq-x", ["experiments/decisions"])
    assert verificar(repo, "claude/orq-x", "main") == 1


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


def test_variavel_de_ambiente_define_o_branch(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPRIEDADE_BRANCH", "claude/s2-y")
    monkeypatch.setenv("GITHUB_HEAD_REF", "claude/s1-x")
    assert branch_atual(repo) == "claude/s2-y"


def test_especificacao_real_reprova_branch_sem_dono_e_aceita_humano(repo: Path) -> None:
    real = (RAIZ / "docs" / "process" / "propriedade.yaml").read_text(encoding="utf-8")
    _gravar(repo, "docs/process/propriedade.yaml", real)
    _git(repo, "commit", "-q", "-am", "especificacao real")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _branch_com(repo, "humano/g0", ["experiments/decisions/G0.yaml"])
    assert verificar(repo, "humano/g0", "origin/main") == 0
    _git(repo, "checkout", "-q", "main")
    _branch_com(repo, "feature-x", ["docs/pendencias/T02.md"])
    assert verificar(repo, "feature-x", "origin/main") == 1


@pytest.fixture
def checador(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destino = tmp_path_factory.mktemp("runner_temp") / "check_ownership.py"
    shutil.copy(CHECADOR, destino)
    return destino


def _checar(checador: Path, repo: Path, **variaveis: str) -> subprocess.CompletedProcess[str]:
    ambiente = {chave: valor for chave, valor in os.environ.items() if chave not in _CONTEXTO}
    ambiente |= variaveis
    return subprocess.run(
        [sys.executable, str(checador)],
        cwd=repo,
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )


def test_checador_copiado_para_fora_de_scripts_usa_o_repositorio_atual(
    repo: Path, checador: Path
) -> None:
    _branch_com(repo, "claude/s1-x", ["src/a/novo.py"])
    resultado = _checar(checador, repo, GITHUB_HEAD_REF="claude/s1-x", **_PR)
    assert resultado.returncode == 0, resultado.stderr
    assert "propriedade_verificada dono=S1 violacoes=0" in resultado.stderr


def test_checador_copiado_reprova_arquivo_de_outro_dono(repo: Path, checador: Path) -> None:
    _branch_com(repo, "claude/s1-x", ["src/b/novo.py"])
    resultado = _checar(checador, repo, GITHUB_HEAD_REF="claude/s1-x", **_PR)
    assert resultado.returncode == 1
    assert "propriedade_violada dono=S1 caminho=src/b/novo.py" in resultado.stderr


def test_checador_em_pr_reprova_branch_sem_dono(repo: Path, checador: Path) -> None:
    _branch_com(repo, "feature-x", ["docs/pendencias/T02.md"])
    resultado = _checar(checador, repo, GITHUB_HEAD_REF="feature-x", **_PR)
    assert resultado.returncode == 1
    assert "propriedade_violada motivo=branch_sem_dono branch=feature-x" in resultado.stderr


def test_checador_em_pr_aceita_branch_humano(repo: Path, checador: Path) -> None:
    _branch_com(repo, "humano/g0", ["experiments/decisions/G0.yaml"])
    resultado = _checar(checador, repo, GITHUB_HEAD_REF="humano/g0", **_PR)
    assert resultado.returncode == 0, resultado.stderr
    assert "propriedade_ignorada motivo=branch_humano branch=humano/g0" in resultado.stderr


def test_propriedade_branch_vale_como_contexto_de_pr(repo: Path, checador: Path) -> None:
    _branch_com(repo, "feature-x", ["docs/pendencias/T02.md"])
    resultado = _checar(checador, repo, PROPRIEDADE_BRANCH="feature-x")
    assert resultado.returncode == 1
    assert "motivo=branch_sem_dono branch=feature-x" in resultado.stderr


def test_checador_fora_de_pr_ignora_branch_local_sem_dono(repo: Path, checador: Path) -> None:
    _branch_com(repo, "feature-x", ["docs/pendencias/T02.md"])
    resultado = _checar(checador, repo)
    assert resultado.returncode == 0, resultado.stderr
    assert "propriedade_ignorada motivo=fora_de_pr branch=feature-x" in resultado.stderr


def test_checador_fora_de_pr_reprova_branch_de_agente_sem_dono(repo: Path, checador: Path) -> None:
    _branch_com(repo, "claude/brave-x", ["docs/pendencias/T02.md"])
    resultado = _checar(checador, repo)
    assert resultado.returncode == 1
    assert "motivo=branch_sem_dono branch=claude/brave-x" in resultado.stderr


def test_checador_ignora_evento_push(repo: Path, checador: Path) -> None:
    resultado = _checar(checador, repo, GITHUB_EVENT_NAME="push")
    assert resultado.returncode == 0, resultado.stderr
    assert "propriedade_ignorada motivo=push" in resultado.stderr
