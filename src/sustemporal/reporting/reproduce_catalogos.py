"""Catálogos e origem dos dados que o congelamento registrou, contra os que a config declara (T14).

O manifesto guarda o SHA-256 de cada catálogo que a config declara e o do catálogo de regras. A
reprodução usa os de agora: se diferem, a diferença vira observação (não impede a conferência: o
conteúdo refeito decide se o resultado é igual ou divergente). A origem dos dados da config tem de
ser a dos conjuntos congelados; senão a reprodução é inconclusiva. O topo do `reproducao.json` traz
a origem dos conjuntos congelados (`origem_dados`) e a da config (`origem_dados_config`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.base import OrigemDados
from sustemporal.evaluation.freeze import hash_das_regras
from sustemporal.hashing import sha256_arquivo
from sustemporal.reporting.reproduce_comparacao import Comparacao, Situacao

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec

__all__ = ["item_da_origem", "observacoes_dos_catalogos", "origens_do_relatorio"]


def _sha256(caminho: str | None) -> str | None:
    if caminho is None:
        return None
    try:
        return sha256_arquivo(Path(caminho))
    except OSError:
        return None


def observacoes_dos_catalogos(
    congelados: Mapping[str, str],
    catalogos: Mapping[str, str],
    regras_congeladas: str | None,
    regras: Sequence[RuleSpec],
) -> list[str]:
    """Linhas de `observacoes` para o catálogo que mudou, sumiu ou que só um dos lados tem.

    `congelados` e `catalogos` (a config) são por nome; `regras_congeladas` é o SHA-256 do
    catálogo de regras no manifesto (sem ele, as regras não são conferidas).
    """
    observacoes = []
    nomes = {*congelados, *catalogos}
    diferentes = sorted(n for n in nomes if _sha256(catalogos.get(n)) != congelados.get(n))
    if diferentes:
        observacoes.append(f"catalogos_diferentes_do_congelado catalogos={','.join(diferentes)}")
    if regras_congeladas is not None and hash_das_regras(regras) != regras_congeladas:
        observacoes.append("catalogo_de_regras_diferente_do_congelado")
    return observacoes


def _origens(datasets: Iterable[DatasetRef]) -> list[str]:
    return sorted({dataset.origem_dados.value for dataset in datasets})


def _declarada(origem: OrigemDados | None) -> str:
    """A origem declarada na config; sem ela vale `SINTETICO`, como no `ingest`."""
    return (origem or OrigemDados.SINTETICO).value


def item_da_origem(origem: OrigemDados | None, datasets: Iterable[DatasetRef]) -> list[Comparacao]:
    """Item inconclusivo se a origem dos dados da config não é a dos conjuntos congelados.

    Sem `origem_dados` na config vale `SINTETICO`, como no `ingest`.
    """
    congeladas, obtida = _origens(datasets), _declarada(origem)
    if congeladas == [obtida]:
        return []
    detalhe = "origem_dados_diferente_do_congelado"
    return [
        Comparacao("origem_dados", Situacao.INCONCLUSIVO, ",".join(congeladas), obtida, detalhe)
    ]


def origens_do_relatorio(
    origem: OrigemDados | None, datasets: Iterable[DatasetRef]
) -> dict[str, str | None]:
    """`origem_dados` e `origem_dados_config` do topo do `reproducao.json`.

    `origem_dados` é a dos conjuntos do manifesto congelado, como nos outros artefatos (várias,
    separadas por vírgula; `None` se o manifesto não traz conjuntos); `origem_dados_config` é a
    declarada na config, e `SINTETICO` sem declaração.
    """
    return {
        "origem_dados": ",".join(_origens(datasets)) or None,
        "origem_dados_config": _declarada(origem),
    }
