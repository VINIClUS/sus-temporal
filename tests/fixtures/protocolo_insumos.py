"""Entrada de validação das regras sobre o TESTE e conjuntos sem arquivo, SINTETICO (T11).

Os conjuntos auxiliares, as seleções e a cobertura não têm arquivo: a conferência por execução só
compara identidades. A entrada preparada para o congelamento não traz a política resolvida, que o
`validate` acrescenta ao gravar a entrada com a execução (`entrada_gravada`).
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import SnapshotSet
from sustemporal.rules.entrada import EntradaValidacao
from sustemporal.temporal.politicas import carregar_politica
from tests.fixtures.protocolo_dados import artefato

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sustemporal.contracts import RunResult

ESQUEMA_CNES = "cnes_estabelecimento.v1"
ESQUEMA_SIGTAP = "sigtap_procedimento.v1"
ESQUEMA_COBERTURA = "cobertura.v1"
ESQUEMA_SELECAO = "selecao_versoes.v1"
ESQUEMAS_DA_POPULACAO = frozenset({"sia_pa.v1", "sia_pa_rotulos.v1"})
ARTEFATO_DO_INSUMO = artefato("insumo")
HASH_DO_RECORTE = hashlib.sha256(b"recorte_territorial").hexdigest()
POLITICA_DOCUMENTADA = "M_TEMP_PADRAO"


def conjunto_sintetico(esquema: str, versao: str) -> DatasetRef:
    """Conjunto não populacional REAL sem arquivo: só a identidade importa na conferência."""
    conteudo = f"lh1:{hashlib.sha256(f'{esquema}:{versao}'.encode()).hexdigest()}"
    return DatasetRef(
        dataset_id=calcular_dataset_id(esquema, conteudo, ()),
        schema_id=esquema,
        caminho=f"{esquema}.{versao}.parquet",
        hash_logico=conteudo,
        linhas=0,
        artifact_ids=(),
        origem_dados=OrigemDados.REAL,
        produzido_por="tests.fixtures.protocolo_insumos",
    )


def snapshots_sinteticos(versao: str) -> SnapshotSet:
    """`SnapshotSet` vazio que só se distingue pelo hash de dataset da `versao`."""
    return SnapshotSet.criar(
        artifact_ids=(),
        observation_ids=(),
        dataset_hashes=(conjunto_sintetico(ESQUEMA_SELECAO, versao).hash_logico,),
        selecoes=(),
    )


def entrada_da_politica(
    teste: DatasetRef, politica_id: str, *, sigtap: str = "2024-01", cobertura: str = "base"
) -> EntradaValidacao:
    """Entrada de validação preparada sobre o TESTE; seleção e snapshots dependem da política.

    Só a política documentada (M_TEMP) vem na entrada; a política resolvida não.
    """
    documentada = carregar_politica(politica_id) if politica_id == POLITICA_DOCUMENTADA else None
    return EntradaValidacao(
        dataset=teste,
        snapshots=snapshots_sinteticos(politica_id),
        auxiliares=(
            conjunto_sintetico(ESQUEMA_CNES, "2024-01"),
            conjunto_sintetico(ESQUEMA_SIGTAP, sigtap),
        ),
        selecoes=conjunto_sintetico(ESQUEMA_SELECAO, politica_id),
        cobertura=conjunto_sintetico(ESQUEMA_COBERTURA, cobertura),
        integridade={ARTEFATO_DO_INSUMO: EstadoIntegridade.OK},
        politica_documentada=documentada,
        identidade_adicional={"recorte_territorial": HASH_DO_RECORTE},
    )


def entrada_gravada(teste: DatasetRef, politica_id: str) -> EntradaValidacao:
    """A entrada como o `validate` a grava com a execução: com a política resolvida."""
    politica = carregar_politica(politica_id)
    return entrada_da_politica(teste, politica_id).model_copy(update={"politica": politica})


def entradas_das_execucoes(runs: Iterable[RunResult]) -> dict[str, EntradaValidacao]:
    """`entrada_validacao.json` de cada execução de regras (a que tem política), por `run_id`."""
    return {
        run.run_id: entrada_gravada(run.entradas[0], run.politica_id)
        for run in runs
        if run.politica_id and run.entradas
    }


def execucao_com_entrada(run: RunResult, entrada: EntradaValidacao) -> RunResult:
    """Mesma execução com as entradas e o `SnapshotSet` que o motor registra para `entrada`."""
    refs = (entrada.dataset, *entrada.auxiliares, entrada.selecoes, entrada.cobertura)
    entradas = tuple(d for d in refs if d is not None)
    return run.model_copy(
        update={"entradas": entradas, "snapshot_set_id": entrada.snapshots.snapshot_id}
    )


def entradas_nao_populacionais(run: RunResult) -> tuple[DatasetRef, ...]:
    """Entradas da execução que não são a população nem os rótulos (auxiliares, seleção, ...)."""
    return tuple(d for d in run.entradas if d.schema_id not in ESQUEMAS_DA_POPULACAO)
