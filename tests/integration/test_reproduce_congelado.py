"""Reprodução do que o congelamento resolveu, não do estado atual (T14); dados SINTETICO.

O `reproduce` lê o manifesto de aquisição como estava no congelamento: coleta nova, republicação
e ausência registradas depois dele não entram na reconstrução. Nada aqui é resultado empírico.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.fixtures.reproducao_fluxo import (
    Fluxo,
    adquirir_e_ingerir,
    coleta_depois_do_congelamento,
    congelar_e_avaliar,
    derivar,
    iniciar,
    reproduzir,
    validar_janelas,
)

from sustemporal.contracts.artifacts import ResultadoTentativa
from sustemporal.contracts.experiment import FreezeManifest
from sustemporal.errors import ExitCode

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def fluxo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fluxo]:
    with pytest.MonkeyPatch.context() as mp:
        estado = iniciar(tmp_path_factory.mktemp("congelado"), mp)
        adquirir_e_ingerir(estado)
        validar_janelas(estado, janelas=("cal", "teste"))
        derivar(estado)
        congelar_e_avaliar(estado)
        yield estado


def _congelado(fluxo: Fluxo) -> FreezeManifest:
    assert fluxo.freeze_id is not None
    caminho = fluxo.mundo.congelamentos / f"{fluxo.freeze_id}.json"
    return FreezeManifest.model_validate_json(caminho.read_text(encoding="utf-8"))


def test_reproduce_ignora_o_que_foi_coletado_depois_do_congelamento(fluxo: Fluxo) -> None:
    with coleta_depois_do_congelamento(fluxo) as coletadas:
        feita = reproduzir(fluxo, fluxo.configs["teste"], fluxo.mundo.raiz / "reproducao_depois")
        resultados = [o.resultado for o in coletadas]
        assert resultados == [ResultadoTentativa.OBTIDO] * 2 + [ResultadoTentativa.NAO_ENCONTRADO]
        assert all(o.observado_em > _congelado(fluxo).criado_em for o in coletadas)
    assert feita.codigo == ExitCode.OK
    assert feita.conteudo["resultado"] == "IGUAL"
    assert set(feita.situacoes.values()) == {"IGUAL"}
    assert "artefatos_fora_do_congelamento_ignorados n=2" in feita.conteudo["observacoes"]
    assert "observacoes_posteriores_ao_congelamento_ignoradas n=3" in feita.conteudo["observacoes"]
