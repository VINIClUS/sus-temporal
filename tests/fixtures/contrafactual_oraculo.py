"""Enumeração completa de referência para mundos SINTETICOS pequenos de um estabelecimento.

Escrita a partir de `docs/method/contrafactuais.md` e `docs/method/model.md` (§4.2), sem importar
a busca de produção. Estado: contagens por CBO do estabelecimento no PF reduzido e presença do
estabelecimento no ST. Veredito da regra estabelecimento–CBO para um CBO: CONFORME com contagem
positiva; senão VIOLACAO se o estabelecimento tem alguma linha no PF; senão INCONCLUSIVO.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

__all__ = ["MundoOraculo", "n_instancias", "solucoes_minimas"]

_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"
_RECLASSIFICAR = "RECLASSIFICAR_CBO_NO_ESTABELECIMENTO"
_CADASTRAR = "CADASTRAR_ESTABELECIMENTO_NO_CNES"
_ORDEM = {_CADASTRAR: 0, _INCLUIR: 1, _RECLASSIFICAR: 1}


@dataclass(frozen=True)
class MundoOraculo:
    pf: dict[str, int]
    st_presente: bool
    cbo_alvo: str
    outros_cbos: tuple[str, ...]
    custos: dict[str, int]
    max_operacoes: int


def _veredito(pf: dict[str, int], cbo: str) -> str:
    if pf.get(cbo, 0) > 0:
        return "CONFORME"
    return "VIOLACAO" if any(n > 0 for n in pf.values()) else "INCONCLUSIVO"


def _instancias(mundo: MundoOraculo) -> list[tuple[str, str]]:
    origens = sorted(c for c, n in mundo.pf.items() if n > 0 and c != mundo.cbo_alvo)
    instancias = [(_INCLUIR, ""), (_CADASTRAR, "")]
    instancias += [(_RECLASSIFICAR, origem) for origem in origens]
    return [i for i in instancias if i[0] in mundo.custos]


def n_instancias(mundo: MundoOraculo) -> int:
    return len(_instancias(mundo))


def _aplicar(
    pf: dict[str, int], st: bool, instancia: tuple[str, str], alvo: str
) -> tuple[dict[str, int], bool] | None:
    op, origem = instancia
    if op == _CADASTRAR:
        return None if st else (pf, True)
    if not st:
        return None
    novo = dict(pf)
    if op == _RECLASSIFICAR:
        if novo.get(origem, 0) <= 0:
            return None
        novo[origem] -= 1
    novo[alvo] = novo.get(alvo, 0) + 1
    return novo, st


def _resolve(mundo: MundoOraculo, combinacao: tuple[tuple[str, str], ...]) -> bool:
    pf, st = dict(mundo.pf), mundo.st_presente
    for instancia in sorted(combinacao, key=lambda i: (_ORDEM[i[0]], i)):
        resultado = _aplicar(pf, st, instancia, mundo.cbo_alvo)
        if resultado is None:
            return False
        pf, st = resultado
    if _veredito(pf, mundo.cbo_alvo) != "CONFORME":
        return False
    return not any(
        _veredito(pf, cbo) == "VIOLACAO" and _veredito(mundo.pf, cbo) != "VIOLACAO"
        for cbo in mundo.outros_cbos
    )


def solucoes_minimas(mundo: MundoOraculo) -> tuple[int | None, set[frozenset[tuple[str, str]]]]:
    """Menor custo entre combinações de até `max_operacoes` instâncias e todas as que o atingem."""
    instancias = _instancias(mundo)
    solucoes: dict[frozenset[tuple[str, str]], int] = {}
    for tamanho in range(1, mundo.max_operacoes + 1):
        for combinacao in combinations(instancias, tamanho):
            if _resolve(mundo, combinacao):
                custo = sum(mundo.custos[op] for op, _ in combinacao)
                solucoes[frozenset(combinacao)] = custo
    if not solucoes:
        return None, set()
    menor = min(solucoes.values())
    return menor, {s for s, c in solucoes.items() if c == menor}
