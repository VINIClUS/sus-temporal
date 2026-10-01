import ast
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
        if len(no.orelse) == 1 and isinstance(no.orelse[0], ast.If):
            return max(corpo, _profundidade_bloco(no.orelse[0], nivel))
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
    fonte = "def f(x):\n    if x:\n        pass\n    elif x > 1:\n        pass\n    else:\n        pass\n"
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 1


def test_detector_de_aninhamento_acusa_quatro_niveis() -> None:
    fonte = (
        "def f(x):\n    for a in x:\n        if a:\n            with a:\n"
        "                while a:\n                    pass\n"
    )
    funcao = next(_funcoes(ast.parse(fonte)))
    assert _profundidade(funcao.body, 0) == 4
