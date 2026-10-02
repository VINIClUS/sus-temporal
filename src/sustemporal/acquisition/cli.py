"""Comandos `acquire` e `watch` da CLI."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.fetch import fetch_source, nomes_listados
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.sources import (
    carregar_catalogo,
    competencias_auxiliares,
    partes_ausentes,
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
from sustemporal.hashing import sha256_arquivo

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Iterable

    from sustemporal.acquisition.sources import CatalogoFontes
    from sustemporal.contracts.artifacts import (
        ArtifactObservation,
        ArtifactVersion,
        SourceRequest,
    )
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


@dataclass
class _Contexto:
    uf: str
    store: Path
    obter: Obter
    motivo: MotivoRequisicao
    ausentes: list[tuple[FamiliaFonte, CompetenciaArquivo]] = field(default_factory=list)


def _por_listagem(
    catalogo: CatalogoFontes,
    fonte: FamiliaFonte,
    competencias: Iterable[CompetenciaArquivo],
    contexto: _Contexto,
) -> list[SourceRequest]:
    """Requisições da listagem; competência pedida sem arquivo listado fica em `ausentes`."""
    pedidas = sorted(set(competencias))
    listagem = contexto.obter(requisicao_listagem(catalogo, fonte, motivo=contexto.motivo))
    if listagem.resultado is not ResultadoTentativa.OBTIDO:
        logger.error("listagem_nao_obtida fonte=%s resultado=%s", fonte, listagem.resultado)
        return []
    nomes = nomes_listados(contexto.store, listagem)
    requisicoes = requisicoes_da_listagem(
        catalogo, fonte, contexto.uf, pedidas, nomes, motivo=contexto.motivo
    )
    encontradas = {r.chave.competencia_arquivo for r in requisicoes}
    item = catalogo.fonte(fonte)
    for competencia in pedidas:
        sem_parte = partes_ausentes(item, competencia, requisicoes)
        if competencia not in encontradas or sem_parte:
            contexto.ausentes.append((fonte, competencia))
    return requisicoes


def _conteudo_integro(store: Path, versao: ArtifactVersion) -> bool:
    caminho = store / versao.caminho_conteudo
    if not caminho.is_file() or caminho.stat().st_size != versao.tamanho_bytes:
        return False
    return sha256_arquivo(caminho) == versao.sha256


def _ja_obtidas(manifesto: Path, store: Path) -> set[str]:
    """Pedidos cuja observação mais recente é OBTIDO com bytes guardados ainda íntegros.

    A observação mais recente decide: uma versão antiga íntegra não cobre a mais nova perdida.
    """
    estado = Manifesto(manifesto).ler()
    recentes = {o.request_sha256: o for o in estado.observacoes}
    obtidas: set[str] = set()
    for pedido, observacao in recentes.items():
        versao = estado.versoes.get(observacao.artifact_id or "")
        if observacao.resultado is not ResultadoTentativa.OBTIDO or versao is None:
            continue
        if _conteudo_integro(store, versao):
            obtidas.add(pedido)
        else:
            logger.warning(
                "conteudo_guardado_ausente_ou_divergente artefato=%s", versao.artifact_id
            )
    return obtidas


def _planejar(
    args: argparse.Namespace, config: RunConfig, obter: Obter, ausentes: list[object]
) -> list[SourceRequest]:
    catalogo = _catalogo(config)
    if args.passada == "documentos":
        return requisicoes_documentos(catalogo)
    piloto = _piloto(config)
    store, _ = _caminhos(config)
    processamento = [CompetenciaProcessamento(c.valor) for c in piloto.competencias_processamento]
    if args.passada == "primaria":
        competencias = [CompetenciaArquivo(c.valor) for c in processamento]
        contexto = _Contexto(piloto.uf, store, obter, MotivoRequisicao.PRIMARIA)
        requisicoes = _por_listagem(catalogo, FamiliaFonte.SIA_PA, competencias, contexto)
        ausentes.extend(contexto.ausentes)
        return requisicoes
    atendimento = _ler_competencias(args.competencias_atendimento)
    auxiliares = competencias_auxiliares(atendimento, processamento)
    contexto = _Contexto(piloto.uf, store, obter, MotivoRequisicao.AUXILIAR_DERIVADA)
    fontes = [f for f in piloto.familias_fontes if f not in _SEM_SELECAO]
    requisicoes = [r for f in fontes for r in _por_listagem(catalogo, f, auxiliares, contexto)]
    ausentes.extend(contexto.ausentes)
    return requisicoes


def executar_acquire(args: argparse.Namespace, config: RunConfig) -> int:
    """Passada primária (SIA-PA), auxiliar (CNES/SIGTAP das competências observadas) ou documentos.

    Sai FALHA_OPERACIONAL (5) se alguma tentativa não foi obtida ou se alguma competência pedida
    não aparece na listagem; a ausência fica no log e na própria listagem observada.

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

    ausentes: list[object] = []
    requisicoes = _planejar(args, config, obter, ausentes)
    obtidas = set() if args.reobservar else _ja_obtidas(manifesto, store)
    pendentes = [r for r in requisicoes if r.sha256() not in obtidas]
    for requisicao in pendentes:
        obter(requisicao)
    falhas = [o for o in observadas if o.resultado is not ResultadoTentativa.OBTIDO]
    logger.info(
        "acquire_concluido passada=%s requisicoes=%d puladas=%d falhas=%d ausentes=%d",
        args.passada,
        len(requisicoes),
        len(requisicoes) - len(pendentes),
        len(falhas),
        len(ausentes),
    )
    incompleta = bool(falhas or ausentes)
    return int(ExitCode.FALHA_OPERACIONAL if incompleta else ExitCode.OK)


def executar_watch(args: argparse.Namespace, config: RunConfig) -> int:
    raise NotImplementedError
