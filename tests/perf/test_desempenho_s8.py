"""Medição sob demanda (marcador perf) de etapas do main sobre cenário SINTETICO pequeno.

Não mede escala: DRS XI e SP rodam na máquina do pesquisador (docs/method/valores.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from tests.fixtures.anotacao_cenario import montar_cenario
from tests.fixtures.anotacao_valores import Linha, montar_valores

from sustemporal.contracts import OrigemDados
from sustemporal.evaluation.annotation import prepare_annotation_sample
from sustemporal.evaluation.performance import (
    ETAPAS_PENDENTES,
    Cache,
    EstadoMedicao,
    Etapa,
    etapa_pendente,
    gravar_relatorio,
    medir,
)
from sustemporal.evaluation.values import summarize_values
from sustemporal.runtime_info import ambiente

pytestmark = pytest.mark.perf


def test_harness_mede_etapas_do_main_e_declara_pendentes(tmp_path: Path) -> None:
    cenario = montar_cenario(tmp_path / "anotacao")
    linhas = [
        Linha(f"r{i:05d}", "NAO_APROVADO", Decimal("10.00"), Decimal("0.00")) for i in range(500)
    ]
    valores = montar_valores(tmp_path / "valores", linhas)
    saida_ann, saida_val = tmp_path / "saida_ann", tmp_path / "saida_val"
    etapas = [
        Etapa(
            "anotacao",
            lambda: prepare_annotation_sample(
                cenario.labels,
                cenario.split,
                cenario.config,
                saida_ann,
                particoes=cenario.particoes,
            ),
            saida=saida_ann,
        ),
        Etapa(
            "valores_p3",
            lambda: summarize_values(valores.run, valores.labels, saida_val),
            saida=saida_val,
        ),
        *(etapa_pendente(nome) for nome in sorted(ETAPAS_PENDENTES)),
    ]
    medicoes = [medir(e, repeticoes=3, cache=Cache.QUENTE) for e in etapas]
    assert [m.estado for m in medicoes[:2]] == [EstadoMedicao.MEDIDO] * 2
    assert all(m.estado is EstadoMedicao.NAO_MEDIDO for m in medicoes[2:])
    caminho = gravar_relatorio(
        medicoes,
        tmp_path / "perf",
        ambiente=ambiente(Path.cwd()),
        instante=datetime.now(UTC),
        origem_dados=OrigemDados.SINTETICO,
    )
    assert caminho.exists()
