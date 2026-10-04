"""Harness de desempenho (T13b): lógica de medição com relógio injetado, sem medir escala."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts import Ambiente, OrigemDados
from sustemporal.evaluation.performance import (
    ETAPAS_PENDENTES,
    Cache,
    EstadoMedicao,
    Etapa,
    etapa_pendente,
    gravar_relatorio,
    medir,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _relogio(passo: int) -> Callable[[], int]:
    contador = count(step=passo)
    return lambda: next(contador)


def test_mede_tempo_repeticoes_e_armazenamento(tmp_path: Path) -> None:
    saida = tmp_path / "saida"
    saida.mkdir()

    def executar() -> None:
        (saida / "a.bin").write_bytes(b"x" * 100)
        _ = [0] * 1000

    medicao = medir(
        Etapa("gravar", executar, saida=saida),
        repeticoes=3,
        cache=Cache.QUENTE,
        relogio=_relogio(7),
    )
    assert medicao.estado is EstadoMedicao.MEDIDO
    assert medicao.repeticoes == 3
    assert medicao.tempos_ns == (7, 7, 7)
    assert medicao.cache is Cache.QUENTE
    assert medicao.armazenamento_bytes == 100
    assert medicao.pico_python_bytes is not None
    assert medicao.pico_python_bytes > 0
    assert medicao.rss_max_kib is not None


@pytest.mark.parametrize("nome", sorted(ETAPAS_PENDENTES))
def test_etapa_pendente_nao_inventa_medicao(nome: str) -> None:
    medicao = medir(etapa_pendente(nome))
    assert medicao.estado is EstadoMedicao.NAO_MEDIDO
    assert medicao.motivo == ETAPAS_PENDENTES[nome]
    assert medicao.tempos_ns == ()
    assert medicao.pico_python_bytes is None
    assert medicao.armazenamento_bytes is None


def test_stub_nao_implementado_vira_nao_medido() -> None:
    def stub() -> None:
        raise NotImplementedError

    medicao = medir(Etapa("stub", stub))
    assert medicao.estado is EstadoMedicao.NAO_MEDIDO
    assert medicao.motivo == "nao_implementado"
    assert medicao.tempos_ns == ()


def test_repeticoes_invalidas_sao_recusadas() -> None:
    with pytest.raises(ValueError, match="repeticoes_invalidas"):
        medir(Etapa("x", lambda: None), repeticoes=0)


def test_relatorio_registra_ambiente_instante_cache_e_repeticoes(tmp_path: Path) -> None:
    medicoes = [
        medir(Etapa("nada", lambda: None), repeticoes=2, relogio=_relogio(3)),
        medir(etapa_pendente("metricas")),
    ]
    ambiente = Ambiente(python="3.12", plataforma="linux", pacotes={"duckdb": "1.0"})
    instante = datetime(2026, 1, 1, tzinfo=UTC)
    caminho = gravar_relatorio(
        medicoes,
        tmp_path / "perf",
        ambiente=ambiente,
        instante=instante,
        origem_dados=OrigemDados.SINTETICO,
    )
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["ambiente"]["pacotes"] == {"duckdb": "1.0"}
    assert dados["instante"] == "2026-01-01T00:00:00Z"
    assert dados["origem_dados"] == "SINTETICO"
    primeira, segunda = dados["medicoes"]
    assert primeira["repeticoes"] == 2
    assert primeira["tempos_ns"] == [3, 3]
    assert primeira["cache"] == "NAO_CONTROLADO"
    assert segunda["estado"] == "NAO_MEDIDO"
    assert segunda["motivo"] == ETAPAS_PENDENTES["metricas"]
