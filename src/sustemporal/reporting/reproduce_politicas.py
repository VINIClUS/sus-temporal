"""Política de cada método como a execução congelada a usou (T14).

O `validate` resolve a política de uma execução por `config.politica_id` (a do catálogo, só do
método dela) ou, sem ele, pela padrão do método. A reprodução não pode aplicar a mesma
`politica_id` da config aos três métodos nem deixar a padrão onde o congelamento usou outra: cada
método é refeito com a política da entrada de validação original (`split/insumos`), conferida
contra o manifesto e contra a execução registrada. Política que não se resolve ou não se confere
é um problema da política congelada (item `insumos:<politica>` inconclusivo), nunca erro de
configuração nem divergência.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.base import hash_canonico
from sustemporal.errors import ConfigInvalida
from sustemporal.rules.insumos import METODOS_DE_VALIDACAO, politica_padrao
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.contracts.temporal import MetodoId, PoliticaTemporal
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = ["DIRETORIO_POLITICAS", "PoliticasCongeladas", "politicas_congeladas"]

_INDISPONIVEL = "politica_congelada_indisponivel"
_ALTERADA = "politica_congelada_alterada"
_AMBIGUA = "politica_congelada_ambigua"
_OUTRO_ID = "politica_congelada_com_outro_id"
_REGISTRADA = "politica_registrada_diferente"


@dataclass(frozen=True)
class PoliticasCongeladas:
    """`config.politica_id` que refaz cada método (None: a padrão dele) e o motivo, por política.

    O método sem política congelada segue pela padrão; o que a conferência dos insumos faz dele
    (`politica_sem_insumo_congelado`) é outro item.
    """

    por_metodo: Mapping[MetodoId, str | None]
    problemas: Mapping[str, str]


def _politica(
    chave: str, entrada: EntradaValidacao, identidades: Mapping[str, str], diretorio: Path
) -> PoliticaTemporal | str:
    """A política que a execução congelada usou, ou o motivo de não se saber qual foi.

    Vale a política resolvida que a entrada traz; sem ela (o `freeze` aceita), a do catálogo com o
    id da entrada. Nos dois casos tem de ser a que o manifesto congelou.
    """
    politica = entrada.politica
    if politica is None:
        try:
            politica = carregar_politica(chave, diretorio)
        except ConfigInvalida:
            return _INDISPONIVEL
    if politica.politica_id != chave:
        return f"{_OUTRO_ID} id={politica.politica_id}"
    if hash_canonico(politica.model_dump(mode="json")) != identidades.get("politica"):
        return _ALTERADA
    return politica


def _como_reproduzir(
    politica: PoliticaTemporal, regras: Sequence[RuleSpec], diretorio: Path
) -> tuple[str | None, str]:
    """`config.politica_id` que faz o `validate` resolver exatamente `politica`, ou o motivo.

    `None` é a política padrão do método; senão, a do catálogo com o mesmo id e o mesmo conteúdo.
    Só se chama com política de método de validação por regras, o único que tem padrão.
    """
    if politica == politica_padrao(politica.metodo, list(regras)):
        return None, ""
    try:
        do_catalogo = carregar_politica(politica.politica_id, diretorio)
    except ConfigInvalida:
        return None, _INDISPONIVEL
    if do_catalogo != politica:
        return None, _INDISPONIVEL
    return politica.politica_id, ""


def _do_metodo(
    metodo: MetodoId,
    candidatas: list[tuple[str, PoliticaTemporal]],
    registradas: Mapping[MetodoId, str | None],
    regras: Sequence[RuleSpec],
    diretorio: Path,
) -> tuple[str | None, dict[str, str]]:
    if not candidatas:
        return None, {}
    if len(candidatas) > 1:
        motivo = f"{_AMBIGUA} metodo={metodo.value}"
        return None, {chave: motivo for chave, _ in candidatas}
    ((chave, politica),) = candidatas
    if metodo in registradas and registradas[metodo] != chave:
        return None, {chave: f"{_REGISTRADA} registrada={registradas[metodo]}"}
    refazer_com, motivo = _como_reproduzir(politica, regras, diretorio)
    return refazer_com, ({chave: motivo} if motivo else {})


def politicas_congeladas(
    entradas: Mapping[str, EntradaValidacao],
    identidades: Mapping[str, Mapping[str, str]],
    registradas: Mapping[MetodoId, str | None],
    regras: Sequence[RuleSpec],
    diretorio: Path | None = None,
) -> PoliticasCongeladas:
    """A política com que refazer cada método e os problemas das que não se refazem.

    `entradas` são as entradas originais já conferidas (por política congelada), `identidades` a
    identidade de cada campo que o manifesto guarda, `registradas` o `politica_id` da execução
    registrada de cada método e `regras` o catálogo de regras (a política padrão depende dele).
    Problemas, por `politica_id`: política que não é a padrão do método nem a do catálogo com o
    mesmo conteúdo (`politica_congelada_indisponivel`), sem a identidade congelada
    (`_alterada`), com id diferente da chave (`_com_outro_id`), duas do mesmo método (`_ambigua`)
    ou execução registrada de outra política (`politica_registrada_diferente`).
    """
    pasta = DIRETORIO_POLITICAS if diretorio is None else diretorio
    problemas: dict[str, str] = {}
    candidatas: dict[MetodoId, list[tuple[str, PoliticaTemporal]]] = {}
    for chave, entrada in sorted(entradas.items()):
        achada = _politica(chave, entrada, identidades.get(chave, {}), pasta)
        if isinstance(achada, str):
            problemas[chave] = achada
        else:
            candidatas.setdefault(achada.metodo, []).append((chave, achada))
    por_metodo: dict[MetodoId, str | None] = {}
    for metodo in METODOS_DE_VALIDACAO:
        achadas = candidatas.pop(metodo, [])
        por_metodo[metodo], do_metodo = _do_metodo(metodo, achadas, registradas, regras, pasta)
        problemas.update(do_metodo)
    for restantes in candidatas.values():
        problemas.update({chave: _INDISPONIVEL for chave, _ in restantes})
    return PoliticasCongeladas(por_metodo, problemas)
