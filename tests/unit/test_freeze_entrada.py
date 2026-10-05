"""Identidade, campo a campo, da entrada de validação das regras (T11, SINTETICO)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import MetodoId
from sustemporal.evaluation.freeze_entrada import (
    campos_divergentes,
    entrada_da_execucao,
    identidades_da_entrada,
)
from sustemporal.rules.entrada import EntradaValidacao
from sustemporal.temporal.politicas import carregar_politica
from tests.fixtures.protocolo_avaliacao import run_agregados
from tests.fixtures.protocolo_insumos import (
    ARTEFATO_DO_INSUMO,
    ESQUEMA_CNES,
    ESQUEMA_COBERTURA,
    ESQUEMA_SELECAO,
    ESQUEMA_SIGTAP,
    conjunto_sintetico,
    entrada_gravada,
    execucao_com_entrada,
    snapshots_sinteticos,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts import RunResult

TESTE = conjunto_sintetico("sia_pa.v1", "teste")
OUTRA = "2099-12"


class EntradaComCampoNovo(EntradaValidacao):
    """Entrada com um campo que a conferência ainda não conhece."""

    novo: str = "x"


class EntradaComColecoes(EntradaValidacao):
    """Entrada com campos de coleção e de mapa que a conferência ainda não conhece."""

    lista: list[DatasetRef] | None = None
    mapa: dict[str, DatasetRef] | None = None


def _entrada() -> EntradaValidacao:
    return entrada_gravada(TESTE, "B_ATEND")


def _com_colecoes(**campos: object) -> EntradaComColecoes:
    return EntradaComColecoes(**_entrada().model_dump(), **campos)


def test_identidade_cobre_todo_campo_da_entrada() -> None:
    assert set(identidades_da_entrada(_entrada())) == set(EntradaValidacao.model_fields)


def test_identidade_do_conjunto_ignora_o_caminho() -> None:
    entrada = _entrada()
    primeiro = entrada.auxiliares[0].model_copy(update={"caminho": "/outro/lugar.parquet"})
    movida = entrada.model_copy(update={"auxiliares": (primeiro, *entrada.auxiliares[1:])})
    assert identidades_da_entrada(movida) == identidades_da_entrada(entrada)


def test_ordem_dos_auxiliares_nao_muda_a_identidade() -> None:
    entrada = _entrada()
    invertida = entrada.model_copy(update={"auxiliares": tuple(reversed(entrada.auxiliares))})
    assert identidades_da_entrada(invertida) == identidades_da_entrada(entrada)


def test_conjunto_do_mesmo_hash_logico_com_outros_artefatos_tem_outra_identidade() -> None:
    entrada = _entrada()
    base = entrada.auxiliares[0]
    artefatos = ("art_de_outra_coleta",)
    outro = base.model_copy(
        update={
            "artifact_ids": artefatos,
            "dataset_id": calcular_dataset_id(base.schema_id, base.hash_logico, artefatos),
        }
    )
    alterada = entrada.model_copy(update={"auxiliares": (outro, *entrada.auxiliares[1:])})
    assert campos_divergentes(identidades_da_entrada(entrada), alterada) == ["auxiliares"]


@pytest.mark.parametrize("campo", ["identidade_adicional", "integridade"])
def test_mapa_ausente_e_vazio_tem_a_mesma_identidade(campo: str) -> None:
    sem = _entrada().model_copy(update={campo: None})
    vazio = _entrada().model_copy(update={campo: {}})
    assert identidades_da_entrada(sem)[campo] == identidades_da_entrada(vazio)[campo]


def test_estado_de_integridade_diferente_muda_a_identidade() -> None:
    entrada = _entrada()
    alterada = entrada.model_copy(
        update={"integridade": {ARTEFATO_DO_INSUMO: EstadoIntegridade.QUARENTENA_LEIAUTE}}
    )
    assert (
        identidades_da_entrada(alterada)["integridade"]
        != identidades_da_entrada(entrada)["integridade"]
    )


ALTERACOES = {
    "dataset": {"dataset": conjunto_sintetico("sia_pa.v1", OUTRA)},
    "snapshots": {"snapshots": snapshots_sinteticos(OUTRA)},
    "auxiliares": {"auxiliares": (conjunto_sintetico(ESQUEMA_CNES, OUTRA),)},
    "selecoes": {"selecoes": conjunto_sintetico(ESQUEMA_SELECAO, OUTRA)},
    "cobertura": {"cobertura": conjunto_sintetico(ESQUEMA_COBERTURA, OUTRA)},
    "integridade": {"integridade": {ARTEFATO_DO_INSUMO: EstadoIntegridade.NAO_VERIFICADO}},
    "politica_documentada": {"politica_documentada": carregar_politica("B_PROC")},
    "politica": {"politica": None},
    "identidade_adicional": {"identidade_adicional": {"recorte_territorial": "a" * 64}},
}


def test_toda_alteracao_do_teste_corresponde_a_um_campo_da_entrada() -> None:
    assert set(ALTERACOES) == set(EntradaValidacao.model_fields)


@pytest.mark.parametrize("campo", sorted(ALTERACOES))
def test_campo_alterado_diverge_so_nele(campo: str) -> None:
    entrada = _entrada()
    congeladas = identidades_da_entrada(entrada)
    alterada = entrada.model_copy(update=ALTERACOES[campo])
    assert campos_divergentes(congeladas, alterada) == [campo]


def test_campos_divergentes_saem_na_ordem_do_modelo() -> None:
    entrada = _entrada()
    congeladas = identidades_da_entrada(entrada)
    alteracoes = {**ALTERACOES["identidade_adicional"], **ALTERACOES["snapshots"]}
    alteracoes |= ALTERACOES["selecoes"]
    ordem = [
        c
        for c in EntradaValidacao.model_fields
        if c in {"snapshots", "selecoes", "identidade_adicional"}
    ]
    assert campos_divergentes(congeladas, entrada.model_copy(update=alteracoes)) == ordem


def test_entrada_igual_a_congelada_nao_diverge() -> None:
    entrada = _entrada()
    assert campos_divergentes(identidades_da_entrada(entrada), entrada) == []


def test_campo_que_o_congelamento_nao_traz_diverge() -> None:
    entrada = _entrada()
    congeladas = identidades_da_entrada(entrada)
    del congeladas["integridade"]
    assert campos_divergentes(congeladas, entrada) == ["integridade"]


def test_campo_novo_da_entrada_entra_na_comparacao_sem_mudar_o_modulo() -> None:
    base = _entrada()
    nova = EntradaComCampoNovo(**base.model_dump())
    congeladas = identidades_da_entrada(base)
    assert "novo" in identidades_da_entrada(nova)
    assert campos_divergentes(congeladas, nova) == ["novo"]


@pytest.mark.parametrize(("campo", "vazio"), [("lista", []), ("mapa", {})])
def test_colecao_de_campo_novo_vazia_vale_o_mesmo_que_ausente(campo: str, vazio: object) -> None:
    vazia = identidades_da_entrada(_com_colecoes(**{campo: vazio}))
    assert vazia == identidades_da_entrada(_com_colecoes())


def test_lista_de_conjuntos_de_campo_novo_vale_pelo_id_e_nao_pela_ordem() -> None:
    cnes = conjunto_sintetico(ESQUEMA_CNES, "2024-01")
    base = identidades_da_entrada(_com_colecoes(lista=[TESTE, cnes]))
    movido = TESTE.model_copy(update={"caminho": "/outro/lugar.parquet"})
    assert identidades_da_entrada(_com_colecoes(lista=[cnes, movido])) == base
    assert identidades_da_entrada(_com_colecoes(lista=[TESTE])) != base


def test_mapa_de_conjuntos_de_campo_novo_vale_pelo_id_e_nao_pelo_caminho() -> None:
    base = identidades_da_entrada(_com_colecoes(mapa={"x": TESTE}))
    movido = TESTE.model_copy(update={"caminho": "/outro/lugar.parquet"})
    assert identidades_da_entrada(_com_colecoes(mapa={"x": movido})) == base
    outro = conjunto_sintetico("sia_pa.v1", OUTRA)
    assert identidades_da_entrada(_com_colecoes(mapa={"x": outro})) != base


def _execucao(tmp_path: Path, entrada: EntradaValidacao) -> RunResult:
    run = run_agregados(MetodoId.B_ATEND, {}, tmp_path, origem=OrigemDados.REAL)
    return execucao_com_entrada(run, entrada)


def test_entrada_que_a_execucao_usou_e_coerente_com_ela(tmp_path: Path) -> None:
    entrada = _entrada()
    assert entrada_da_execucao(entrada, _execucao(tmp_path, entrada))


def test_entrada_de_outro_snapshot_nao_e_a_da_execucao(tmp_path: Path) -> None:
    entrada = _entrada()
    run = _execucao(tmp_path, entrada)
    outra = entrada.model_copy(update={"snapshots": snapshots_sinteticos(OUTRA)})
    assert not entrada_da_execucao(outra, run)


@pytest.mark.parametrize("campo", ["selecoes", "cobertura", "auxiliares"])
def test_entrada_com_conjunto_que_a_execucao_nao_registrou_nao_e_a_dela(
    tmp_path: Path, campo: str
) -> None:
    entrada = _entrada()
    run = _execucao(tmp_path, entrada)
    esquema = {
        "selecoes": ESQUEMA_SELECAO,
        "cobertura": ESQUEMA_COBERTURA,
        "auxiliares": ESQUEMA_CNES,
    }[campo]
    outro = conjunto_sintetico(esquema, OUTRA)
    outra = entrada.model_copy(update={campo: (outro,) if campo == "auxiliares" else outro})
    assert not entrada_da_execucao(outra, run)


def test_execucao_com_entradas_a_mais_ainda_usou_a_entrada(tmp_path: Path) -> None:
    entrada = _entrada()
    run = _execucao(tmp_path, entrada)
    a_mais = conjunto_sintetico(ESQUEMA_SIGTAP, OUTRA)
    assert entrada_da_execucao(
        entrada, run.model_copy(update={"entradas": (*run.entradas, a_mais)})
    )
