"""Etapas do fluxo pequeno da reprodução: janelas do ingest e partições do protocolo (T14).

Os originais são sintéticos, vêm de um FTP local pelo `acquire` e passam pelo `ingest` real;
nada aqui é resultado empírico. A propriedade central: o `validate --ingest` sobre a janela de
uma partição lê a mesma população que o split formou (mesmo hash lógico).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
import pytest
from tests.fixtures.reproducao_fluxo import (
    Fluxo,
    adquirir_e_ingerir,
    artefatos_do_sia_pa,
    derivar,
    iniciar,
    validar_janelas,
    yaml_em_memoria,
)

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import EstadoExecucao, Particao
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.evaluation.split import SCHEMA_ENTRADA
from sustemporal.execucoes import ler_execucao, raiz_execucoes
from sustemporal.reporting.reproduce_etapas import (
    competencias_da_janela,
    competencias_da_particao,
    derivar_protocolo,
    estados_do_ingest,
    janela_do_ingest,
    janela_dos_artefatos,
    validar_janela,
)
from sustemporal.rules.ingest import ler_datasets

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sustemporal.contracts.experiment import SplitManifest

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module", autouse=True)
def _catalogos_em_memoria() -> Iterator[None]:
    with yaml_em_memoria():
        yield


@pytest.fixture(scope="module")
def ingerido(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Fluxo]:
    with pytest.MonkeyPatch.context() as mp:
        fluxo = iniciar(tmp_path_factory.mktemp("etapas"), mp)
        adquirir_e_ingerir(fluxo)
        yield fluxo


@pytest.fixture(scope="module")
def derivado(ingerido: Fluxo) -> Fluxo:
    validar_janelas(ingerido, janelas=("cal",))
    derivar(ingerido)
    return ingerido


def _sia_pa(pasta: Path) -> list[DatasetRef]:
    return [ref for ref in ler_datasets(pasta) if ref.schema_id == SCHEMA_ENTRADA]


def _auxiliares(pasta: Path) -> list[DatasetRef]:
    return [ref for ref in ler_datasets(pasta) if ref.schema_id != SCHEMA_ENTRADA]


def _janela(fluxo: Fluxo, destino: Path, competencias: tuple[str, ...]) -> Path:
    assert fluxo.ingest is not None
    return janela_do_ingest(fluxo.config("teste"), fluxo.ingest, destino, competencias)


def test_mundo_com_meses_faltantes_ingere_o_que_existe(ingerido: Fluxo) -> None:
    assert ingerido.codigos == {"acquire_primaria": 0, "acquire_auxiliar": 5, "ingest": 0}
    assert ingerido.ingest is not None
    assert len(_sia_pa(ingerido.ingest)) == 4


def test_janela_traz_so_o_sia_pa_dos_arquivos_da_competencia(ingerido: Fluxo, tmp_path: Path):
    pasta = _janela(ingerido, tmp_path / "cal", ("202301",))
    (sia_pa,) = _sia_pa(pasta)
    assert competencias_da_particao(sia_pa) == ("202301",)


def test_janela_deixa_todos_os_auxiliares_como_estao(ingerido: Fluxo, tmp_path: Path) -> None:
    assert ingerido.ingest is not None
    pasta = _janela(ingerido, tmp_path / "cal", ("202301",))
    assert _auxiliares(pasta) == _auxiliares(ingerido.ingest)
    assert _auxiliares(pasta)


def test_janela_de_duas_competencias_traz_os_dois_arquivos(ingerido: Fluxo, tmp_path: Path) -> None:
    pasta = _janela(ingerido, tmp_path / "dev", ("201801", "201803"))
    competencias = sorted(c for ref in _sia_pa(pasta) for c in competencias_da_particao(ref))
    assert competencias == ["201801", "201803"]


def test_janela_sem_arquivo_na_competencia_nao_inventa_producao(ingerido: Fluxo, tmp_path: Path):
    pasta = _janela(ingerido, tmp_path / "vazia", ("202412",))
    assert _sia_pa(pasta) == []
    assert _auxiliares(pasta)


def _dataset_misto(fluxo: Fluxo) -> tuple[DatasetRef, tuple[str, ...]]:
    """Conjunto com os arquivos de duas competências e a competência de um deles."""
    assert fluxo.ingest is not None
    a, b = _sia_pa(fluxo.ingest)[:2]
    artefatos = tuple(sorted({*a.artifact_ids, *b.artifact_ids}))
    misto = DatasetRef(
        dataset_id=calcular_dataset_id(a.schema_id, a.hash_logico, artefatos),
        schema_id=a.schema_id,
        caminho=a.caminho,
        hash_logico=a.hash_logico,
        linhas=a.linhas,
        artifact_ids=artefatos,
        origem_dados=a.origem_dados,
        produzido_por="teste",
    )
    return misto, competencias_da_particao(a)


def test_janela_recusa_conjunto_com_arquivos_de_janelas_diferentes(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    falsa = tmp_path / "ingest_misto"
    falsa.mkdir()
    misto, pedida = _dataset_misto(ingerido)
    (falsa / "datasets.jsonl").write_text(misto.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="janela_com_dataset_misto"):
        janela_do_ingest(ingerido.config("teste"), falsa, tmp_path / "j", pedida)


def test_janela_recusa_artefato_fora_do_manifesto(ingerido: Fluxo, tmp_path: Path) -> None:
    assert ingerido.ingest is not None
    (modelo, *_) = _sia_pa(ingerido.ingest)
    artefato = "art_" + "0" * 64
    ref = modelo.model_copy(
        update={
            "artifact_ids": (artefato,),
            "dataset_id": calcular_dataset_id(modelo.schema_id, modelo.hash_logico, (artefato,)),
        }
    )
    falsa = tmp_path / "ingest_orfao"
    falsa.mkdir()
    (falsa / "datasets.jsonl").write_text(ref.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="janela_artefato_fora_do_manifesto"):
        janela_do_ingest(ingerido.config("teste"), falsa, tmp_path / "j", ("202301",))


def test_derivar_forma_tres_particoes_de_quatro_linhas(derivado: Fluxo) -> None:
    split = derivado.split
    assert split is not None
    assert split.linhas_por_particao == {
        Particao.DESENVOLVIMENTO: 4,
        Particao.CALIBRACAO: 4,
        Particao.TESTE: 4,
    }
    assert split.exclusoes == {}


def test_cada_particao_traz_as_competencias_da_sua_janela(derivado: Fluxo) -> None:
    particoes = (derivado.split.particoes if derivado.split else None) or {}
    assert {p: competencias_da_particao(ref) for p, ref in particoes.items()} == {
        Particao.DESENVOLVIMENTO: ("201801", "201803"),
        Particao.CALIBRACAO: ("202301",),
        Particao.TESTE: ("202402",),
    }


def test_validate_sobre_a_janela_le_a_populacao_da_particao(derivado: Fluxo) -> None:
    assert derivado.split is not None
    esperado = derivado.split.hash_por_particao[Particao.CALIBRACAO]
    linhas = derivado.split.linhas_por_particao[Particao.CALIBRACAO]
    runs = [run for (janela, _), run in derivado.execucoes.items() if janela == "cal"]
    assert len(runs) == 3
    for run in runs:
        assert run.entradas[0].hash_logico == esperado
        assert run.entradas[0].linhas == linhas


def test_rotulos_da_particao_seguem_o_codebook_do_pa_indica(derivado: Fluxo) -> None:
    rotulos = (derivado.split.rotulos_por_particao if derivado.split else None) or {}
    tabela = pq.read_table(rotulos[Particao.CALIBRACAO].caminho, columns=["rotulo"])
    contagem = Counter(tabela.column("rotulo").to_pylist())
    assert contagem == {"NAO_APROVADO": 2, "APROVADO_TOTAL": 2}


def test_derivar_protocolo_exige_a_coorte_na_config(derivado: Fluxo, tmp_path: Path) -> None:
    assert derivado.ingest is not None
    sem_coorte = derivado.config("teste").model_copy(update={"coorte": None})
    spec = derivado.split.spec if derivado.split else None
    assert spec is not None
    with pytest.raises(ConfigInvalida, match="derivar_protocolo_exige_coorte"):
        derivar_protocolo(sem_coorte, derivado.ingest, tmp_path / "split", spec=spec)


def test_derivar_protocolo_recusa_ingest_sem_sia_pa(derivado: Fluxo, tmp_path: Path) -> None:
    vazio = tmp_path / "ingest_vazio"
    vazio.mkdir()
    (vazio / "datasets.jsonl").write_text("", encoding="utf-8")
    spec = derivado.split.spec if derivado.split else None
    assert spec is not None
    with pytest.raises(ConfigInvalida, match="ingest_sem_producao"):
        derivar_protocolo(derivado.config("teste"), vazio, tmp_path / "split", spec=spec)


def test_validar_janela_refaz_cada_metodo_com_a_politica_pedida(derivado: Fluxo) -> None:
    config = derivado.config("teste_cohort")
    janela = _janela(derivado, derivado.mundo.saidas / "janelas" / "teste_politicas", ("202401",))
    pedidas = {MetodoId.M_TEMP: "M_TEMP_PADRAO", MetodoId.B_ATEND: "B_ATEND", MetodoId.B_PROC: None}
    execucoes = validar_janela(config, janela, pedidas)
    assert {metodo: run.politica_id for metodo, run in execucoes.items()} == {
        MetodoId.M_TEMP: "M_TEMP_PADRAO",
        MetodoId.B_ATEND: "B_ATEND",
        MetodoId.B_PROC: "b_proc_exploratoria",
    }
    assert all(run.estado is EstadoExecucao.CONCLUIDA for run in execucoes.values())
    for run in execucoes.values():
        assert ler_execucao(raiz_execucoes(config), run.run_id) == run


def test_validar_janela_so_refaz_os_metodos_pedidos(derivado: Fluxo) -> None:
    janela = _janela(derivado, derivado.mundo.saidas / "janelas" / "teste_um", ("202401",))
    execucoes = validar_janela(derivado.config("teste"), janela, {MetodoId.B_PROC: None})
    assert set(execucoes) == {MetodoId.B_PROC}


def test_estados_do_ingest_trazem_o_estado_de_cada_artefato(ingerido: Fluxo) -> None:
    assert ingerido.ingest is not None
    estados = estados_do_ingest(ingerido.ingest)
    assert Counter(estados.values()) == {"NORMALIZADO": 16}
    sia_pa = {a for ref in _sia_pa(ingerido.ingest) for a in ref.artifact_ids}
    assert sia_pa <= set(estados)


def test_estados_do_ingest_recusa_pasta_sem_resultados(tmp_path: Path) -> None:
    with pytest.raises(FalhaOperacionalErro, match=r"^ingest_ilegivel caminho="):
        estados_do_ingest(tmp_path)


@pytest.mark.parametrize("linha", ["{nao e json", '{"artifact_id": "art_x"}', "[1, 2]"])
def test_estados_do_ingest_recusa_linha_fora_do_formato(tmp_path: Path, linha: str) -> None:
    (tmp_path / "resultados.jsonl").write_text(linha + "\n", encoding="utf-8")
    with pytest.raises(FalhaOperacionalErro, match=r"^ingest_ilegivel caminho="):
        estados_do_ingest(tmp_path)


def test_estados_do_ingest_ignora_linha_em_branco(tmp_path: Path) -> None:
    conteudo = '{"artifact_id": "art_x", "estado": "ARQUIVOAUSENTE"}\n\n'
    (tmp_path / "resultados.jsonl").write_text(conteudo, encoding="utf-8")
    assert estados_do_ingest(tmp_path) == {"art_x": "ARQUIVOAUSENTE"}


def test_derivar_protocolo_recusa_ingest_com_origens_diferentes(
    derivado: Fluxo, tmp_path: Path
) -> None:
    assert derivado.ingest is not None
    refs = ler_datasets(derivado.ingest)
    primeiro = next(i for i, ref in enumerate(refs) if ref.schema_id == SCHEMA_ENTRADA)
    refs[primeiro] = refs[primeiro].model_copy(update={"origem_dados": OrigemDados.REAL})
    misturado = tmp_path / "ingest_misturado"
    misturado.mkdir()
    linhas = "".join(f"{ref.model_dump_json()}\n" for ref in refs)
    (misturado / "datasets.jsonl").write_text(linhas, encoding="utf-8")
    spec = derivado.split.spec if derivado.split else None
    assert spec is not None
    with pytest.raises(ConfigInvalida, match=r"^ingest_com_origens_diferentes origens="):
        derivar_protocolo(derivado.config("teste"), misturado, tmp_path / "split", spec=spec)


def _derivar(fluxo: Fluxo, destino: Path, inspecionados: tuple[str, ...] = ()) -> SplitManifest:
    assert fluxo.ingest is not None
    assert fluxo.split is not None
    config = fluxo.config("teste")
    spec = fluxo.split.spec
    return derivar_protocolo(
        config, fluxo.ingest, destino, spec=spec, inspecionados=inspecionados
    ).split


def test_derivar_protocolo_grava_os_artefatos_inspecionados_no_split(
    derivado: Fluxo, tmp_path: Path
) -> None:
    inspecionados = artefatos_do_sia_pa(derivado, "dev")
    assert len(inspecionados) == 2
    com = _derivar(derivado, tmp_path / "com", inspecionados)
    sem = _derivar(derivado, tmp_path / "sem")
    assert com.artefatos_inspecionados == inspecionados
    assert sem.artefatos_inspecionados == ()
    assert com.split_id != sem.split_id
    assert com.hash_por_particao == sem.hash_por_particao


def test_derivar_protocolo_recusa_inspecionado_que_cairia_no_teste(
    derivado: Fluxo, tmp_path: Path
) -> None:
    do_teste = artefatos_do_sia_pa(derivado, "teste")
    assert len(do_teste) == 1
    with pytest.raises(ValueError, match="teste_contem_artefato_inspecionado"):
        _derivar(derivado, tmp_path / "teste", do_teste)


def test_derivar_protocolo_recusa_inspecionado_sem_fonte_no_manifesto(
    derivado: Fluxo, tmp_path: Path
) -> None:
    fora = "art_" + "0" * 64
    with pytest.raises(
        ValueError, match=r"^split_sem_fonte_para_artefato inspecionados=1 primeiro="
    ):
        _derivar(derivado, tmp_path / "fora", (fora,))


def test_janela_dos_artefatos_traz_so_o_sia_pa_dos_artefatos_pedidos(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    assert ingerido.ingest is not None
    (cal,) = artefatos_do_sia_pa(ingerido, "cal")
    pasta = janela_dos_artefatos(ingerido.ingest, tmp_path / "cal", [cal])
    (sia_pa,) = _sia_pa(pasta)
    assert sia_pa.artifact_ids == (cal,)


def test_janela_dos_artefatos_traz_todos_os_arquivos_pedidos(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    assert ingerido.ingest is not None
    dev = artefatos_do_sia_pa(ingerido, "dev")
    assert len(dev) == 2
    pasta = janela_dos_artefatos(ingerido.ingest, tmp_path / "dev", dev)
    assert sorted(a for ref in _sia_pa(pasta) for a in ref.artifact_ids) == list(dev)


def test_janela_dos_artefatos_deixa_todos_os_auxiliares_como_estao(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    assert ingerido.ingest is not None
    (cal,) = artefatos_do_sia_pa(ingerido, "cal")
    pasta = janela_dos_artefatos(ingerido.ingest, tmp_path / "cal", [cal])
    assert _auxiliares(pasta) == _auxiliares(ingerido.ingest)
    assert _auxiliares(pasta)


def test_janela_dos_artefatos_sem_artefatos_nao_inventa_producao(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    assert ingerido.ingest is not None
    pasta = janela_dos_artefatos(ingerido.ingest, tmp_path / "vazia", [])
    assert _sia_pa(pasta) == []
    assert _auxiliares(pasta)


def test_janela_dos_artefatos_traz_o_arquivo_cuja_competencia_difere_da_das_linhas(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    assert ingerido.ingest is not None
    (teste,) = artefatos_do_sia_pa(ingerido, "teste")
    pasta = janela_dos_artefatos(ingerido.ingest, tmp_path / "teste", [teste])
    (sia_pa,) = _sia_pa(pasta)
    assert sia_pa.artifact_ids == (teste,)
    assert competencias_da_particao(sia_pa) == ("202402",)


def test_janela_dos_artefatos_recusa_conjunto_com_artefatos_de_dentro_e_de_fora(
    ingerido: Fluxo, tmp_path: Path
) -> None:
    falsa = tmp_path / "ingest_misto"
    falsa.mkdir()
    misto, _ = _dataset_misto(ingerido)
    (falsa / "datasets.jsonl").write_text(misto.model_dump_json() + "\n", encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="janela_com_dataset_misto"):
        janela_dos_artefatos(falsa, tmp_path / "j", [misto.artifact_ids[0]])


def test_competencias_da_janela_juntam_as_do_arquivo_e_as_das_linhas(derivado: Fluxo) -> None:
    particoes = (derivado.split.particoes if derivado.split else None) or {}
    config = derivado.config("teste")
    assert {p: competencias_da_janela(config, ref) for p, ref in particoes.items()} == {
        Particao.DESENVOLVIMENTO: ("201801", "201803"),
        Particao.CALIBRACAO: ("202301",),
        Particao.TESTE: ("202401", "202402"),
    }


def test_competencias_da_janela_recusa_artefato_fora_do_manifesto(derivado: Fluxo) -> None:
    particoes = (derivado.split.particoes if derivado.split else None) or {}
    orfa = particoes[Particao.CALIBRACAO].model_copy(update={"artifact_ids": ("art_" + "0" * 64,)})
    with pytest.raises(ConfigInvalida, match="janela_artefato_fora_do_manifesto"):
        competencias_da_janela(derivado.config("teste"), orfa)
