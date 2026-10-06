"""Manifesto de aquisição como o `ingest` original o leu (T14); SINTETICO.

A reprodução copia o manifesto só até a posição que o `ingest` gravou em `manifesto_lido.json`
(linhas e hash da última): coleta, republicação, recoleta ou ausência registradas depois dela não
entram, qualquer que seja o instante da observação. A execução do `ingest` é a que produziu o
SIA-PA que o congelamento fixou; sem ela, ou com posições diferentes entre candidatas, a posição
não se sabe e a reprodução é inconclusiva, nunca um corte por instante.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import EstadoManifesto, Manifesto
from sustemporal.contracts import FamiliaFonte, ResultadoTentativa
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.errors import ConfigInvalida
from sustemporal.reporting.reproduce_manifesto import (
    Recorte,
    Resolucao,
    gravar_manifesto,
    observacoes_do_manifesto,
    resolver_manifesto,
)
from tests.fixtures.protocolo_dados import artefato
from tests.fixtures.protocolo_insumos import conjunto_sintetico
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from sustemporal.contracts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.artifacts import LinhaManifesto

    Evento = tuple[ArtifactObservation, ArtifactVersion | None]

PA = FamiliaFonte.SIA_PA
ANCORA = f"{NOME_MANIFESTO_AQUISICAO}.ancora"
LIDO = "manifesto_lido.json"
CONFIGURACAO_DO_INGEST = "configuracao_ingest.json"
CONFIGURACAO: dict[str, object] = {
    "uf": "SP",
    "corte_observacao": None,
    "familias_fontes": ["CNES_PF", "CNES_ST", "SIA_PA", "SIGTAP"],
    "catalogo_fontes_sha256": "a" * 64,
    "leiaute_sia_pa_sha256": "b" * 64,
}
SIA_PA = "sia_pa.v1"


def _origem(tmp_path: Path, eventos: Iterable[Evento]) -> Path:
    raiz = tmp_path / "origem"
    manifesto = Manifesto(raiz / NOME_MANIFESTO_AQUISICAO)
    for observacao, versao in eventos:
        manifesto.registrar(observacao, versao)
    return raiz


def _linhas(origem: Path) -> tuple[LinhaManifesto, ...]:
    return Manifesto(origem / NOME_MANIFESTO_AQUISICAO).ler().linhas


def _posicao(origem: Path, linhas: int) -> dict[str, object]:
    cabeca = EstadoManifesto(_linhas(origem)[:linhas]).cabeca_sha256
    return {"linhas": linhas, "cabeca_sha256": cabeca}


def _id(evento: Evento) -> str:
    assert evento[1] is not None
    return evento[1].artifact_id


def _conjunto(*artefatos: str, esquema: str = SIA_PA) -> DatasetRef:
    base = conjunto_sintetico(esquema, "v1")
    ids = tuple(sorted(artefatos))
    novo = calcular_dataset_id(esquema, base.hash_logico, ids)
    return base.model_copy(update={"artifact_ids": ids, "dataset_id": novo})


def _execucao(
    raiz: Path,
    nome: str,
    conjuntos: Iterable[DatasetRef],
    posicao: object = None,
    configuracao: object = None,
) -> Path:
    pasta = raiz / nome
    pasta.mkdir(parents=True)
    linhas = "".join(f"{conjunto.model_dump_json()}\n" for conjunto in conjuntos)
    (pasta / "datasets.jsonl").write_text(linhas, encoding="utf-8")
    if posicao is not None:
        (pasta / LIDO).write_text(json.dumps(posicao), encoding="utf-8")
    if configuracao is not None:
        (pasta / CONFIGURACAO_DO_INGEST).write_text(json.dumps(configuracao), encoding="utf-8")
    return pasta


def _tres(tmp_path: Path) -> tuple[Path, list[Evento]]:
    eventos = [
        observar(PA, "202401", "a", 1),
        observar(PA, "202402", "b", 2),
        observar(PA, "202403", "c", 3),
    ]
    return _origem(tmp_path, eventos), eventos


def _resolver(
    tmp_path: Path,
    origem: Path,
    *congelados: DatasetRef,
    configuracao: dict[str, object] | None = None,
) -> Resolucao:
    return resolver_manifesto(tmp_path / "ingest", origem, congelados, configuracao)


def test_a_copia_leva_so_o_que_o_ingest_leu_e_o_resto_fica_de_fora(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"
    assert resolucao.linhas == _linhas(origem)[:4]
    assert resolucao.recorte == Recorte(artefatos=1, observacoes=1)


def test_posicao_no_fim_do_manifesto_nao_deixa_nada_de_fora(tmp_path: Path) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b), _id(c))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 6))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.linhas == _linhas(origem)
    assert resolucao.recorte == Recorte(artefatos=0, observacoes=0)


def test_o_que_o_ingest_nao_leu_sai_mesmo_com_o_instante_anterior_ao_que_ele_leu(
    tmp_path: Path,
) -> None:
    a, b = observar(PA, "202401", "a", 5), observar(PA, "202402", "b", 6)
    antes_no_tempo = observar(PA, "202403", "c", 1)
    origem = _origem(tmp_path, [a, b, antes_no_tempo])
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.recorte == Recorte(artefatos=1, observacoes=1)
    mantidas = [linha.observacao for linha in resolucao.linhas if linha.observacao]
    assert [o.observation_id for o in mantidas] == [a[0].observation_id, b[0].observation_id]


def test_recoleta_depois_da_posicao_sai_e_a_versao_continua(tmp_path: Path) -> None:
    primeira, recoleta = observar(PA, "202401", "a", 1), observar(PA, "202401", "a", 5)
    assert _id(primeira) == _id(recoleta)
    origem = _origem(tmp_path, [primeira, recoleta])
    uniao = _conjunto(_id(primeira))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.recorte == Recorte(artefatos=0, observacoes=1)
    assert len(resolucao.linhas) == 2


def test_republicacao_depois_da_posicao_com_outro_conteudo_nao_entra(tmp_path: Path) -> None:
    v1, v2 = observar(PA, "202401", "a", 1), observar(PA, "202401", "b", 5)
    assert _id(v1) != _id(v2)
    origem = _origem(tmp_path, [v1, v2])
    uniao = _conjunto(_id(v1))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.recorte == Recorte(artefatos=1, observacoes=1)
    assert {linha.versao.artifact_id for linha in resolucao.linhas if linha.versao} == {_id(v1)}


def test_ausencia_depois_da_posicao_sai(tmp_path: Path) -> None:
    obtida = observar(PA, "202401", "a", 1)
    sumiu = observar(PA, "202401", "a", 5, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    origem = _origem(tmp_path, [obtida, sumiu])
    uniao = _conjunto(_id(obtida))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.recorte == Recorte(artefatos=0, observacoes=1)


def test_ausencia_registrada_antes_da_posicao_continua_no_manifesto_copiado(tmp_path: Path) -> None:
    sumiu = observar(PA, "202401", "a", 1, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    obtida = observar(PA, "202402", "b", 2)
    origem = _origem(tmp_path, [sumiu, obtida])
    uniao = _conjunto(_id(obtida))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 3))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.recorte == Recorte(0, 0)
    assert resolucao.linhas[0].observacao is not None
    assert resolucao.linhas[0].observacao.resultado is ResultadoTentativa.NAO_ENCONTRADO


def test_ingest_que_leu_o_manifesto_vazio_copia_um_manifesto_vazio(tmp_path: Path) -> None:
    a = observar(PA, "202401", "a", 1)
    origem = _origem(tmp_path, [a])
    _execucao(tmp_path / "ingest", "execucao_1", [_conjunto(_id(a))], _posicao(origem, 0))
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a)))
    assert resolucao.motivo == ""
    assert resolucao.linhas == ()
    assert resolucao.recorte == Recorte(artefatos=1, observacoes=1)


def test_mais_de_uma_execucao_com_a_mesma_posicao_nao_e_ambiguidade(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    for nome in ("execucao_1", "execucao_3", "execucao_2"):
        _execucao(tmp_path / "ingest", nome, [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_3"
    assert len(resolucao.linhas) == 4


def test_execucoes_com_posicoes_diferentes_deixam_a_posicao_ambigua(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    _execucao(tmp_path / "ingest", "execucao_2", [uniao], _posicao(origem, 5))
    _execucao(tmp_path / "ingest", "execucao_3", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == "ingest_original_ambiguo candidatas=3 posicoes=2"
    assert (resolucao.execucao, resolucao.linhas) == ("", ())


def test_a_mesma_quantidade_de_linhas_com_outra_cabeca_tambem_e_ambiguidade(
    tmp_path: Path,
) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    _execucao(
        tmp_path / "ingest",
        "execucao_2",
        [uniao],
        {**_posicao(origem, 4), "cabeca_sha256": "0" * 64},
    )
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == "ingest_original_ambiguo candidatas=2 posicoes=2"


def test_execucao_de_outro_conjunto_do_sia_pa_nao_e_candidata(tmp_path: Path) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    _execucao(tmp_path / "ingest", "execucao_1", [_conjunto(_id(a), _id(b))], _posicao(origem, 4))
    _execucao(
        tmp_path / "ingest", "execucao_2", [_conjunto(_id(a), _id(b), _id(c))], _posicao(origem, 6)
    )
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a), _id(b)))
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"
    assert len(resolucao.linhas) == 4


def test_o_conjunto_congelado_so_precisa_da_mesma_uniao_de_artefatos(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    por_arquivo = [_conjunto(_id(a)), _conjunto(_id(b))]
    _execucao(tmp_path / "ingest", "execucao_1", por_arquivo, _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a), _id(b)))
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"


def test_a_uniao_congelada_em_mais_de_um_conjunto_vale_pelo_todo(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    _execucao(tmp_path / "ingest", "execucao_1", [_conjunto(_id(a), _id(b))], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a)), _conjunto(_id(b)))
    assert resolucao.motivo == ""


def test_conjunto_do_ingest_que_nao_e_do_sia_pa_nao_entra_na_comparacao(tmp_path: Path) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    cnes = _conjunto(_id(c), esquema="cnes_estab_cbo.v1")
    conjuntos = [_conjunto(_id(a), _id(b)), cnes]
    _execucao(tmp_path / "ingest", "execucao_1", conjuntos, _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a), _id(b)))
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"


def test_conjunto_congelado_que_nao_e_do_sia_pa_nao_entra_na_comparacao(tmp_path: Path) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    _execucao(tmp_path / "ingest", "execucao_1", [_conjunto(_id(a), _id(b))], _posicao(origem, 4))
    rotulos = _conjunto(_id(c), esquema="sia_pa_rotulos.v1")
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a), _id(b)), rotulos)
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"


def test_sem_execucao_do_ingest_com_o_sia_pa_congelado_a_posicao_nao_se_sabe(
    tmp_path: Path,
) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    _execucao(tmp_path / "ingest", "execucao_1", [_conjunto(_id(a), _id(c))], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a), _id(b)))
    assert resolucao.motivo == "ingest_original_ausente execucoes=1"
    assert (resolucao.execucao, resolucao.linhas) == ("", ())


def test_sem_a_pasta_do_ingest_a_posicao_nao_se_sabe(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    resolucao = _resolver(tmp_path, origem, _conjunto(_id(a)))
    assert resolucao.motivo == "ingest_original_ausente execucoes=0"


def test_congelamento_sem_sia_pa_nao_aponta_execucao_nenhuma(tmp_path: Path) -> None:
    origem, _ = _tres(tmp_path)
    _execucao(tmp_path / "ingest", "execucao_1", [], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, _conjunto(artefato("x"), esquema="sia_pa_rotulos.v1"))
    assert resolucao.motivo == "ingest_original_ausente execucoes=1"


def test_pasta_do_ingest_sem_datasets_ou_fora_do_padrao_nao_e_candidata(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    (tmp_path / "ingest" / "execucao_0").mkdir(parents=True)
    (tmp_path / "ingest" / "execucao_9").mkdir()
    (tmp_path / "ingest" / "execucao_9" / "datasets.jsonl").write_text("{", encoding="utf-8")
    (tmp_path / "ingest" / "outra").mkdir()
    (tmp_path / "ingest" / "execucao_arquivo").write_text("x", encoding="utf-8")
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"


@pytest.mark.parametrize(
    "posicao",
    [
        None,
        "texto",
        [1, 2],
        {"linhas": 2},
        {"cabeca_sha256": None},
        {"linhas": "2", "cabeca_sha256": None},
        {"linhas": True, "cabeca_sha256": None},
        {"linhas": 2.0, "cabeca_sha256": None},
        {"linhas": -1, "cabeca_sha256": None},
        {"linhas": 2, "cabeca_sha256": 7},
    ],
)
def test_execucao_candidata_sem_posicao_legivel_deixa_a_posicao_desconhecida(
    tmp_path: Path, posicao: object
) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    _execucao(tmp_path / "ingest", "execucao_2", [uniao], posicao)
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == "ingest_original_sem_posicao execucao=execucao_2"
    assert (resolucao.execucao, resolucao.linhas) == ("", ())


def test_todas_as_candidatas_sem_posicao_aparecem_no_motivo_em_ordem(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_2", [uniao])
    _execucao(tmp_path / "ingest", "execucao_1", [uniao])
    _execucao(tmp_path / "ingest", "execucao_3", [uniao], _posicao(origem, 2))
    motivo = _resolver(tmp_path, origem, uniao).motivo
    assert motivo == "ingest_original_sem_posicao execucao=execucao_1,execucao_2"


def test_posicao_com_json_quebrado_tambem_e_sem_posicao(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    pasta = _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    (pasta / LIDO).write_text('{"linhas": ', encoding="utf-8")
    assert _resolver(tmp_path, origem, uniao).motivo == (
        "ingest_original_sem_posicao execucao=execucao_1"
    )


@pytest.mark.parametrize("lidas", [7, 9])
def test_posicao_alem_do_fim_do_manifesto_atual_nao_se_reproduz(tmp_path: Path, lidas: int) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    posicao = {"linhas": lidas, "cabeca_sha256": "0" * 64}
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], posicao)
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == f"manifesto_menor_que_o_lido_pelo_ingest linhas={lidas} atual=6"
    assert (resolucao.execucao, resolucao.linhas) == ("", ())


def test_cabeca_diferente_da_que_o_ingest_leu_nao_se_reproduz(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(
        tmp_path / "ingest",
        "execucao_1",
        [uniao],
        {**_posicao(origem, 2), "cabeca_sha256": "0" * 64},
    )
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == "manifesto_diferente_do_lido_pelo_ingest linhas=2"


def test_posicao_que_termina_numa_versao_sem_a_observacao_dela_nao_se_reproduz(
    tmp_path: Path,
) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    assert _linhas(origem)[2].versao is not None
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 3))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert resolucao.motivo == "posicao_do_ingest_no_meio_de_uma_transacao linhas=3"


def test_manifesto_atual_sem_arquivo_so_serve_ao_ingest_que_nao_leu_nada(tmp_path: Path) -> None:
    uniao = _conjunto(artefato("a"))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], {"linhas": 0, "cabeca_sha256": None})
    resolucao = resolver_manifesto(tmp_path / "ingest", tmp_path / "nao_existe", [uniao])
    assert (resolucao.motivo, resolucao.linhas) == ("", ())
    _execucao(tmp_path / "outro", "execucao_1", [uniao], {"linhas": 2, "cabeca_sha256": "0" * 64})
    outra = resolver_manifesto(tmp_path / "outro", tmp_path / "nao_existe", [uniao])
    assert outra.motivo == "manifesto_menor_que_o_lido_pelo_ingest linhas=2 atual=0"


def test_manifesto_atual_corrompido_deixa_a_reproducao_inconclusiva(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    caminho = origem / NOME_MANIFESTO_AQUISICAO
    caminho.write_text(caminho.read_text(encoding="utf-8").replace("202402", "202403"))
    assert _resolver(tmp_path, origem, uniao).motivo == "manifesto_corrompido"


def test_resolver_nao_altera_nada_da_origem_nem_do_ingest(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    pasta = _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    arquivos = [*origem.iterdir(), *pasta.iterdir()]
    antes = {arquivo: arquivo.read_bytes() for arquivo in arquivos}
    _resolver(tmp_path, origem, uniao)
    assert {arquivo: arquivo.read_bytes() for arquivo in arquivos} == antes


def _com_configuracao(tmp_path: Path, *nomes: str, **trocas: object) -> tuple[Path, DatasetRef]:
    """Ingest com a `CONFIGURACAO` gravada em cada execução de `nomes` e a origem de 3 arquivos."""
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    for nome in nomes:
        gravada = {**CONFIGURACAO, **trocas}
        _execucao(tmp_path / "ingest", nome, [uniao], _posicao(origem, 4), gravada)
    return origem, uniao


def test_ingest_gravado_com_a_configuracao_do_refeito_se_resolve(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1")
    resolucao = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO)
    assert resolucao.motivo == ""
    assert resolucao.execucao == "execucao_1"


@pytest.mark.parametrize(
    ("campo", "gravado"),
    [
        ("uf", "RJ"),
        ("corte_observacao", "2026-01-01T00:00:00+00:00"),
        ("familias_fontes", ["SIA_PA"]),
        ("catalogo_fontes_sha256", "c" * 64),
        ("leiaute_sia_pa_sha256", "d" * 64),
    ],
)
def test_ingest_gravado_com_outra_configuracao_nao_e_o_que_o_refeito_faria(
    tmp_path: Path, campo: str, gravado: object
) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1", **{campo: gravado})
    resolucao = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO)
    assert resolucao.motivo == f"ingest_original_com_configuracao_diferente campos={campo}"
    assert (resolucao.execucao, resolucao.linhas) == ("", ())


def test_campos_diferentes_saem_na_ordem_da_configuracao_do_refeito(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(
        tmp_path, "execucao_1", leiaute_sia_pa_sha256="d" * 64, uf="RJ"
    )
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_com_configuracao_diferente campos=uf,leiaute_sia_pa_sha256"


def test_campo_a_mais_na_configuracao_gravada_tambem_diferencia(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1", novo_campo="x")
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_com_configuracao_diferente campos=novo_campo"


def test_todas_as_candidatas_tem_de_ter_a_configuracao_do_refeito(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1")
    _execucao(
        tmp_path / "ingest",
        "execucao_2",
        [uniao],
        _posicao(origem, 4),
        {**CONFIGURACAO, "uf": "RJ"},
    )
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_com_configuracao_diferente campos=uf"


@pytest.mark.parametrize("gravada", ["{", "[1, 2]", '"texto"', "null"])
def test_configuracao_gravada_ilegivel_deixa_a_execucao_sem_configuracao(
    tmp_path: Path, gravada: str
) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1")
    (tmp_path / "ingest" / "execucao_1" / CONFIGURACAO_DO_INGEST).write_text(gravada)
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_sem_configuracao execucao=execucao_1"


def test_execucao_sem_arquivo_de_configuracao_e_sem_configuracao(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_2", [uniao], _posicao(origem, 4))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_sem_configuracao execucao=execucao_1,execucao_2"


def test_sem_a_configuracao_do_refeito_a_do_ingest_nao_e_conferida(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1", uf="RJ")
    assert _resolver(tmp_path, origem, uniao).motivo == ""


def test_posicao_desconhecida_vem_antes_da_configuracao(tmp_path: Path) -> None:
    origem, uniao = _com_configuracao(tmp_path, "execucao_1")
    posicao = {**_posicao(origem, 4), "linhas": 5}
    _execucao(tmp_path / "ingest", "execucao_2", [uniao], posicao, {**CONFIGURACAO, "uf": "RJ"})
    motivo = _resolver(tmp_path, origem, uniao, configuracao=CONFIGURACAO).motivo
    assert motivo == "ingest_original_ambiguo candidatas=2 posicoes=2"


def test_a_copia_gravada_e_o_prefixo_do_original_com_a_mesma_cadeia_e_a_ancora(
    tmp_path: Path,
) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    destino = tmp_path / "destino"
    gravar_manifesto(origem, destino, resolucao)
    original = (origem / NOME_MANIFESTO_AQUISICAO).read_text(encoding="utf-8").splitlines(True)
    assert (destino / NOME_MANIFESTO_AQUISICAO).read_text(encoding="utf-8") == "".join(original[:4])
    ancora = json.loads((destino / ANCORA).read_text(encoding="utf-8"))
    assert ancora == {"sequencia": 4, "sha256": _linhas(origem)[3].sha256()}
    estado = Manifesto(destino / NOME_MANIFESTO_AQUISICAO).ler()
    assert estado.linhas == _linhas(origem)[:4]
    assert set(estado.versoes) == {_id(a), _id(b)}


def test_posicao_no_fim_copia_o_manifesto_byte_a_byte(tmp_path: Path) -> None:
    origem, (a, b, c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b), _id(c))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 6))
    destino = tmp_path / "destino"
    gravar_manifesto(origem, destino, _resolver(tmp_path, origem, uniao))
    for nome in (NOME_MANIFESTO_AQUISICAO, ANCORA):
        assert (destino / nome).read_bytes() == (origem / nome).read_bytes()


def test_copia_vazia_e_um_manifesto_legivel_com_a_ancora_zerada(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 0))
    destino = tmp_path / "destino"
    gravar_manifesto(origem, destino, _resolver(tmp_path, origem, uniao))
    assert Manifesto(destino / NOME_MANIFESTO_AQUISICAO).ler().linhas == ()
    assert json.loads((destino / ANCORA).read_text(encoding="utf-8")) == {
        "sequencia": 0,
        "sha256": None,
    }


def test_a_copia_nunca_e_gravada_sobre_o_manifesto_de_origem(tmp_path: Path) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    antes = {n: (origem / n).read_bytes() for n in (NOME_MANIFESTO_AQUISICAO, ANCORA)}
    with pytest.raises(ConfigInvalida, match=r"^manifesto_do_ingest_sobre_a_origem raiz="):
        gravar_manifesto(origem, origem, resolucao)
    assert {n: (origem / n).read_bytes() for n in antes} == antes


def test_a_copia_recusa_o_mesmo_diretorio_escrito_de_outro_modo(tmp_path: Path) -> None:
    origem, (a, _b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a))
    _execucao(tmp_path / "ingest", "execucao_1", [uniao], _posicao(origem, 2))
    resolucao = _resolver(tmp_path, origem, uniao)
    with pytest.raises(ConfigInvalida, match="manifesto_do_ingest_sobre_a_origem"):
        gravar_manifesto(origem, origem / "volta" / "..", resolucao)


def test_resolucao_sem_posicao_nao_grava_manifesto_nenhum(tmp_path: Path) -> None:
    origem, _ = _tres(tmp_path)
    resolucao = Resolucao(motivo="ingest_original_ausente execucoes=0")
    with pytest.raises(ConfigInvalida, match=r"^manifesto_do_ingest_sem_posicao"):
        gravar_manifesto(origem, tmp_path / "destino", resolucao)
    assert not (tmp_path / "destino").exists()


def test_observacoes_dizem_a_execucao_e_a_posicao_usadas_e_o_que_ficou_de_fora(
    tmp_path: Path,
) -> None:
    origem, (a, b, _c) = _tres(tmp_path)
    uniao = _conjunto(_id(a), _id(b))
    _execucao(tmp_path / "ingest", "execucao_7", [uniao], _posicao(origem, 4))
    resolucao = _resolver(tmp_path, origem, uniao)
    assert observacoes_do_manifesto(resolucao) == [
        "manifesto_do_ingest execucao=execucao_7 linhas=4",
        "artefatos_depois_do_ingest_ignorados n=1",
        "observacoes_depois_do_ingest_ignoradas n=1",
    ]


@pytest.mark.parametrize(
    ("recorte", "esperado"),
    [
        (Recorte(0, 0), []),
        (
            Recorte(2, 3),
            [
                "artefatos_depois_do_ingest_ignorados n=2",
                "observacoes_depois_do_ingest_ignoradas n=3",
            ],
        ),
        (Recorte(0, 4), ["observacoes_depois_do_ingest_ignoradas n=4"]),
        (Recorte(1, 0), ["artefatos_depois_do_ingest_ignorados n=1"]),
    ],
)
def test_so_o_que_ficou_de_fora_gera_observacao_alem_da_posicao(
    tmp_path: Path, recorte: Recorte, esperado: list[str]
) -> None:
    origem, _ = _tres(tmp_path)
    resolucao = Resolucao(execucao="execucao_1", linhas=_linhas(origem)[:2], recorte=recorte)
    primeira, *demais = observacoes_do_manifesto(resolucao)
    assert primeira == "manifesto_do_ingest execucao=execucao_1 linhas=2"
    assert demais == esperado


def test_resolucao_sem_posicao_nao_tem_observacao_de_manifesto() -> None:
    assert observacoes_do_manifesto(Resolucao(motivo="ingest_original_ausente execucoes=0")) == []
