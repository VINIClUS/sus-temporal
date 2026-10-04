"""Baseline estatístico do T10: categoria desconhecida, semente, controle trivial (SINTETICO)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import duckdb
import pytest
from tests.fixtures.protocolo_dados import (
    PROC_APROVADO,
    PROC_REJEITADO,
    LinhaPa,
    artefato,
    cenario_baseline,
)

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO


def _relogio() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _predicoes(caminho: str) -> list[tuple[Any, ...]]:
    con = duckdb.connect()
    try:
        return con.execute(
            "SELECT row_id, metodo, particao, resultado FROM read_parquet($c) "
            "ORDER BY metodo, row_id",
            {"c": caminho},
        ).fetchall()
    finally:
        con.close()


def _parametros(caminho: str) -> dict[str, Any]:
    texto = Path(caminho).with_name("parametros.json").read_text(encoding="utf-8")
    return cast("dict[str, Any]", json.loads(texto))


def test_categoria_desconhecida_no_teste(tmp_path: Path) -> None:
    novo = LinhaPa(
        artefato("pa_202301"),
        500,
        competencia_processamento="202301",
        procedimento="0999999999",
        cbo="99999X",
    )
    cenario = cenario_baseline(tmp_path, extras=((novo, "APROVADO_TOTAL"),))
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    parametros = _parametros(run.saidas[0].caminho)
    assert "0999999999" not in parametros["vocabulario"]["procedimento"]
    assert parametros["desconhecidas"]["CALIBRACAO"]["procedimento"] == 1
    assert parametros["desconhecidas"]["CALIBRACAO"]["cbo"] == 1
    linhas = {(r[0], r[1]) for r in _predicoes(run.saidas[0].caminho)}
    assert (novo.row_id, "B_ML") in linhas


def test_mesma_saida_com_mesma_semente(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    runs = [
        fit_baseline(
            cenario.split,
            FEATURES_PADRAO,
            cenario.config,
            tmp_path / nome,
            rotulos=cenario.rotulos,
            relogio=_relogio,
        )
        for nome in ("a", "b")
    ]
    assert runs[0].run_id == runs[1].run_id
    assert runs[0].semente == cenario.config.semente == 2027
    assert runs[0].saidas[0].hash_logico == runs[1].saidas[0].hash_logico
    assert _parametros(runs[0].saidas[0].caminho) == _parametros(runs[1].saidas[0].caminho)


def test_baseline_aprende_sinal_plantado(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    procedimento = {linha.row_id: linha.procedimento for linha in cenario.linhas}
    calibracao = [
        r for r in _predicoes(run.saidas[0].caminho) if r[1] == "B_ML" and r[2] == "CALIBRACAO"
    ]
    assert calibracao
    for row_id, _, _, resultado in calibracao:
        esperado = "ALERTA" if procedimento[row_id] == PROC_REJEITADO else "SEM_ALERTA"
        assert procedimento[row_id] in {PROC_REJEITADO, PROC_APROVADO}
        assert resultado == esperado


def test_controle_trivial_prediz_classe_prevalente_do_treino(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    triviais = [r for r in _predicoes(run.saidas[0].caminho) if r[1] == "CONTROLE_TRIVIAL"]
    assert triviais
    assert {r[3] for r in triviais} == {"SEM_ALERTA"}
    assert _parametros(run.saidas[0].caminho)["classe_prevalente"] == "APROVADO_TOTAL"
    assert run.metodo is MetodoId.B_ML


def test_exploratorio_nao_le_nem_pontua_o_teste(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    assert cenario.split.particoes is not None
    Path(cenario.split.particoes[Particao.TESTE].caminho).unlink()
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    particoes = {r[2] for r in _predicoes(run.saidas[0].caminho)}
    assert particoes == {"DESENVOLVIMENTO", "CALIBRACAO"}
    assert cenario.split.particoes[Particao.TESTE] not in run.entradas


def test_aprovacao_parcial_fica_fora_do_ajuste(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    contagens = _parametros(run.saidas[0].caminho)["contagens_treino"]
    assert contagens["APROVADO_PARCIAL"] > 0
    assert contagens["usadas_no_ajuste"] == contagens["NAO_APROVADO"] + contagens["APROVADO_TOTAL"]


def test_baseline_sem_rotulos_e_recusado(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    with pytest.raises(ValueError, match="baseline_sem_rotulos"):
        fit_baseline(cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run")


def test_confirmatorio_com_dados_sinteticos_e_recusado(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path)
    config = RunConfig.model_validate(
        {
            "versao": "1",
            "modo": "CONFIRMATORIO",
            "origem_dados": "REAL",
            "freeze_id": f"frz_{'0' * 64}",
            "bootstrap": {"correcao": "HOLM"},
        }
    )
    with pytest.raises(PortaoRecusado):
        fit_baseline(
            cenario.split,
            FEATURES_PADRAO,
            config,
            tmp_path / "run",
            rotulos=cenario.rotulos,
            decisoes=tmp_path / "decisoes",
        )


def _extras_calibracao(rotulo: str, n: int = 12) -> tuple[tuple[LinhaPa, str], ...]:
    return tuple(
        (
            LinhaPa(
                artefato("pa_202301"),
                200 + i,
                competencia_processamento="202301",
                idade=900 + i,
                procedimento="0888888888",
                cnes="0000099",
            ),
            rotulo if i % 2 else "APROVADO_TOTAL",
        )
        for i in range(n)
    )


_AJUSTADOS_NO_DESENVOLVIMENTO = ("vocabulario", "numericos", "coeficientes", "intercepto")


def test_codificador_e_modelo_nao_mudam_com_a_calibracao(tmp_path: Path) -> None:
    base = cenario_baseline(tmp_path / "base")
    run = fit_baseline(
        base.split, FEATURES_PADRAO, base.config, tmp_path / "rb", rotulos=base.rotulos
    )
    esperado = _parametros(run.saidas[0].caminho)
    for nome, rotulo in (("rej", "NAO_APROVADO"), ("apr", "APROVADO_TOTAL")):
        alterado = cenario_baseline(tmp_path / nome, extras=_extras_calibracao(rotulo))
        run_alt = fit_baseline(
            alterado.split,
            FEATURES_PADRAO,
            alterado.config,
            tmp_path / f"r{nome}",
            rotulos=alterado.rotulos,
        )
        obtido = _parametros(run_alt.saidas[0].caminho)
        for chave in _AJUSTADOS_NO_DESENVOLVIMENTO:
            assert obtido[chave] == esperado[chave], chave


def _youden_de_referencia(pares: list[tuple[float, int]]) -> tuple[float, float]:
    positivos = sum(alvo for _, alvo in pares)
    negativos = len(pares) - positivos
    melhor: tuple[float, float] = (-2.0, 0.0)
    for limiar in sorted({escore for escore, _ in pares}, reverse=True):
        vp = sum(1 for e, a in pares if e >= limiar and a == 1)
        fp = sum(1 for e, a in pares if e >= limiar and a == 0)
        indice = vp / positivos - fp / negativos
        if indice > melhor[0]:
            melhor = (indice, limiar)
    return melhor


def test_limiar_escolhido_na_calibracao(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path, invertidas=("202301",))
    run = fit_baseline(
        cenario.split, FEATURES_PADRAO, cenario.config, tmp_path / "run", rotulos=cenario.rotulos
    )
    con = duckdb.connect()
    try:
        linhas = con.execute(
            "SELECT p.escore, r.rotulo FROM read_parquet($p) p JOIN read_parquet($r) r "
            "USING (row_id) WHERE p.metodo = 'B_ML' AND p.particao = 'CALIBRACAO' "
            "AND r.rotulo IN ('NAO_APROVADO', 'APROVADO_TOTAL')",
            {"p": run.saidas[0].caminho, "r": cenario.rotulos.caminho},
        ).fetchall()
    finally:
        con.close()
    pares = [(float(e), 1 if r == "NAO_APROVADO" else 0) for e, r in linhas]
    melhor, _ = _youden_de_referencia(pares)
    limiar = float(_parametros(run.saidas[0].caminho)["limiar"])
    assert any(abs(limiar - escore) < 1e-8 for escore, _ in pares)
    vp = sum(1 for e, a in pares if e >= limiar - 1e-9 and a == 1)
    fp = sum(1 for e, a in pares if e >= limiar - 1e-9 and a == 0)
    positivos = sum(a for _, a in pares)
    assert vp / positivos - fp / (len(pares) - positivos) == pytest.approx(melhor)
