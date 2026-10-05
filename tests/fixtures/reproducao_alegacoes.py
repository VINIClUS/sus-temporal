"""Decisões humanas por alegação: leitura e conferência com o estado do registro (T14).

Cada arquivo `experiments/decisions/alegacoes/<AAAA-MM-DD>.yaml` traz `data`, `responsaveis`,
`registrado_por_humano: true`, `evidencias` e `alegacoes` (`AL-NN: ESTADO`). Fica num subdiretório
porque `sustemporal.gates` lê todo `*.yaml` de `experiments/decisions/` como `DecisaoPortao`, que
recusa campos extras. A autoridade humana vem do caminho, só de humanos em
`docs/process/propriedade.yaml`; o conteúdo não identifica quem o escreveu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, NamedTuple

from pydantic import Field, StringConstraints

from sustemporal.contracts.base import ContratoBase, Data, Verdadeiro
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date
    from pathlib import Path

DIR_ALEGACOES = "alegacoes"
ESTADOS = ("PENDENTE", "EXPLORATORIA", "CONFIRMADA", "NAO_CONFIRMADA")

_Texto = Annotated[str, StringConstraints(pattern=r"\S")]
_Id = Annotated[str, StringConstraints(pattern=r"^AL-\d{2}$")]
_Estado = Annotated[str, StringConstraints(pattern=f"^(?:{'|'.join(ESTADOS)})$")]


class DecisaoDeAlegacoes(ContratoBase):
    data: Data
    responsaveis: Annotated[tuple[_Texto, ...], Field(min_length=1)]
    registrado_por_humano: Verdadeiro
    evidencias: Annotated[tuple[_Texto, ...], Field(min_length=1)]
    alegacoes: Annotated[dict[_Id, _Estado], Field(min_length=1)]
    observacoes: str = ""


class _Citacao(NamedTuple):
    data: date
    estado: str


def carregar_decisoes_de_alegacoes(
    diretorio: Path,
) -> tuple[list[tuple[str, DecisaoDeAlegacoes]], list[str]]:
    """Decisões válidas como (arquivo, decisão) e as mensagens dos arquivos inválidos.

    Arquivos `MODELO_*` e subdiretórios ficam de fora: modelo nunca decide.
    """
    if not diretorio.is_dir():
        return [], []
    decisoes: list[tuple[str, DecisaoDeAlegacoes]] = []
    problemas: list[str] = []
    for arquivo in sorted([*diretorio.glob("*.yaml"), *diretorio.glob("*.yml")]):
        if arquivo.name.startswith("MODELO_"):
            continue
        try:
            decisao = DecisaoDeAlegacoes.model_validate(carregar_yaml(arquivo))
        except (ValueError, OSError):
            problemas.append(f"decisao_de_alegacao_invalida arquivo={arquivo.name}")
        else:
            decisoes.append((arquivo.name, decisao))
    return decisoes, problemas


def _citacoes(decisoes: Sequence[tuple[str, DecisaoDeAlegacoes]]) -> dict[str, list[_Citacao]]:
    citacoes: dict[str, list[_Citacao]] = {}
    for _arquivo, decisao in decisoes:
        for id_, estado in decisao.alegacoes.items():
            citacoes.setdefault(id_, []).append(_Citacao(decisao.data, estado))
    return citacoes


def _problemas_da_alegacao(id_: str, estado: str, citacoes: Sequence[_Citacao]) -> list[str]:
    if not citacoes:
        sem_decisao = f"estado_sem_decisao_da_alegacao id={id_} estado={estado}"
        return [] if estado == "PENDENTE" else [sem_decisao]
    data = max(citacao.data for citacao in citacoes)
    decididos = sorted({citacao.estado for citacao in citacoes if citacao.data == data})
    if len(decididos) > 1:
        return [f"decisoes_de_alegacao_empatadas id={id_} data={data}"]
    if decididos[0] != estado:
        return [f"estado_diverge_da_decisao id={id_} estado={estado} decidido={decididos[0]}"]
    return []


def problemas_de_decisoes(estados: Mapping[str, str], diretorio: Path) -> list[str]:
    """Mensagens `chave=valor` do estado de cada alegação contra a decisão humana mais recente.

    Args:
        estados: estado do registro por id de alegação.
        diretorio: `experiments/decisions/alegacoes/` (ou o equivalente de teste).
    """
    decisoes, problemas = carregar_decisoes_de_alegacoes(diretorio)
    citacoes = _citacoes(decisoes)
    inexistentes = sorted(citacoes.keys() - estados.keys())
    problemas += [f"decisao_cita_alegacao_inexistente id={id_}" for id_ in inexistentes]
    for id_, estado in estados.items():
        problemas += _problemas_da_alegacao(id_, estado, citacoes.get(id_, ()))
    return problemas
