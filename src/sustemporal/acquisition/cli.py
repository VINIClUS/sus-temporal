"""Comandos `acquire` e `watch` da CLI."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.fetch import fetch_source, nomes_listados
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.sources import (
    carregar_catalogo,
    competencias_auxiliares,
    requisicao_listagem,
    requisicoes_da_listagem,
    requisicoes_documentos,
)
from sustemporal.contracts.artifacts import MotivoRequisicao, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    CompetenciaArquivo,
    CompetenciaAtendimento,
    CompetenciaProcessamento,
)
from sustemporal.errors import ConfigInvalida, ExitCode

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Iterable

    from sustemporal.acquisition.sources import CatalogoFontes
    from sustemporal.contracts.artifacts import ArtifactObservation, SourceRequest
    from sustemporal.contracts.config import PilotSpec, RunConfig

    Obter = Callable[[SourceRequest], ArtifactObservation]

__all__ = ["configurar_parser", "executar_acquire", "executar_watch"]

logger = logging.getLogger(__name__)

CATALOGO_PADRAO = Path("catalog/sources.yaml")
NOME_MANIFESTO_AQUISICAO = "aquisicao.jsonl"
PASSADAS = ("primaria", "auxiliar", "documentos")
_SEM_SELECAO = {FamiliaFonte.SIA_PA, FamiliaFonte.DOCUMENTO, FamiliaFonte.TERRITORIO_DRS}


def configurar_parser(sub: argparse.ArgumentParser) -> None:
    if sub.prog.endswith("acquire"):
        sub.add_argument("--passada", choices=PASSADAS, default="primaria")
        sub.add_argument("--competencias-atendimento", type=Path, default=None)
        sub.add_argument("--reobservar", action="store_true")


def _caminhos(config: RunConfig) -> tuple[Path, Path]:
    store = Path(config.runtime.raiz_dados) / "raw"
    manifesto = Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO
    return store, manifesto


def _catalogo(config: RunConfig) -> CatalogoFontes:
    return carregar_catalogo(Path(config.catalogos.get("fontes", str(CATALOGO_PADRAO))))


def _piloto(config: RunConfig) -> PilotSpec:
    if config.piloto is None:
        raise ConfigInvalida("acquire_exige_secao_piloto")
    return config.piloto


def _ler_competencias(caminho: Path | None) -> list[CompetenciaAtendimento]:
    """Uma competência de atendimento AAAAMM por linha, observada nos registros (passada 1)."""
    if caminho is None:
        raise ConfigInvalida("passada_auxiliar_exige_competencias_atendimento")
    try:
        linhas = caminho.read_text(encoding="utf-8").split()
        return [CompetenciaAtendimento(linha) for linha in linhas]
    except (OSError, ValueError) as erro:
        raise ConfigInvalida(f"competencias_atendimento_invalidas erro={erro}") from erro


def _por_listagem(
    catalogo: CatalogoFontes,
    fonte: FamiliaFonte,
    competencias: Iterable[CompetenciaArquivo],
    contexto: tuple[str, Path, Obter, MotivoRequisicao],
) -> list[SourceRequest]:
    uf, store, obter, motivo = contexto
    listagem = obter(requisicao_listagem(catalogo, fonte, motivo=motivo))
    if listagem.resultado is not ResultadoTentativa.OBTIDO:
        logger.error("listagem_nao_obtida fonte=%s resultado=%s", fonte, listagem.resultado)
        return []
    nomes = nomes_listados(store, listagem)
    return requisicoes_da_listagem(catalogo, fonte, uf, competencias, nomes, motivo=motivo)


def _ja_obtidas(manifesto: Path) -> set[str]:
    estado = Manifesto(manifesto).ler()
    return {
        o.request_sha256 for o in estado.observacoes if o.resultado is ResultadoTentativa.OBTIDO
    }


def _planejar(args: argparse.Namespace, config: RunConfig, obter: Obter) -> list[SourceRequest]:
    catalogo = _catalogo(config)
    if args.passada == "documentos":
        return requisicoes_documentos(catalogo)
    piloto = _piloto(config)
    store, _ = _caminhos(config)
    processamento = [CompetenciaProcessamento(c.valor) for c in piloto.competencias_processamento]
    if args.passada == "primaria":
        competencias = [CompetenciaArquivo(c.valor) for c in processamento]
        contexto = (piloto.uf, store, obter, MotivoRequisicao.PRIMARIA)
        return _por_listagem(catalogo, FamiliaFonte.SIA_PA, competencias, contexto)
    atendimento = _ler_competencias(args.competencias_atendimento)
    auxiliares = competencias_auxiliares(atendimento, processamento)
    contexto = (piloto.uf, store, obter, MotivoRequisicao.AUXILIAR_DERIVADA)
    fontes = [f for f in piloto.familias_fontes if f not in _SEM_SELECAO]
    return [r for f in fontes for r in _por_listagem(catalogo, f, auxiliares, contexto)]


def executar_acquire(args: argparse.Namespace, config: RunConfig) -> int:
    """Passada primária (SIA-PA), auxiliar (CNES/SIGTAP das competências observadas) ou documentos.

    Raises:
        RedeProibida: fonte remota com `rede_permitida` falso (a recusa fica no manifesto).
        ConfigInvalida: piloto ausente, catálogo inválido ou competências de atendimento ausentes.
    """
    store, manifesto = _caminhos(config)
    buscar = partial(
        fetch_source,
        store=store,
        rede_permitida=config.runtime.rede_permitida,
        manifesto=manifesto,
    )
    observadas: list[ArtifactObservation] = []

    def obter(requisicao: SourceRequest) -> ArtifactObservation:
        observadas.append(buscar(requisicao))
        return observadas[-1]

    requisicoes = _planejar(args, config, obter)
    obtidas = set() if args.reobservar else _ja_obtidas(manifesto)
    pendentes = [r for r in requisicoes if r.sha256() not in obtidas]
    for requisicao in pendentes:
        obter(requisicao)
    falhas = [o for o in observadas if o.resultado is not ResultadoTentativa.OBTIDO]
    logger.info(
        "acquire_concluido passada=%s requisicoes=%d puladas=%d falhas=%d",
        args.passada,
        len(requisicoes),
        len(requisicoes) - len(pendentes),
        len(falhas),
    )
    return int(ExitCode.FALHA_OPERACIONAL if falhas else ExitCode.OK)


def executar_watch(args: argparse.Namespace, config: RunConfig) -> int:
    raise NotImplementedError
