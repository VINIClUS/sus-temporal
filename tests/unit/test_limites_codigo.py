import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
DIRETORIOS = ("src", "scripts")
MAX_LINHAS_FUNCAO = 50
MAX_LINHAS_ARQUIVO = 500
MAX_ANINHAMENTO = 3
_BLOCOS = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.TryStar,
    ast.Match,
)


def _arquivos() -> list[Path]:
    return sorted(p for d in DIRETORIOS for p in (RAIZ / d).rglob("*.py"))


def _funcoes(arvore: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            yield no


def _profundidade(instrucoes: list[ast.stmt], nivel: int) -> int:
    maior = nivel
    for instrucao in instrucoes:
        if isinstance(instrucao, _BLOCOS):
            maior = max(maior, _profundidade_bloco(instrucao, nivel + 1))
    return maior


def _profundidade_bloco(no: ast.stmt, nivel: int) -> int:
    if isinstance(no, ast.If):
        corpo = _profundidade(no.body, nivel)
        senao = no.orelse
        elif_ = len(senao) == 1 and isinstance(senao[0], ast.If)
        if elif_ and senao[0].col_offset == no.col_offset:
            return max(corpo, _profundidade_bloco(senao[0], nivel))
        return max(corpo, _profundidade(no.orelse, nivel))
    if isinstance(no, ast.Match):
        return max((_profundidade(caso.body, nivel) for caso in no.cases), default=nivel)
    if isinstance(no, ast.Try | ast.TryStar):
        partes = [no.body, no.orelse, no.finalbody, *(h.body for h in no.handlers)]
        return max(_profundidade(parte, nivel) for parte in partes)
    partes = [getattr(no, "body", []), getattr(no, "orelse", [])]
    return max(_profundidade(parte, nivel) for parte in partes)


@pytest.mark.parametrize("arquivo", _arquivos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_arquivo_respeita_limites(arquivo: Path) -> None:
    texto = arquivo.read_text(encoding="utf-8")
    assert len(texto.splitlines()) <= MAX_LINHAS_ARQUIVO
    arvore = ast.parse(texto)
    for funcao in _funcoes(arvore):
        linhas = (funcao.end_lineno or funcao.lineno) - funcao.lineno + 1
        assert linhas <= MAX_LINHAS_FUNCAO, f"funcao_longa nome={funcao.name} linhas={linhas}"
        profundidade = _profundidade(funcao.body, 0)
        assert profundidade <= MAX_ANINHAMENTO, f"aninhamento nome={funcao.name}"


def test_detector_de_aninhamento_conta_elif_no_mesmo_nivel() -> None:
    fonte = (
        "def f(x):\n    if x:\n        pass\n    elif x > 1:\n        pass\n"
        "    else:\n        pass\n"
    )
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 1


def test_detector_de_aninhamento_acusa_quatro_niveis() -> None:
    fonte = (
        "def f(x):\n    for a in x:\n        if a:\n            with a:\n"
        "                while a:\n                    pass\n"
    )
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 4


def test_detector_conta_else_seguido_de_if_como_aninhamento() -> None:
    fonte = "def f(x):\n    if x:\n        pass\n    else:\n        if x > 1:\n            pass\n"
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 2


def test_detector_conta_try_e_match() -> None:
    fonte = (
        "def f(x):\n    try:\n        match x:\n            case 1:\n"
        "                for i in x:\n                    pass\n    except ValueError:\n"
        "        pass\n"
    )
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 3


_SUPRESSOES_PROIBIDAS = re.compile(
    r"#\s*(ruff:\s*noqa|mypy:\s*ignore-errors|type:\s*ignore\s*$|noqa:[^\n]*(C901|PLR09))",
    re.MULTILINE,
)


@pytest.mark.parametrize("arquivo", _arquivos(), ids=lambda p: str(p.relative_to(RAIZ)))
def test_arquivo_nao_desliga_limites(arquivo: Path) -> None:
    texto = arquivo.read_text(encoding="utf-8")
    assert not _SUPRESSOES_PROIBIDAS.search(texto), "supressao_de_limite_proibida"


SONAR = RAIZ / ".sonarcloud.properties"
_PREFIXO_SUPRESSAO_SONAR = "sonar.issue.ignore.multicriteria"


def _propriedades_sonar() -> dict[str, str]:
    pares = (
        linha.partition("=")
        for linha in SONAR.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.lstrip().startswith("#")
    )
    return {chave.strip(): valor.strip() for chave, _, valor in pares}


def test_supressao_do_sonar_e_escopada_por_regra_e_caminho_com_revisao() -> None:
    propriedades = _propriedades_sonar()
    grupos = [g.strip() for g in propriedades.get(_PREFIXO_SUPRESSAO_SONAR, "").split(",")]
    escopos = {
        (
            propriedades.get(f"{_PREFIXO_SUPRESSAO_SONAR}.{grupo}.ruleKey", "*"),
            propriedades.get(f"{_PREFIXO_SUPRESSAO_SONAR}.{grupo}.resourceKey", "*"),
        )
        for grupo in grupos
        if grupo
    }
    assert ("python:S5332", "src/sustemporal/acquisition/transport.py") in escopos
    assert not any("*" in regra or "*" in caminho for regra, caminho in escopos)
    assert re.search(r"Revisar em \d{4}-\d{2}-\d{2}", SONAR.read_text(encoding="utf-8"))
