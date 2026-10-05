"""Apoio aos testes da CLI `freeze` e `evaluate` com cenário SINTETICO rotulado REAL (T11).

Decisões G0/G2 são escritas só no diretório temporário do teste; nada aqui é dado real nem
decisão humana.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sustemporal.cli import main
from sustemporal.config import load_config
from sustemporal.contracts.experiment import FreezeManifest, TipoExecucao
from sustemporal.errors import ExitCode
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao
from tests.fixtures.protocolo_confirmatorio import (
    CATALOGO_SIA_PA,
    reescrever_split_como_real,
    runs_compativeis,
)
from tests.fixtures.protocolo_dados import cenario_baseline

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from sustemporal.contracts import RunResult
    from tests.fixtures.protocolo_dados import Cenario

REGISTRO = "registro_execucoes.jsonl"


def config_yaml(raiz: Path, **extra: str) -> Path:
    """Config da CLI; com `extra` (ex.: `modo`, `freeze_id`) é a config confirmatória."""
    linhas = [
        'versao: "1"',
        "origem_dados: REAL",
        "runtime:",
        f"  raiz_saidas: {raiz / 'saidas'}",
        f"  dir_congelamentos: {raiz / 'frozen'}",
        "bootstrap:",
        "  correcao: HOLM",
        "  reamostragens: 50",
        "catalogos:",
        f"  esquema_sia_pa: {CATALOGO_SIA_PA}",
        *(f"{chave}: {valor}" for chave, valor in extra.items()),
    ]
    caminho = raiz / ("config_confirmatoria.yaml" if extra else "config.yaml")
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def executar_cli(argumentos: list[str]) -> int:
    """Código de saída da CLI, inclusive o `SystemExit` do argparse para opção desconhecida."""
    try:
        return int(main(argumentos))
    except SystemExit as saida:
        return int(saida.code) if isinstance(saida.code, int) else 1


def config_confirmatoria_yaml(raiz: Path, freeze: str) -> Path:
    return config_yaml(raiz, modo="CONFIRMATORIO", freeze_id=freeze)


def congelar_pela_cli(raiz: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Cenario, str]:
    """Constrói o split, congela pela CLI (G0) e abre o teste (G2); devolve o `freeze_id`."""
    cenario = cenario_baseline(raiz / "saidas", competencias=("202001", "202301", "202401"))
    reescrever_split_como_real(raiz / "saidas" / "split")
    monkeypatch.chdir(raiz)
    monkeypatch.setattr("sustemporal.evaluation.cli.versao_codigo", lambda _: CODIGO_LIMPO)
    decisoes = raiz / "experiments" / "decisions"
    escrever_decisao(decisoes, "G0", "CONTINUAR")
    assert main(["freeze", "--config", str(config_yaml(raiz))]) == ExitCode.OK
    (manifesto,) = sorted((raiz / "frozen").glob("frz_*.json"))
    escrever_decisao(decisoes, "G2", "ABRIR_TESTE", freeze_id=manifesto.stem)
    return cenario, manifesto.stem


def manifesto_da_cli(raiz: Path, freeze: str) -> FreezeManifest:
    texto = (raiz / "frozen" / f"{freeze}.json").read_text(encoding="utf-8")
    return FreezeManifest.model_validate_json(texto)


def nome_do_arquivo_da_execucao(run: RunResult) -> str:
    """O do produtor: `run.json` no baseline, `run_result.json` no motor de regras."""
    return "run.json" if run.tipo is TipoExecucao.BASELINE_ML else "run_result.json"


def gravar_runs(raiz: Path, runs: list[RunResult]) -> None:
    for run in runs:
        destino = raiz / "saidas" / "runs" / run.run_id
        destino.mkdir(parents=True, exist_ok=True)
        (destino / nome_do_arquivo_da_execucao(run)).write_text(
            run.model_dump_json(), encoding="utf-8"
        )


def runs_da_cli(raiz: Path, cenario: Cenario, freeze: str) -> list[RunResult]:
    config = load_config(config_confirmatoria_yaml(raiz, freeze))
    manifesto = manifesto_da_cli(raiz, freeze)
    return runs_compativeis(cenario, manifesto, config, raiz / "saidas" / "runs")
