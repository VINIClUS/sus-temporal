import ast
import sys
from pathlib import Path

import pytest
import yaml
from scripts.check_ownership import (
    Dono,
    ErroPropriedade,
    EspecificacaoPropriedade,
    carregar_especificacao,
    dono_do_branch,
    encontrar_violacoes,
    especificacao_de_texto,
)

RAIZ = Path(__file__).resolve().parents[2]
ESPECIFICACAO_REAL = RAIZ / "docs" / "process" / "propriedade.yaml"
CHECADOR = RAIZ / "scripts" / "check_ownership.py"
FLUXO_CI = RAIZ / ".github" / "workflows" / "ci.yml"
_MINIMA = 'donos:\n  S1:\n    branches: ["claude/s1-*"]\n    caminhos: ["src/a/*"]\n'
_EXTRACAO_DA_BASE = (
    'git show "origin/${GITHUB_BASE_REF}:scripts/check_ownership.py" '
    '> "$RUNNER_TEMP/check_ownership.py"'
)
_EXECUCAO_ISOLADA = (
    'uv run --no-project --no-config --with "pyyaml=={versao}" '
    'python "$RUNNER_TEMP/check_ownership.py"'
)


@pytest.fixture
def especificacao() -> EspecificacaoPropriedade:
    return EspecificacaoPropriedade(
        donos={
            "ORQ": Dono(branches=("claude/orq-*",), caminhos=("pyproject.toml", "docs/process/*")),
            "S1": Dono(branches=("claude/s1-*",), caminhos=("src/sustemporal/acquisition/*",)),
            "S2": Dono(branches=("claude/s2-*",), caminhos=("src/sustemporal/ingest/dbc.py",)),
        },
        somente_humanos=("experiments/decisions/*.yaml",),
        excecoes_humanos=("experiments/decisions/MODELO_*.yaml",),
        integradores=("ORQ",),
    )


def test_branch_de_sessao_mapeia_para_dono(especificacao: EspecificacaoPropriedade) -> None:
    assert dono_do_branch("claude/s1-bitemporal", especificacao) == "S1"


def test_branch_desconhecido_nao_tem_dono(especificacao: EspecificacaoPropriedade) -> None:
    assert dono_do_branch("feature/qualquer", especificacao) is None


def test_arquivo_de_outro_dono_e_violacao(especificacao: EspecificacaoPropriedade) -> None:
    violacoes = encontrar_violacoes(["src/sustemporal/ingest/dbc.py"], "S1", especificacao)
    assert violacoes == ["src/sustemporal/ingest/dbc.py"]


def test_arquivo_proprio_e_permitido(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["src/sustemporal/acquisition/fetch.py"]
    assert encontrar_violacoes(alterados, "S1", especificacao) == []


def test_arquivo_sem_dono_e_compartilhado(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["tests/unit/test_fetch.py", "docs/pendencias/T02.md"]
    assert encontrar_violacoes(alterados, "S1", especificacao) == []


def test_integrador_pode_alterar_caminho_de_sessao(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["src/sustemporal/acquisition/fetch.py", "src/sustemporal/ingest/dbc.py"]
    assert encontrar_violacoes(alterados, "ORQ", especificacao) == []


def test_decisao_humana_e_violacao_para_agente(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["experiments/decisions/G0.yaml"]
    assert encontrar_violacoes(alterados, "ORQ", especificacao) == alterados


def test_modelo_de_decisao_e_permitido(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["experiments/decisions/MODELO_G0.yaml"]
    assert encontrar_violacoes(alterados, "S2", especificacao) == []


def test_especificacao_do_repositorio_cobre_todas_as_sessoes() -> None:
    especificacao = carregar_especificacao(RAIZ / "docs" / "process" / "propriedade.yaml")
    assert set(especificacao.donos) == {"ORQ", *(f"S{n}" for n in range(1, 10))}
    assert dono_do_branch("claude/determined-ritchie-b9o2qg", especificacao) == "ORQ"
    assert dono_do_branch("claude/s4-motor-regras", especificacao) == "S4"
    assert encontrar_violacoes(["uv.lock"], "S3", especificacao) == ["uv.lock"]


@pytest.mark.parametrize(
    "trecho",
    [
        "somente_humanos: [yes]\n",
        "somente_humanos: [2020-01-01]\n",
        "reservados_integradores: [1.0]\n",
        "integradores: [null]\n",
        "humanos:\n  branches: [on]\n",
    ],
)
def test_especificacao_recusa_escalar_que_nao_e_texto(trecho: str) -> None:
    with pytest.raises(ErroPropriedade, match="especificacao_invalida"):
        especificacao_de_texto(_MINIMA + trecho)


@pytest.mark.parametrize(
    "texto",
    [
        'donos:\n  S1:\n    branches: [true]\n    caminhos: ["src/a/*"]\n',
        'donos:\n  S1:\n    branches: ["claude/s1-*"]\n    caminhos: [3]\n',
        'donos:\n  1:\n    branches: ["claude/s1-*"]\n    caminhos: ["src/a/*"]\n',
    ],
)
def test_especificacao_recusa_dono_com_escalar_que_nao_e_texto(texto: str) -> None:
    with pytest.raises(ErroPropriedade, match="especificacao_invalida"):
        especificacao_de_texto(texto)


def _erro_ao_ler(texto: str) -> Exception | None:
    try:
        especificacao_de_texto(texto)
    except Exception as erro:
        return erro
    return None


@pytest.mark.parametrize(
    "texto",
    [
        'donos:\n  S1:\n    branches: ["claude/s1-*"]\n',
        "donos: [S1]\n",
        "- lista\n",
        _MINIMA + "humanos: [humano/*]\n",
    ],
)
def test_especificacao_mal_formada_falha_com_erro_de_propriedade(texto: str) -> None:
    assert isinstance(_erro_ao_ler(texto), ErroPropriedade)


def test_decisao_humana_com_outra_caixa_e_violacao(especificacao: EspecificacaoPropriedade) -> None:
    alterados = ["experiments/Decisions/G0.yaml", "EXPERIMENTS/DECISIONS/G1.YAML"]
    assert encontrar_violacoes(alterados, "ORQ", especificacao) == alterados


def test_excecao_de_modelo_nao_vale_com_outra_caixa(
    especificacao: EspecificacaoPropriedade,
) -> None:
    alterados = ["experiments/decisions/modelo_g0.yaml", "experiments/Decisions/MODELO_G0.yaml"]
    assert encontrar_violacoes(alterados, "S2", especificacao) == alterados


def _especificacao_real() -> EspecificacaoPropriedade:
    return carregar_especificacao(ESPECIFICACAO_REAL)


def test_branch_curinga_de_orquestrador_nao_tem_dono() -> None:
    especificacao = _especificacao_real()
    assert dono_do_branch("claude/orq-qualquer", especificacao) is None
    assert dono_do_branch("claude/determined-ritchie-b9o2qg", especificacao) == "ORQ"


@pytest.mark.parametrize(
    "caminho",
    ["experiments/decisions", "experiments/Decisions/G0.yaml", "Experiments/decisions/g1.md"],
)
def test_diretorio_de_decisoes_e_so_humano_em_qualquer_caixa(caminho: str) -> None:
    assert encontrar_violacoes([caminho], "ORQ", _especificacao_real()) == [caminho]


def test_modelos_de_decisao_seguem_permitidos() -> None:
    alterados = ["experiments/decisions/MODELO_G0.yaml", "experiments/decisions/README.md"]
    assert encontrar_violacoes(alterados, "S5", _especificacao_real()) == []


@pytest.mark.parametrize(
    "nome",
    [
        "pytest.toml",
        ".pytest.toml",
        ".pytest.ini",
        "uv.toml",
        "pyrightconfig.json",
        ".pre-commit-config.yaml",
        "noxfile.py",
        ".sonarcloud.properties",
        "sonar-project.properties",
    ],
)
def test_configuracao_de_ferramenta_e_reservada_aos_integradores(nome: str) -> None:
    alterados = [nome, f"src/sustemporal/acquisition/{nome}"]
    especificacao = _especificacao_real()
    assert encontrar_violacoes(alterados, "S1", especificacao) == alterados
    assert encontrar_violacoes(alterados, "ORQ", especificacao) == []


@pytest.mark.parametrize(
    "caminho",
    [
        ".githooks/pre-push",
        "tests/unit/test_hook_pre_push.py",
        "tests/unit/test_hook_mcp_github.py",
        "tests/unit/test_config_heranca.py",
        "tests/unit/test_contratos_vigilancia.py",
    ],
)
def test_githooks_e_testes_deste_pr_sao_do_orquestrador(caminho: str) -> None:
    assert encontrar_violacoes([caminho], "S1", _especificacao_real()) == [caminho]


def test_checador_so_importa_biblioteca_padrao_e_yaml() -> None:
    arvore = ast.parse(CHECADOR.read_text(encoding="utf-8"))
    importados = [no for no in ast.walk(arvore) if isinstance(no, ast.Import | ast.ImportFrom)]
    nomes = {
        alias.name.split(".")[0]
        for no in importados
        if isinstance(no, ast.Import)
        for alias in no.names
    }
    nomes |= {
        no.module.split(".")[0] for no in importados if isinstance(no, ast.ImportFrom) and no.module
    }
    assert not nomes & {"sustemporal", "scripts", "tests"}
    assert nomes <= set(sys.stdlib_module_names) | {"yaml"}
    assert all(no.level == 0 for no in importados if isinstance(no, ast.ImportFrom))


def _versao_travada(pacote: str) -> str:
    trava = (RAIZ / "uv.lock").read_text(encoding="utf-8")
    trecho = trava.split(f'name = "{pacote}"\n', 1)[1]
    return trecho.split('version = "', 1)[1].split('"', 1)[0]


def test_ci_de_pr_roda_o_checador_da_base_antes_de_instalar_o_projeto() -> None:
    passos = yaml.safe_load(FLUXO_CI.read_text(encoding="utf-8"))["jobs"]["ci"]["steps"]
    comandos = [str(passo.get("run", "")) for passo in passos]
    isolada = _EXECUCAO_ISOLADA.format(versao=_versao_travada("pyyaml"))
    indices = [
        indice
        for indice, comando in enumerate(comandos)
        if _EXTRACAO_DA_BASE in comando and isolada in comando
    ]
    assert len(indices) == 1
    assert passos[indices[0]].get("if") == "github.event_name == 'pull_request'"
    assert indices[0] < comandos.index("uv sync --locked") < comandos.index("bash scripts/ci.sh")
