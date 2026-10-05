"""Apoio aos testes da CLI `freeze` e `evaluate` com cenário SINTETICO rotulado REAL (T11).

Decisões G0/G2 são escritas só no diretório temporário do teste; nada aqui é dado real nem
decisão humana.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from sustemporal.cli import main
from sustemporal.config import load_config
from sustemporal.contracts.experiment import FreezeManifest, TipoExecucao
from sustemporal.errors import ExitCode
from sustemporal.rules.entrada import ARQUIVO_ENTRADA
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao
from tests.fixtures.protocolo_confirmatorio import (
    CATALOGO_SIA_PA,
    insumos_do_teste,
    reescrever_split_como_real,
    runs_compativeis,
)
from tests.fixtures.protocolo_dados import cenario_baseline
from tests.fixtures.protocolo_insumos import entradas_das_execucoes

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    import pytest

    from sustemporal.contracts import RunResult
    from sustemporal.rules.entrada import EntradaValidacao
    from tests.fixtures.protocolo_dados import Cenario

REGISTRO = "registro_execucoes.jsonl"


def catalogo_da_config(raiz: Path) -> Path:
    """Cópia do catálogo de esquema que a config congela, para os testes poderem alterá-la."""
    destino = raiz / "catalogos" / CATALOGO_SIA_PA.name
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CATALOGO_SIA_PA, destino)
    return destino


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
        f"  esquema_sia_pa: {catalogo_da_config(raiz)}",
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


def preparar_cli(raiz: Path, monkeypatch: pytest.MonkeyPatch) -> Cenario:
    """Constrói o split REAL e o G0, de dentro de `raiz`, sem os insumos das execuções."""
    cenario = cenario_baseline(raiz / "saidas", competencias=("202001", "202301", "202401"))
    reescrever_split_como_real(raiz / "saidas" / "split")
    monkeypatch.chdir(raiz)
    monkeypatch.setattr("sustemporal.evaluation.cli.versao_codigo", lambda _: CODIGO_LIMPO)
    escrever_decisao(raiz / "experiments" / "decisions", "G0", "CONTINUAR")
    return cenario


def gravar_insumos(raiz: Path, cenario: Cenario) -> Path:
    """`<raiz_saidas>/split/insumos/<politica_id>.json`: a entrada de validação de cada política."""
    pasta = raiz / "saidas" / "split" / "insumos"
    pasta.mkdir(parents=True, exist_ok=True)
    for politica, entrada in insumos_do_teste(cenario).items():
        (pasta / f"{politica}.json").write_text(entrada.model_dump_json(indent=2), encoding="utf-8")
    return pasta


def congelar_pela_cli(raiz: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Cenario, str]:
    """Constrói o split, congela pela CLI (G0) e abre o teste (G2); devolve o `freeze_id`."""
    cenario = preparar_cli(raiz, monkeypatch)
    gravar_insumos(raiz, cenario)
    decisoes = raiz / "experiments" / "decisions"
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


def gravar_runs(
    raiz: Path, runs: list[RunResult], *, entradas: Mapping[str, EntradaValidacao] | None = None
) -> None:
    """Grava cada execução, e a `entrada_validacao.json` das de regras (`entradas` a substitui)."""
    gravadas = {**entradas_das_execucoes(runs), **(entradas or {})}
    for run in runs:
        destino = raiz / "saidas" / "runs" / run.run_id
        destino.mkdir(parents=True, exist_ok=True)
        (destino / nome_do_arquivo_da_execucao(run)).write_text(
            run.model_dump_json(), encoding="utf-8"
        )
        if (entrada := gravadas.get(run.run_id)) is not None:
            (destino / ARQUIVO_ENTRADA).write_text(entrada.model_dump_json(), encoding="utf-8")


def runs_da_cli(raiz: Path, cenario: Cenario, freeze: str) -> list[RunResult]:
    config = load_config(config_confirmatoria_yaml(raiz, freeze))
    manifesto = manifesto_da_cli(raiz, freeze)
    return runs_compativeis(cenario, manifesto, config, raiz / "saidas" / "runs")
