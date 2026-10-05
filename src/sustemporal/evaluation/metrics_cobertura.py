"""Cobertura dos resultados de cada método sobre a população avaliada (T11).

Cada registro da partição avaliada precisa de um resultado de cada método. No confirmatório, o
método que omite registros, ou traz resultado de registros de fora da população sem declarar as
outras partições entre as entradas, é recusado antes de qualquer métrica; no exploratório só as
contagens vão para as notas do relatório e o registro sem resultado segue contando como abstenção.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import declara_outras_particoes

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sustemporal.contracts import FreezeManifest, RunResult
    from sustemporal.evaluation.metrics_calculo import Situacao

__all__ = ["Cobertura", "calcular_coberturas", "exigir_cobertura_completa", "notas_de_cobertura"]


@dataclass(frozen=True)
class Cobertura:
    """Registros da população sem resultado (`ausentes`) e resultados fora dela (`extras`)."""

    metodo: str
    ausentes: int
    extras: int
    run: RunResult


def calcular_coberturas(
    populacao: Iterable[str],
    situacoes: Mapping[str, Mapping[str, Situacao]],
    execucoes: Mapping[str, RunResult],
) -> list[Cobertura]:
    """Cobertura de cada método de `situacoes`, na ordem dele, contra o `row_id` da população."""
    esperados = set(populacao)
    coberturas = []
    for metodo, resultados in situacoes.items():
        obtidos = set(resultados)
        coberturas.append(
            Cobertura(metodo, len(esperados - obtidos), len(obtidos - esperados), execucoes[metodo])
        )
    return coberturas


def exigir_cobertura_completa(coberturas: Iterable[Cobertura], manifesto: FreezeManifest) -> None:
    """Recusa o método sem resultado de algum registro avaliado ou com resultado a mais.

    Resultado de registros de fora da população só passa se a execução traz, entre as entradas, a
    população de outra partição congelada (o baseline lê as que ajusta e avalia).

    Raises:
        PortaoRecusado: `execucao_com_cobertura_incompleta metodo=... ausentes=... extras=...`,
            para o primeiro método, em ordem alfabética, que não cobre a população.
    """
    for cobertura in sorted(coberturas, key=lambda c: c.metodo):
        extras_declarados = declara_outras_particoes(manifesto, cobertura.run)
        if cobertura.ausentes or (cobertura.extras and not extras_declarados):
            raise PortaoRecusado(
                f"execucao_com_cobertura_incompleta metodo={cobertura.metodo} "
                f"ausentes={cobertura.ausentes} extras={cobertura.extras}"
            )


def notas_de_cobertura(coberturas: Iterable[Cobertura]) -> tuple[str, ...]:
    """Uma nota com as contagens de cada método, em ordem alfabética."""
    return tuple(
        f"cobertura_dos_resultados metodo={c.metodo} ausentes={c.ausentes} extras={c.extras}"
        for c in sorted(coberturas, key=lambda c: c.metodo)
    )
