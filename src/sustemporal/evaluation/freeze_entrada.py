"""Identidade, campo a campo, da entrada de validação (`EntradaValidacao`) das regras (T11).

O manifesto guarda, por `politica_id`, a identidade de cada campo da entrada que as execuções de
regras do TESTE devem usar, e a conferência recalcula a da `entrada_validacao.json` de cada
execução. A identidade percorre os campos do modelo recebido, então um campo novo entra na
comparação sem alterar este módulo e, se o congelamento não o traz, diverge. Conjuntos de dados
valem pelo `dataset_id` (nunca pelo caminho), o `SnapshotSet` pelo `snapshot_id`, a ordem dos
conjuntos não importa e coleção ou mapa vazio vale o mesmo que ausente.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from sustemporal.contracts.base import hash_canonico, json_canonico
from sustemporal.contracts.records import DatasetRef
from sustemporal.contracts.temporal import SnapshotSet

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sustemporal.contracts import RunResult
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = ["campos_divergentes", "entrada_da_execucao", "identidades_da_entrada"]


def _normalizado(valor: object) -> object:
    if isinstance(valor, DatasetRef):
        return valor.dataset_id
    if isinstance(valor, SnapshotSet):
        return valor.snapshot_id
    if isinstance(valor, BaseModel):
        return valor.model_dump(mode="json")
    if isinstance(valor, tuple | list):
        return sorted((_normalizado(item) for item in valor), key=json_canonico) or None
    if isinstance(valor, dict):
        return {str(chave): _normalizado(item) for chave, item in valor.items()} or None
    return valor


def identidades_da_entrada(entrada: EntradaValidacao) -> dict[str, str]:
    """Identidade (hash canônico do valor normalizado) de cada campo da entrada, na ordem dela."""
    campos = type(entrada).model_fields
    return {campo: hash_canonico(_normalizado(getattr(entrada, campo))) for campo in campos}


def campos_divergentes(congeladas: Mapping[str, str], entrada: EntradaValidacao) -> list[str]:
    """Campos da entrada, na ordem dela, cuja identidade difere da congelada ou falta nela."""
    atuais = identidades_da_entrada(entrada)
    return [campo for campo, identidade in atuais.items() if congeladas.get(campo) != identidade]


def entrada_da_execucao(entrada: EntradaValidacao, run: RunResult) -> bool:
    """A entrada é a que a execução usou: mesmo `SnapshotSet` e os conjuntos não populacionais
    (auxiliares, seleções e cobertura) entre as entradas dela; a população fica para `entradas`."""
    conjuntos = (*entrada.auxiliares, entrada.selecoes, entrada.cobertura)
    usados = {d.dataset_id for d in run.entradas}
    do_snapshot = entrada.snapshots.snapshot_id == run.snapshot_set_id
    return do_snapshot and all(d.dataset_id in usados for d in conjuntos if d is not None)
