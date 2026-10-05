"""Passos do fluxo pela CLI sobre o mundo SINTETICO da T14, cada um com o que produziu.

Cada passo anota o código de saída do comando em `Fluxo.codigos` e guarda o que os testes
inspecionam depois. Os comandos rodam de dentro da raiz do mundo (ver `preparar_mundo`); o
código limpo e a decisão G0 são de teste, escritos só no diretório temporário.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow.parquet as pq

from sustemporal.config import load_config
from sustemporal.contracts.experiment import Particao, RunResult, SplitManifest
from sustemporal.evaluation.split import carregar_spec
from sustemporal.execucoes import raiz_execucoes
from sustemporal.reporting.reproduce_etapas import derivar_protocolo, janela_do_ingest
from sustemporal.rules.ingest import ler_datasets
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao
from tests.fixtures.reproducao_mundo import (
    JANELAS,
    POLITICAS,
    Mundo,
    adquirir,
    comando,
    escrever_configs,
    preparar_mundo,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pytest

    from sustemporal.contracts.config import RunConfig

SPLITS = Path("config") / "splits.yaml"


@dataclass
class Fluxo:
    mundo: Mundo
    configs: Mapping[str, Path]
    codigos: dict[str, int] = field(default_factory=dict)
    ingest: Path | None = None
    execucoes: dict[tuple[str, str], RunResult] = field(default_factory=dict)
    split: SplitManifest | None = None
    freeze_id: str | None = None

    def config(self, nome: str) -> RunConfig:
        return load_config(self.configs[nome])


def iniciar(raiz: Path, mp: pytest.MonkeyPatch, *, threads: int = 1) -> Fluxo:
    """Mundo limpo, de dentro dele, com a versão de código de teste (limpa) no `freeze`.

    O diretório do mundo não é um repositório git: sem o patch, o `freeze` recusaria código sujo.
    """
    mundo = preparar_mundo(raiz)
    mp.chdir(raiz)
    mp.setattr("sustemporal.evaluation.cli.versao_codigo", lambda _: CODIGO_LIMPO)
    return Fluxo(mundo, escrever_configs(mundo, threads=threads))


def adquirir_e_ingerir(fluxo: Fluxo) -> None:
    fluxo.codigos.update({f"acquire_{n}": c for n, c in adquirir(fluxo.mundo).items()})
    configuracao = str(fluxo.configs["teste"])
    fluxo.codigos["ingest"] = comando("ingest", "--config", configuracao)
    (fluxo.ingest,) = sorted((fluxo.mundo.saidas / "ingest").iterdir())


def _runs(fluxo: Fluxo, janela: str) -> set[str]:
    raiz = raiz_execucoes(fluxo.config(janela))
    return {p.name for p in raiz.glob("val_*")} if raiz.is_dir() else set()


def _validar(fluxo: Fluxo, janela: str, politica: str, pasta: Path) -> None:
    antes = _runs(fluxo, janela)
    configuracao = str(fluxo.configs[janela])
    argumentos = [
        "validate",
        "--config",
        configuracao,
        "--policy",
        politica,
        "--ingest",
        str(pasta),
    ]
    fluxo.codigos[f"validate_{janela}_{politica}"] = comando(*argumentos)
    (novo,) = _runs(fluxo, janela) - antes
    caminho = raiz_execucoes(fluxo.config(janela)) / novo / "run_result.json"
    fluxo.execucoes[(janela, politica)] = RunResult.model_validate_json(caminho.read_text("utf-8"))


def validar_janelas(fluxo: Fluxo, janelas: tuple[str, ...] = tuple(JANELAS)) -> None:
    """`validate --ingest` das três políticas em cada janela pedida (DEV, CAL e TESTE)."""
    assert fluxo.ingest is not None
    for janela in janelas:
        competencias = JANELAS[janela]
        destino = fluxo.mundo.saidas / "janelas" / janela
        pasta = janela_do_ingest(fluxo.config(janela), fluxo.ingest, destino, competencias)
        for politica in POLITICAS:
            _validar(fluxo, janela, politica, pasta)


def linha_do_ingest(
    fluxo: Fluxo, *, processamento: str | None = None, atendimento: str, instrumento: str
) -> str:
    """`row_id` da única linha do SIA-PA com o atendimento e o instrumento pedidos."""
    assert fluxo.ingest is not None
    colunas = ["row_id", "competencia_processamento", "competencia_atendimento", "instrumento"]
    achados = [
        linha["row_id"]
        for ref in ler_datasets(fluxo.ingest)
        if ref.schema_id == "sia_pa.v1"
        for linha in pq.read_table(ref.caminho, columns=colunas).to_pylist()
        if linha["competencia_atendimento"] == atendimento
        and linha["instrumento"] == instrumento
        and processamento in (None, linha["competencia_processamento"])
    ]
    assert len(achados) == 1, achados
    return str(achados[0])


def derivar(fluxo: Fluxo) -> SplitManifest:
    """União, rótulos e partições em `<raiz_saidas>/split`, com os insumos do TESTE ao lado."""
    assert fluxo.ingest is not None
    destino = fluxo.mundo.saidas / "split"
    config = fluxo.config("teste")
    derivado = derivar_protocolo(config, fluxo.ingest, destino, spec=carregar_spec(SPLITS))
    fluxo.split = derivado.split
    teste = derivado.split.hash_por_particao[Particao.TESTE]
    (destino / "insumos").mkdir(exist_ok=True)
    for (janela, _), run in fluxo.execucoes.items():
        if janela == "teste" and run.entradas[0].hash_logico == teste:
            origem = raiz_execucoes(config) / run.run_id / "entrada_validacao.json"
            shutil.copyfile(origem, destino / "insumos" / f"{run.politica_id}.json")
    return derivado.split


def congelar_e_avaliar(fluxo: Fluxo) -> None:
    """`freeze` sem G0 (recusado), com a decisão G0 de teste, `evaluate` e `annotation-export`."""
    teste, cal = str(fluxo.configs["teste"]), str(fluxo.configs["cal"])
    fluxo.codigos["freeze_sem_g0"] = comando("freeze", "--config", teste)
    escrever_decisao(Path("experiments") / "decisions", "G0", "CONTINUAR")
    fluxo.codigos["freeze"] = comando("freeze", "--config", teste)
    (manifesto,) = sorted(fluxo.mundo.congelamentos.glob("frz_*.json"))
    fluxo.freeze_id = manifesto.stem
    base = ["--config", cal, "--freeze", fluxo.freeze_id]
    fluxo.codigos["evaluate_sem_exploratory"] = comando("evaluate", *base)
    fluxo.codigos["evaluate"] = comando("evaluate", *base, "--exploratory")
    fluxo.codigos["annotation_export"] = comando("annotation-export", *base)
