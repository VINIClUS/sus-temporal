"""Portões G0/G1/G2: só decisões registradas por humanos liberam etapas congeladas."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import DecisaoPortao, ModoExecucao, Portao
from sustemporal.errors import PortaoRecusado
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from sustemporal.contracts.config import RunConfig

logger = logging.getLogger(__name__)

_DECISOES_QUE_LIBERAM = {
    Portao.G0: {"CONTINUAR", "AMPLIAR_SP", "RESTRINGIR_FAMILIAS"},
    Portao.G1: {"APROVADO"},
    Portao.G2: {"ABRIR_TESTE"},
}


def carregar_decisoes(diretorio: Path, portao: Portao) -> list[DecisaoPortao]:
    """Lê as decisões do portão; arquivo inválido recusa o portão em vez de ser ignorado.

    Raises:
        PortaoRecusado: algum registro de decisão é inválido.
    """
    if not diretorio.is_dir():
        return []
    decisoes = []
    for arquivo in sorted(diretorio.glob("*.yaml")):
        if arquivo.name.startswith("MODELO_"):
            continue
        try:
            decisao = DecisaoPortao.model_validate(carregar_yaml(arquivo))
        except ValidationError as erro:
            raise PortaoRecusado(f"decisao_invalida arquivo={arquivo.name}") from erro
        if decisao.portao is portao:
            decisoes.append(decisao)
    return decisoes


def exigir_portao(
    diretorio: Path, portao: Portao, *, freeze_id: str | None = None
) -> DecisaoPortao:
    """Exige decisão humana que libere o portão (e o congelamento indicado, no G2).

    Raises:
        PortaoRecusado: não há decisão liberadora registrada.
    """
    liberadoras = [
        decisao
        for decisao in carregar_decisoes(diretorio, portao)
        if decisao.decisao in _DECISOES_QUE_LIBERAM[portao]
        and (freeze_id is None or decisao.freeze_id == freeze_id)
    ]
    if not liberadoras:
        raise PortaoRecusado(f"portao_sem_decisao_liberadora portao={portao} freeze={freeze_id}")
    escolhida = max(liberadoras, key=lambda decisao: decisao.data)
    logger.info("portao_liberado portao=%s data=%s", portao, escolhida.data)
    return escolhida


def exigir_confirmatorio_valido(config: RunConfig, origem: OrigemDados) -> None:
    """Recusa execução confirmatória com dados sintéticos ou sem G2 para o congelamento.

    Raises:
        PortaoRecusado: modo confirmatório sem dados reais ou sem decisão G2.
    """
    if config.modo is not ModoExecucao.CONFIRMATORIO:
        return
    if origem is not OrigemDados.REAL:
        raise PortaoRecusado(f"confirmatorio_exige_dados_reais origem={origem}")
    exigir_portao(Path(config.runtime.dir_decisoes), Portao.G2, freeze_id=config.freeze_id)
