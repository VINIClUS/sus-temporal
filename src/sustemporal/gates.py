"""Portões G0/G1/G2: só decisões registradas por humanos liberam etapas congeladas."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import DecisaoPortao, ModoExecucao, Portao
from sustemporal.contracts.temporal import TipoPolitica
from sustemporal.errors import PortaoRecusado
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sustemporal.contracts.config import RunConfig
    from sustemporal.contracts.temporal import PoliticaTemporal

logger = logging.getLogger(__name__)

DIR_DECISOES = Path("experiments/decisions")

_DECISOES_QUE_LIBERAM = {
    Portao.G0: {"CONTINUAR", "AMPLIAR_SP", "RESTRINGIR_FAMILIAS"},
    Portao.G1: {"APROVADO"},
    Portao.G2: {"ABRIR_TESTE"},
}


def _recusar_link_simbolico(diretorio: Path) -> None:
    caminhos = [diretorio] if diretorio.is_absolute() else [diretorio, *diretorio.parents]
    for caminho in caminhos:
        if caminho.is_symlink():
            raise PortaoRecusado(f"decisoes_em_link_simbolico caminho={caminho}")


def _arquivos_de_decisao(diretorio: Path) -> list[Path]:
    arquivos = sorted([*diretorio.glob("*.yaml"), *diretorio.glob("*.yml")])
    candidatos = [arquivo for arquivo in arquivos if not arquivo.name.startswith("MODELO_")]
    for arquivo in candidatos:
        if arquivo.is_symlink():
            raise PortaoRecusado(f"decisoes_em_link_simbolico caminho={arquivo}")
    return candidatos


def carregar_decisoes(diretorio: Path, portao: Portao) -> list[DecisaoPortao]:
    """Lê as decisões `*.yaml`/`*.yml` do portão; arquivo inválido recusa o portão.

    Raises:
        PortaoRecusado: registro de decisão inválido, ou diretório, ancestral relativo ou
            arquivo de decisão que é link simbólico.
    """
    _recusar_link_simbolico(diretorio)
    if not diretorio.is_dir():
        return []
    decisoes = []
    for arquivo in _arquivos_de_decisao(diretorio):
        try:
            decisao = DecisaoPortao.model_validate(carregar_yaml(arquivo))
        except (ValueError, OSError) as erro:
            raise PortaoRecusado(f"decisao_invalida arquivo={arquivo.name}") from erro
        if decisao.portao is portao:
            decisoes.append(decisao)
    return decisoes


def _ultima_decisao(decisoes: list[DecisaoPortao], portao: Portao) -> DecisaoPortao:
    data_mais_recente = max(decisao.data for decisao in decisoes)
    ultimas = [decisao for decisao in decisoes if decisao.data == data_mais_recente]
    if any(decisao != ultimas[0] for decisao in ultimas[1:]):
        raise PortaoRecusado(f"portao_decisoes_empatadas portao={portao} data={data_mais_recente}")
    return ultimas[0]


def exigir_portao(
    diretorio: Path,
    portao: Portao,
    *,
    freeze_id: str | None = None,
    hoje: date | None = None,
) -> DecisaoPortao:
    """Exige que a decisão humana mais recente do portão o libere (no G2, para o congelamento).

    Raises:
        PortaoRecusado: G2 sem congelamento, sem decisão, decisão datada depois de `hoje`
            (padrão: data UTC atual), decisões divergentes na mesma data ou a última não libera.
    """
    if portao is Portao.G2 and freeze_id is None:
        raise PortaoRecusado("portao_g2_exige_freeze_id")
    referencia = hoje if hoje is not None else datetime.now(UTC).date()
    aplicaveis = [
        decisao
        for decisao in carregar_decisoes(diretorio, portao)
        if freeze_id is None or decisao.freeze_id == freeze_id
    ]
    if not aplicaveis:
        raise PortaoRecusado(f"portao_sem_decisao portao={portao} freeze={freeze_id}")
    futuras = sorted(decisao.data for decisao in aplicaveis if decisao.data > referencia)
    if futuras:
        raise PortaoRecusado(
            f"decisao_no_futuro portao={portao} data={futuras[0]} hoje={referencia}"
        )
    escolhida = _ultima_decisao(aplicaveis, portao)
    if escolhida.decisao not in _DECISOES_QUE_LIBERAM[portao]:
        raise PortaoRecusado(
            f"portao_ultima_decisao_nao_libera portao={portao} decisao={escolhida.decisao} "
            f"data={escolhida.data}"
        )
    logger.info("portao_liberado portao=%s data=%s", portao, escolhida.data)
    return escolhida


def exigir_confirmatorio_valido(
    config: RunConfig,
    origem: OrigemDados,
    *,
    diretorio: Path = DIR_DECISOES,
    hoje: date | None = None,
) -> None:
    """Recusa execução confirmatória com dados sintéticos ou sem G2 para o congelamento.

    Raises:
        PortaoRecusado: modo confirmatório sem dados reais ou sem decisão G2 que o libere.
    """
    if config.modo is not ModoExecucao.CONFIRMATORIO:
        return
    if origem is not OrigemDados.REAL:
        raise PortaoRecusado(f"confirmatorio_exige_dados_reais origem={origem}")
    exigir_portao(diretorio, Portao.G2, freeze_id=config.freeze_id, hoje=hoje)


def exigir_politicas_resolvidas(politicas: Iterable[PoliticaTemporal], modo: ModoExecucao) -> None:
    """No confirmatório, recusa política não resolvida ou documentada com documento pendente.

    Raises:
        PortaoRecusado: política NAO_RESOLVIDA ou DOCUMENTADA com documento PENDENTE.
    """
    if modo is not ModoExecucao.CONFIRMATORIO:
        return
    for politica in politicas:
        if politica.tipo is TipoPolitica.NAO_RESOLVIDA:
            raise PortaoRecusado(
                f"politica_nao_resolvida_no_confirmatorio politica={politica.politica_id}"
            )
        if politica.tipo is TipoPolitica.DOCUMENTADA and politica.documento_pendente:
            raise PortaoRecusado(
                f"politica_com_documento_pendente_no_confirmatorio politica={politica.politica_id}"
            )
