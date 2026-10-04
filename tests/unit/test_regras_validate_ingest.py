"""`sustemporal validate --ingest`: pasta do ingest e registro temporal (SINTETICO)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq
import pytest

from sustemporal import cli
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.errors import ExitCode
from tests.fixtures.regras_ingest import MUNICIPIO_FORA, montar_ingest

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.regras_ingest import MundoIngest

_POLITICAS = ("atendimento", "processamento", "documented")


def _validar(mundo: MundoIngest, politica: str) -> int:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", politica]
    return cli.main([*argumentos, "--ingest", str(mundo.pasta), "--saida", str(mundo.saida)])


def _resultados(mundo: MundoIngest) -> list[tuple[RunResult, Path]]:
    caminhos = sorted(mundo.saida.glob("*/run_result.json"))
    return [
        (RunResult.model_validate_json(c.read_text(encoding="utf-8")), c.parent) for c in caminhos
    ]


def _unico(mundo: MundoIngest) -> tuple[RunResult, Path]:
    (resultado,) = _resultados(mundo)
    return resultado


def _tabela(resultado: RunResult, schema_id: str) -> list[dict[str, Any]]:
    caminho = next(s.caminho for s in resultado.saidas if s.schema_id == schema_id)
    linhas: list[dict[str, Any]] = pq.read_table(caminho).to_pylist()
    return linhas


def _estados(resultado: RunResult) -> dict[tuple[str, str], str]:
    return {(a["row_id"], a["rule_id"]): a["estado"] for a in _tabela(resultado, "avaliacoes.v1")}


def test_tres_politicas_pela_cli_so_mudam_a_selecao(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    por_politica = {}
    for politica in _POLITICAS:
        antes = {r.run_id for r, _ in _resultados(mundo)}
        assert _validar(mundo, politica) == ExitCode.OK
        (novo,) = [r for r, _ in _resultados(mundo) if r.run_id not in antes]
        por_politica[politica] = novo
    for resultado in por_politica.values():
        assert resultado.estado is EstadoExecucao.CONCLUIDA
    fixas = {
        p: sorted(e.dataset_id for e in r.entradas if e.schema_id != "selecao_versoes.v1")
        for p, r in por_politica.items()
    }
    assert len({tuple(v) for v in fixas.values()}) == 1
    assert {r.catalogo_regras_sha256 for r in por_politica.values()} == {
        por_politica["atendimento"].catalogo_regras_sha256
    }
    selecoes = {
        next(e.dataset_id for e in r.entradas if e.schema_id == "selecao_versoes.v1")
        for r in por_politica.values()
    }
    assert len(selecoes) == len(_POLITICAS)
    atend = _estados(por_politica["atendimento"])
    proc = _estados(por_politica["processamento"])
    chaves_cnes = [k for k in atend if k[1] == "ESTAB_CBO_CNES" and k[0].endswith("#0")]
    assert chaves_cnes
    assert {atend[k] for k in chaves_cnes} == {"CONFORME"}
    assert {proc[k] for k in chaves_cnes} == {"VIOLACAO"}
    documentada = set(_estados(por_politica["documented"]).values())
    assert documentada <= {"INCONCLUSIVO", "NAO_APLICAVEL"}


def test_linha_fisica_repetida_entre_partes_conta_duas_vezes(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    repetidas = {k[0] for k in _estados(resultado) if k[0].endswith("#0")}
    assert len(repetidas) == 2


def test_territorio_exclui_e_conta_linhas_fora(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    avaliados = {k[0] for k in _estados(resultado)}
    assert not any(k.endswith("#2") for k in avaliados)
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1}
    assert MUNICIPIO_FORA not in recorte["municipios"]


def test_mes_vizinho_ausente_e_inconclusivo_nunca_o_vizinho(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sigtap_fev_ausente=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    selecoes = [s for s in _tabela(resultado, "selecao_versoes.v1") if s["fonte"] == "SIGTAP"]
    assert selecoes
    assert {s["competencia_requerida"] for s in selecoes} == {"202302"}
    assert {s["estado"] for s in selecoes} == {"AUSENTE"}
    estados = _estados(resultado)
    for selecao in selecoes:
        assert estados[(selecao["row_id"], selecao["rule_id"])] == "INCONCLUSIVO"


def test_versoes_concorrentes_da_producao_sao_recusadas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, concorrente=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_sem_cobertura_nenhuma_violacao_por_ausencia(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sem_cobertura=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    assert "VIOLACAO" not in set(_estados(resultado).values())


def test_manifesto_ausente_sai_com_config_invalida_sem_saidas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sem_manifesto=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_entrada_e_ingest_sao_mutuamente_exclusivos(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    argumentos += ["--ingest", str(mundo.pasta), "--entrada", str(tmp_path / "e.json")]
    with pytest.raises(SystemExit) as erro:
        cli.main(argumentos)
    assert erro.value.code == 2
