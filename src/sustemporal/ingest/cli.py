"""Comando `sustemporal ingest`: normaliza as versões do manifesto e gera a cobertura (T04).

Cada versão de conteúdo do manifesto de aquisição é despachada pela família (`ingest/registry.py`)
com os leiautes do catálogo. Quarentena, arquivo ausente e família reservada viram resultados
registrados, nunca tabela vazia. Saídas em `<raiz_saidas>/ingest/`: os Parquet canônicos,
`datasets.jsonl` (um `DatasetRef` por linha, inclusive a cobertura) e `resultados.jsonl`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import FamiliaFonte, LayoutSpec, OrigemDados
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.ingest.cnes import RESERVADAS, FamiliaReservada, carregar_leiautes_cnes
from sustemporal.ingest.coverage import build_coverage
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.ingest.registry import normalizador
from sustemporal.ingest.sigtap_zip import carregar_leiautes_sigtap
from sustemporal.ingest.territorio import carregar_territorio
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    import argparse

    from sustemporal.contracts import ArtifactVersion, DatasetRef, RuntimeConfig
    from sustemporal.contracts.config import PilotSpec, RunConfig

__all__ = ["executar_ingest"]

logger = logging.getLogger(__name__)

LEIAUTE_SIA_PA = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "sia_pa.yaml"
# Mesmo endereçamento da aquisição (acquisition/cli.py): conteúdo em <raiz_dados>/raw.
SUBPASTA_ARMAZENAMENTO = "raw"
_NORMALIZAVEIS = frozenset(
    {FamiliaFonte.SIA_PA, FamiliaFonte.SIGTAP, FamiliaFonte.CNES_PF, FamiliaFonte.CNES_ST}
)


class _Normalizar(Protocol):
    def __call__(
        self,
        artifact: ArtifactVersion,
        layout: LayoutSpec,
        out: Path,
        *,
        runtime: RuntimeConfig | None = ...,
        origem_dados: OrigemDados = ...,
    ) -> DatasetRef: ...


def _leiautes(fonte: FamiliaFonte) -> list[LayoutSpec]:
    if fonte is FamiliaFonte.SIA_PA:
        return [LayoutSpec.model_validate(carregar_yaml(LEIAUTE_SIA_PA))]
    if fonte is FamiliaFonte.SIGTAP:
        return list(carregar_leiautes_sigtap().values())
    leiautes = carregar_leiautes_cnes()
    return [leiautes[fonte]] if fonte in leiautes else []


def _piloto(config: RunConfig) -> PilotSpec:
    if config.piloto is None:
        raise ConfigInvalida("ingest_exige_piloto")
    carregar_territorio(Path(config.piloto.territorio), uf=config.piloto.uf)
    return config.piloto


def _resultado(
    versao: ArtifactVersion, layout_id: str | None, estado: str, **extras: str | None
) -> dict[str, str | None]:
    return {
        "artifact_id": versao.artifact_id,
        "fonte": versao.chave.fonte.value,
        "leiaute": layout_id,
        "estado": estado,
        **extras,
    }


class _Execucao:
    def __init__(self, config: RunConfig, saida: Path) -> None:
        raiz = Path(config.runtime.raiz_dados) / SUBPASTA_ARMAZENAMENTO
        self.runtime = config.runtime.model_copy(update={"raiz_dados": str(raiz)})
        self.origem = config.origem_dados or OrigemDados.SINTETICO
        self.saida = saida
        self.datasets: list[DatasetRef] = []
        self.resultados: list[dict[str, str | None]] = []

    def normalizar(self, versao: ArtifactVersion) -> None:
        fonte = versao.chave.fonte
        if fonte in RESERVADAS:
            motivo = f"familia_reservada familia={RESERVADAS[fonte]}"
            self.resultados.append(_resultado(versao, None, "FAMILIA_RESERVADA", motivo=motivo))
            return
        funcao = cast("_Normalizar", normalizador(fonte))
        for layout in _leiautes(fonte):
            self._uma(funcao, versao, layout)

    def _uma(self, funcao: _Normalizar, versao: ArtifactVersion, layout: LayoutSpec) -> None:
        try:
            dataset = funcao(
                versao, layout, self.saida, runtime=self.runtime, origem_dados=self.origem
            )
        except QuarentenaLeitura as erro:
            estado, motivo = erro.estado.value, erro.motivo
        except (ArquivoAusente, FamiliaReservada) as erro:
            estado, motivo = type(erro).__name__.upper(), str(erro)
        else:
            self.datasets.append(dataset)
            resultado = _resultado(versao, layout.layout_id, "NORMALIZADO")
            self.resultados.append({**resultado, "dataset_id": dataset.dataset_id})
            return
        logger.warning("ingest_sem_tabela id=%s estado=%s", versao.artifact_id, estado)
        self.resultados.append(_resultado(versao, layout.layout_id, estado, motivo=motivo))


def _gravar_jsonl(destino: Path, linhas: list[str]) -> None:
    temporario = destino.with_name(f".{destino.name}.tmp")
    temporario.write_text("".join(f"{linha}\n" for linha in linhas), encoding="utf-8")
    temporario.replace(destino)


def executar_ingest(args: argparse.Namespace, config: RunConfig) -> int:
    """Normaliza cada versão do manifesto de aquisição pela família e grava a cobertura.

    Raises:
        ConfigInvalida: configuração sem piloto ou com território inválido.
    """
    piloto = _piloto(config)
    saida = Path(config.runtime.raiz_saidas) / "ingest"
    saida.mkdir(parents=True, exist_ok=True)
    execucao = _Execucao(config, saida)
    manifesto = Manifesto(Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO).ler()
    for versao in manifesto.versoes.values():
        if versao.chave.fonte in {*RESERVADAS, *_NORMALIZAVEIS}:
            execucao.normalizar(versao)
    sia_pa = [d for d in execucao.datasets if d.schema_id == "sia_pa.v1"]
    auxiliares = [d for d in execucao.datasets if d.schema_id != "sia_pa.v1"]
    competencias = [c.valor for c in piloto.competencias_processamento]
    cobertura = build_coverage(
        sia_pa,
        auxiliares,
        competencias,
        saida,
        runtime=execucao.runtime,
        origem_dados=execucao.origem,
    )
    datasets = [*execucao.datasets, cobertura]
    _gravar_jsonl(saida / "datasets.jsonl", [d.model_dump_json() for d in datasets])
    _gravar_jsonl(saida / "resultados.jsonl", [json.dumps(r) for r in execucao.resultados])
    logger.info(
        "ingest_concluido versoes=%s datasets=%s args=%s",
        len(manifesto.versoes),
        len(datasets),
        vars(args).get("comando"),
    )
    return ExitCode.OK
