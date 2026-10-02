"""Portões do confirmatório no motor de regras (cenários SINTETICOS)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.records import DatasetRef
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import PortaoRecusado
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao
from tests.fixtures.regras_cenario import coerente, materializar, politica, snapshot_vazio
from tests.fixtures.regras_exemplos import cenario_base

FREEZE = f"frz_{'a' * 64}"
G2_ABRIR = (
    "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2025-06-01\nresponsaveis: [orientacao]\n"
    f"registrado_por_humano: true\nfreeze_id: {FREEZE}\n"
)
CONFIRMATORIA = RunConfig.model_validate(
    {
        "versao": "1",
        "modo": "CONFIRMATORIO",
        "origem_dados": "REAL",
        "freeze_id": FREEZE,
        "bootstrap": {"correcao": "HOLM"},
    }
)


def _relogio() -> datetime:
    return datetime(2026, 1, 15, tzinfo=UTC)


def _como_real(dataset: DatasetRef) -> DatasetRef:
    return dataset.model_copy(update={"origem_dados": OrigemDados.REAL})


def _avaliar(
    tmp_path: Path, *, real: bool, decisoes: Path, metodo: MetodoId = MetodoId.B_ATEND
) -> None:
    cenario = coerente(cenario_base().com(politica=politica(metodo)))
    dataset, insumos = materializar(cenario, tmp_path / "entrada")
    if real:
        dataset = _como_real(dataset)
        insumos = replace(
            insumos,
            auxiliares=tuple(_como_real(d) for d in insumos.auxiliares),
            selecoes=_como_real(insumos.selecoes) if insumos.selecoes else None,
            cobertura=_como_real(insumos.cobertura) if insumos.cobertura else None,
        )
    insumos = replace(insumos, diretorio_decisoes=decisoes)
    evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        CONFIRMATORIA,
        tmp_path / "s",
        insumos=insumos,
        relogio=_relogio,
    )


def _decisoes_com_g2(raiz: Path) -> Path:
    raiz.mkdir(parents=True)
    (raiz / "g2.yaml").write_text(G2_ABRIR, encoding="utf-8")
    return raiz


def test_confirmatorio_com_dados_sinteticos_e_recusado(tmp_path: Path) -> None:
    with pytest.raises(PortaoRecusado, match="confirmatorio_exige_dados_reais"):
        _avaliar(tmp_path, real=False, decisoes=_decisoes_com_g2(tmp_path / "decisoes"))


def test_confirmatorio_sem_g2_e_recusado(tmp_path: Path) -> None:
    vazio = tmp_path / "decisoes"
    vazio.mkdir()
    with pytest.raises(PortaoRecusado):
        _avaliar(tmp_path, real=True, decisoes=vazio)


def test_confirmatorio_com_g2_ainda_recusa_politica_nao_resolvida(tmp_path: Path) -> None:
    with pytest.raises(PortaoRecusado, match="politica_nao_resolvida"):
        _avaliar(
            tmp_path,
            real=True,
            decisoes=_decisoes_com_g2(tmp_path / "decisoes"),
            metodo=MetodoId.M_TEMP,
        )


def test_insumos_tem_diretorio_de_decisoes_padrao() -> None:
    assert InsumosAvaliacao().diretorio_decisoes == Path("experiments/decisions")
