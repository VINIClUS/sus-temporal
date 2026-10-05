"""Cobertura dos resultados de cada método sobre a população avaliada (T11).

Cada registro da partição avaliada precisa de um resultado de cada método, e um só. No
confirmatório, o método que repete o resultado de um (método, row_id), omite registros, ou traz
resultado de registros de fora da população sem declarar as outras partições entre as entradas,
é recusado antes de qualquer métrica; no exploratório só as contagens vão para as notas do
relatório, o registro sem resultado segue contando como abstenção e o último repetido prevalece.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import declara_outras_particoes

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sustemporal.contracts import FreezeManifest, RunResult
    from sustemporal.evaluation.metrics_leitura import Leitura

__all__ = ["Cobertura", "calcular_coberturas", "exigir_cobertura_completa", "notas_de_cobertura"]


@dataclass(frozen=True)
class Cobertura:
    """Contagens de um método (`ausentes`, `extras` e `duplicados`) e a execução que o produziu."""

    metodo: str
    ausentes: int
    extras: int
    duplicados: int
    run: RunResult


def calcular_coberturas(populacao: Iterable[str], leitura: Leitura) -> list[Cobertura]:
    """Cobertura de cada método lido, na ordem dele, contra o `row_id` da população."""
    esperados = set(populacao)
    coberturas = []
    for metodo, resultados in leitura.situacoes.items():
        obtidos = set(resultados)
        coberturas.append(
            Cobertura(
                metodo,
                len(esperados - obtidos),
                len(obtidos - esperados),
                leitura.duplicados.get(metodo, 0),
                leitura.execucoes[metodo],
            )
        )
    return coberturas


def exigir_cobertura_completa(coberturas: Iterable[Cobertura], manifesto: FreezeManifest) -> None:
    """Recusa o método com resultado repetido, sem resultado de algum registro ou com a mais.

    Resultado de registros de fora da população só passa se a execução traz, entre as entradas, a
    população de outra partição congelada (o baseline lê as que ajusta e avalia). O repetido vem
    antes da cobertura.

    Raises:
        PortaoRecusado: `execucao_com_resultado_duplicado metodo=... duplicados=...` ou
            `execucao_com_cobertura_incompleta metodo=... ausentes=... extras=...`, para o
            primeiro método, em ordem alfabética, que não cumpre.
    """
    for cobertura in sorted(coberturas, key=lambda c: c.metodo):
        if cobertura.duplicados:
            raise PortaoRecusado(
                f"execucao_com_resultado_duplicado metodo={cobertura.metodo} "
                f"duplicados={cobertura.duplicados}"
            )
        extras_declarados = declara_outras_particoes(manifesto, cobertura.run)
        if cobertura.ausentes or (cobertura.extras and not extras_declarados):
            raise PortaoRecusado(
                f"execucao_com_cobertura_incompleta metodo={cobertura.metodo} "
                f"ausentes={cobertura.ausentes} extras={cobertura.extras}"
            )


def notas_de_cobertura(coberturas: Iterable[Cobertura]) -> tuple[str, ...]:
    """Uma nota com as contagens de cada método, em ordem alfabética."""
    return tuple(
        f"cobertura_dos_resultados metodo={c.metodo} ausentes={c.ausentes} extras={c.extras} "
        f"duplicados={c.duplicados}"
        for c in sorted(coberturas, key=lambda c: c.metodo)
    )
