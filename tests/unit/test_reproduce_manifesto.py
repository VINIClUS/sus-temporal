"""Manifesto de aquisição como estava no congelamento (T14); SINTETICO.

A reprodução lê só o histórico até o instante do congelamento: o que foi coletado depois (artefato
novo, republicação, recoleta, ausência) fica fora da cópia, e a cópia é um manifesto válido.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto, ManifestoCorrompido
from sustemporal.contracts import FamiliaFonte, ResultadoTentativa
from sustemporal.reporting.reproduce_manifesto import (
    Recorte,
    manifesto_do_congelamento,
    observacoes_do_recorte,
)
from tests.fixtures.temporal_registro import instante, observar

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from pathlib import Path

    from sustemporal.contracts import ArtifactObservation, ArtifactVersion

    Evento = tuple[ArtifactObservation, ArtifactVersion | None]

PA = FamiliaFonte.SIA_PA
ANCORA = f"{NOME_MANIFESTO_AQUISICAO}.ancora"


def _origem(tmp_path: Path, eventos: Iterable[Evento]) -> Path:
    raiz = tmp_path / "origem"
    manifesto = Manifesto(raiz / NOME_MANIFESTO_AQUISICAO)
    for observacao, versao in eventos:
        manifesto.registrar(observacao, versao)
    return raiz


def _copiar(tmp_path: Path, eventos: Iterable[Evento], quando: datetime) -> tuple[Recorte, Path]:
    destino = tmp_path / "destino"
    recorte = manifesto_do_congelamento(_origem(tmp_path, eventos), destino, quando)
    return recorte, destino


def _lido(destino: Path) -> tuple[set[str], list[str]]:
    estado = Manifesto(destino / NOME_MANIFESTO_AQUISICAO).ler()
    return set(estado.versoes), [o.observation_id for o in estado.observacoes]


def _id(evento: Evento) -> str:
    assert evento[1] is not None
    return evento[1].artifact_id


def _obs(evento: Evento) -> str:
    return evento[0].observation_id


def test_a_copia_leva_so_o_observado_ate_o_instante(tmp_path: Path) -> None:
    a, b, c = (
        observar(PA, "202401", "a", 1),
        observar(PA, "202402", "b", 2),
        observar(PA, "202403", "c", 5),
    )
    recorte, destino = _copiar(tmp_path, [a, b, c], instante(3))
    assert recorte == Recorte(artefatos=1, observacoes=1)
    assert _lido(destino) == ({_id(a), _id(b)}, [_obs(a), _obs(b)])


def test_observacao_no_proprio_instante_do_congelamento_entra(tmp_path: Path) -> None:
    a, b = observar(PA, "202401", "a", 1), observar(PA, "202402", "b", 3)
    recorte, destino = _copiar(tmp_path, [a, b], instante(3))
    assert recorte == Recorte(artefatos=0, observacoes=0)
    assert _lido(destino) == ({_id(a), _id(b)}, [_obs(a), _obs(b)])


def test_recoleta_posterior_sai_e_a_versao_continua(tmp_path: Path) -> None:
    primeira, recoleta = observar(PA, "202401", "a", 1), observar(PA, "202401", "a", 5)
    assert _id(primeira) == _id(recoleta)
    recorte, destino = _copiar(tmp_path, [primeira, recoleta], instante(3))
    assert recorte == Recorte(artefatos=0, observacoes=1)
    assert _lido(destino) == ({_id(primeira)}, [_obs(primeira)])


def test_republicacao_posterior_com_outro_conteudo_nao_entra(tmp_path: Path) -> None:
    v1, v2 = observar(PA, "202401", "a", 1), observar(PA, "202401", "b", 5)
    assert _id(v1) != _id(v2)
    recorte, destino = _copiar(tmp_path, [v1, v2], instante(3))
    assert recorte == Recorte(artefatos=1, observacoes=1)
    assert _lido(destino) == ({_id(v1)}, [_obs(v1)])


def test_ausencia_posterior_sem_artefato_sai(tmp_path: Path) -> None:
    obtida = observar(PA, "202401", "a", 1)
    sumiu = observar(PA, "202401", "a", 5, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    recorte, destino = _copiar(tmp_path, [obtida, sumiu], instante(3))
    assert recorte == Recorte(artefatos=0, observacoes=1)
    assert _lido(destino) == ({_id(obtida)}, [_obs(obtida)])


def test_ausencia_anterior_ao_instante_continua_registrada(tmp_path: Path) -> None:
    sumiu = observar(PA, "202401", "a", 1, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    recorte, destino = _copiar(tmp_path, [sumiu], instante(3))
    assert recorte == Recorte(artefatos=0, observacoes=0)
    assert _lido(destino) == (set(), [_obs(sumiu)])


def test_instante_depois_de_tudo_copia_o_manifesto_byte_a_byte(tmp_path: Path) -> None:
    eventos = [observar(PA, "202401", "a", 1), observar(PA, "202402", "b", 2)]
    origem = _origem(tmp_path, eventos)
    destino = tmp_path / "destino"
    assert manifesto_do_congelamento(origem, destino, instante(9)) == Recorte(0, 0)
    for nome in (NOME_MANIFESTO_AQUISICAO, ANCORA):
        assert (destino / nome).read_bytes() == (origem / nome).read_bytes()


def test_o_recorte_e_o_prefixo_do_original_com_a_mesma_cadeia_e_a_ancora(tmp_path: Path) -> None:
    eventos = [observar(PA, "202401", "a", 1), observar(PA, "202402", "b", 2)]
    eventos.append(observar(PA, "202403", "c", 5))
    origem = _origem(tmp_path, eventos)
    destino = tmp_path / "destino"
    assert manifesto_do_congelamento(origem, destino, instante(3)) == Recorte(1, 1)
    linhas = (origem / NOME_MANIFESTO_AQUISICAO).read_text(encoding="utf-8").splitlines(True)
    assert (destino / NOME_MANIFESTO_AQUISICAO).read_text(encoding="utf-8") == "".join(linhas[:4])
    ancora = json.loads((destino / ANCORA).read_text(encoding="utf-8"))
    quarta = Manifesto(origem / NOME_MANIFESTO_AQUISICAO).ler().linhas[3]
    assert ancora == {"sequencia": 4, "sha256": quarta.sha256()}


def test_instantes_fora_de_ordem_mantem_a_cadeia_valida(tmp_path: Path) -> None:
    a, tarde, b = (
        observar(PA, "202401", "a", 1),
        observar(PA, "202402", "t", 9),
        observar(PA, "202403", "b", 2),
    )
    recorte, destino = _copiar(tmp_path, [a, tarde, b], instante(5))
    assert recorte == Recorte(artefatos=1, observacoes=1)
    assert _lido(destino) == ({_id(a), _id(b)}, [_obs(a), _obs(b)])


def test_observacao_mantida_de_versao_vista_primeiro_depois_do_instante_traz_a_versao(
    tmp_path: Path,
) -> None:
    tarde, cedo = observar(PA, "202401", "a", 9), observar(PA, "202401", "a", 2)
    recorte, destino = _copiar(tmp_path, [tarde, cedo], instante(5))
    assert recorte == Recorte(artefatos=0, observacoes=1)
    assert _lido(destino) == ({_id(cedo)}, [_obs(cedo)])


def test_instante_antes_de_tudo_gera_manifesto_vazio_e_legivel(tmp_path: Path) -> None:
    a = observar(PA, "202401", "a", 5)
    recorte, destino = _copiar(tmp_path, [a], instante(1))
    assert recorte == Recorte(artefatos=1, observacoes=1)
    assert _lido(destino) == (set(), [])
    assert Manifesto(destino / NOME_MANIFESTO_AQUISICAO).ler().linhas == ()


def test_origem_sem_manifesto_gera_manifesto_vazio(tmp_path: Path) -> None:
    destino = tmp_path / "destino"
    assert manifesto_do_congelamento(tmp_path / "nao_existe", destino, instante(3)) == Recorte(0, 0)
    assert _lido(destino) == (set(), [])


def test_manifesto_de_origem_corrompido_e_recusado(tmp_path: Path) -> None:
    origem = _origem(tmp_path, [observar(PA, "202401", "a", 1), observar(PA, "202402", "b", 2)])
    caminho = origem / NOME_MANIFESTO_AQUISICAO
    caminho.write_text(caminho.read_text(encoding="utf-8").replace("202402", "202403"))
    with pytest.raises(ManifestoCorrompido):
        manifesto_do_congelamento(origem, tmp_path / "destino", instante(9))


def test_a_origem_nao_e_alterada(tmp_path: Path) -> None:
    origem = _origem(tmp_path, [observar(PA, "202401", "a", 1), observar(PA, "202402", "b", 5)])
    antes = {n: (origem / n).read_bytes() for n in (NOME_MANIFESTO_AQUISICAO, ANCORA)}
    manifesto_do_congelamento(origem, tmp_path / "destino", instante(3))
    assert {n: (origem / n).read_bytes() for n in antes} == antes


@pytest.mark.parametrize(
    ("recorte", "esperado"),
    [
        (Recorte(0, 0), []),
        (
            Recorte(2, 3),
            [
                "artefatos_fora_do_congelamento_ignorados n=2",
                "observacoes_posteriores_ao_congelamento_ignoradas n=3",
            ],
        ),
        (Recorte(0, 4), ["observacoes_posteriores_ao_congelamento_ignoradas n=4"]),
        (Recorte(1, 0), ["artefatos_fora_do_congelamento_ignorados n=1"]),
    ],
)
def test_observacoes_do_recorte_contam_o_que_ficou_de_fora(
    recorte: Recorte, esperado: list[str]
) -> None:
    assert observacoes_do_recorte(recorte) == esperado
