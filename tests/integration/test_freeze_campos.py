"""Todo campo do FreezeManifest é conferido ou declarado informativo, com o motivo (T11).

Cenário SINTETICO rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Um campo novo no manifesto sem classificação, ou classificado como conferido sem cenário de
divergência, derruba os testes daqui.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO
from tests.fixtures.protocolo_confirmatorio import (
    CATALOGO_SIA_PA,
    MUTACOES_DO_AMBIENTE,
    OUTRO_SHA,
    Confirmatorio,
    montar_confirmatorio,
    sia_pa_desconhecido,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.experiment import Ambiente, CodeVersion, FeatureSpec, FreezeManifest
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import (
    CAMPOS_DO_MANIFESTO,
    SUBCAMPOS_INFORMATIVOS,
    ambiente_divergente,
    campos_sem_classificacao,
    verificar_congelamento_completo,
)
from sustemporal.rules.catalog import carregar_regras
from sustemporal.temporal.politicas import carregar_politica

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import RunResult
    from sustemporal.evaluation.freeze_conferencia import EstadoAtual

    Resultado = tuple[FreezeManifest, EstadoAtual]
    Modificador = Callable[[FreezeManifest, EstadoAtual], Resultado]

OUTRO_CODIGO = CODIGO_LIMPO.model_copy(update={"commit": "b" * 40})
M_TEMP = 0
MODELOS_DOS_SUBCAMPOS = {"codigo": CodeVersion, "ambiente": Ambiente}
AMBIENTE_BASE = Ambiente(
    python="3.12.3", plataforma="Linux-6.1", pacotes={"duckdb": "1.0.0"}, uv_lock_sha256="a" * 64
)
README = Path(__file__).resolve().parents[2] / "experiments" / "frozen" / "README.md"


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def catalogo(tmp_path: Path) -> Path:
    copia = tmp_path / "catalogos" / CATALOGO_SIA_PA.name
    copia.parent.mkdir()
    shutil.copyfile(CATALOGO_SIA_PA, copia)
    return copia


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario, catalogo: Path) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario, catalogo=catalogo)


def test_todo_campo_do_manifesto_esta_classificado() -> None:
    assert campos_sem_classificacao(FreezeManifest.model_fields) == set()
    assert set(CAMPOS_DO_MANIFESTO) == set(FreezeManifest.model_fields)


def test_campo_novo_no_manifesto_sem_classificacao_e_acusado() -> None:
    assert campos_sem_classificacao([*FreezeManifest.model_fields, "campo_novo"]) == {"campo_novo"}


def test_campo_informativo_declara_o_motivo() -> None:
    for nome, campo in CAMPOS_DO_MANIFESTO.items():
        assert campo.estado or campo.execucao or campo.motivo.strip(), f"sem_motivo campo={nome}"


def test_subcampos_informativos_existem_e_declaram_o_motivo() -> None:
    for nome, motivo in SUBCAMPOS_INFORMATIVOS.items():
        modelo, campo = nome.split(".")
        assert campo in MODELOS_DOS_SUBCAMPOS[modelo].model_fields, nome
        assert motivo.strip(), nome


def _informativos(modelo: str) -> set[str]:
    return {nome.split(".")[1] for nome in SUBCAMPOS_INFORMATIVOS if nome.startswith(f"{modelo}.")}


def test_todo_campo_do_codigo_e_conferido_ou_informativo() -> None:
    conferidos = set(CodeVersion.model_fields) - _informativos("codigo")
    assert conferidos == {"commit", "sujo"}


def test_todo_campo_conferido_do_ambiente_tem_mutacao_de_teste() -> None:
    conferidos = set(Ambiente.model_fields) - _informativos("ambiente")
    assert set(MUTACOES_DO_AMBIENTE) == conferidos


@pytest.mark.parametrize("campo", sorted(MUTACOES_DO_AMBIENTE))
def test_ambiente_que_difere_em_campo_conferido_diverge(campo: str) -> None:
    assert ambiente_divergente(AMBIENTE_BASE, MUTACOES_DO_AMBIENTE[campo](AMBIENTE_BASE))


def test_ambiente_que_so_difere_na_plataforma_nao_diverge() -> None:
    outra = AMBIENTE_BASE.model_copy(update={"plataforma": "Windows-10"})
    assert not ambiente_divergente(AMBIENTE_BASE, outra)
    assert not ambiente_divergente(AMBIENTE_BASE, AMBIENTE_BASE)


def _mensagem_do_estado(conf: Confirmatorio, campo: str) -> str:
    base = f"freeze_incompativel campos={campo} freeze={conf.manifesto.freeze_id}"
    return f"^{re.escape(base)}$"


def _cenarios_do_estado(conf: Confirmatorio, raiz: Path, catalogo: Path) -> dict[str, Modificador]:
    """Por nome em `freeze_incompativel campos=`: o que alterar para que só ele divirja.

    Cada modificador recebe o manifesto e o estado e devolve os dois alterados, de modo que
    também se combinam (ordem dos campos na mensagem).
    """
    base = conf.estado

    def no_estado(**trocas: object) -> Modificador:
        return lambda manifesto, estado: (manifesto, replace(estado, **trocas))

    def no_manifesto(**campos: object) -> Modificador:
        return lambda manifesto, estado: (manifesto.model_copy(update=campos), estado)

    def catalogo_alterado(manifesto: FreezeManifest, estado: EstadoAtual) -> Resultado:
        catalogo.write_text(catalogo.read_text(encoding="utf-8") + "\n# alterado\n")
        return manifesto, estado

    outro_bootstrap = conf.manifesto.bootstrap.model_copy(update={"reamostragens": 7})
    return {
        "config": no_estado(config=base.config.model_copy(update={"semente": 7})),
        "codigo": no_estado(codigo=OUTRO_CODIGO),
        "ambiente": no_estado(ambiente=MUTACOES_DO_AMBIENTE["python"](base.ambiente)),
        "catalogos": catalogo_alterado,
        "entradas": no_estado(datasets=[*base.datasets, sia_pa_desconhecido(raiz)]),
        "split": no_estado(split=base.split.model_copy(update={"limites": ("outro",)})),
        "features": no_estado(
            features=FeatureSpec(feature_set_id="outro", atributos=base.features.atributos)
        ),
        "bootstrap": no_manifesto(bootstrap=outro_bootstrap),
        "metricas": no_manifesto(metricas=("outra_metrica",)),
        "comparacoes": no_manifesto(comparacoes_primarias=("M_TEMP_x_B_ML",)),
        "catalogo": no_estado(regras=carregar_regras()[:-1]),
        "politica": no_estado(politicas=(base.politicas or [])[:-1]),
    }


def test_todo_campo_conferido_no_estado_tem_cenario_de_divergencia(
    tmp_path: Path, confirmatorio: Confirmatorio, catalogo: Path
) -> None:
    esperados = {campo.estado for campo in CAMPOS_DO_MANIFESTO.values() if campo.estado}
    assert set(_cenarios_do_estado(confirmatorio, tmp_path, catalogo)) == esperados


def test_estado_e_execucoes_compativeis_com_o_manifesto_passam(
    confirmatorio: Confirmatorio,
) -> None:
    verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado)
    verificar_congelamento_completo(
        confirmatorio.manifesto, confirmatorio.estado, confirmatorio.runs
    )


ESTADOS = sorted(c.estado for c in CAMPOS_DO_MANIFESTO.values() if c.estado)


@pytest.mark.parametrize("campo", ESTADOS)
def test_divergencia_no_estado_atual_e_recusada(
    tmp_path: Path, confirmatorio: Confirmatorio, catalogo: Path, campo: str
) -> None:
    modificador = _cenarios_do_estado(confirmatorio, tmp_path, catalogo)[campo]
    manifesto, estado = modificador(confirmatorio.manifesto, confirmatorio.estado)
    with pytest.raises(PortaoRecusado, match=_mensagem_do_estado(confirmatorio, campo)):
        verificar_congelamento_completo(manifesto, estado)


def test_divergencias_do_estado_saem_na_ordem_do_protocolo(
    tmp_path: Path, confirmatorio: Confirmatorio, catalogo: Path
) -> None:
    manifesto, estado = confirmatorio.manifesto, confirmatorio.estado
    for modificador in _cenarios_do_estado(confirmatorio, tmp_path, catalogo).values():
        manifesto, estado = modificador(manifesto, estado)
    campos = (
        "codigo,ambiente,split,features,config,catalogos,catalogo,politica,bootstrap,"
        "metricas,comparacoes,entradas"
    )
    with pytest.raises(PortaoRecusado, match=_mensagem_do_estado(confirmatorio, campos)):
        verificar_congelamento_completo(manifesto, estado)


def test_politica_repetida_com_conteudo_diferente_no_estado_diverge(
    confirmatorio: Confirmatorio,
) -> None:
    original = carregar_politica("B_ATEND")
    alterada = original.model_copy(update={"criterios": original.criterios[:1]})
    estado = confirmatorio.estado_com(politicas=[*(confirmatorio.estado.politicas or []), alterada])
    with pytest.raises(PortaoRecusado, match=_mensagem_do_estado(confirmatorio, "politica")):
        verificar_congelamento_completo(confirmatorio.manifesto, estado)


def _mensagem_da_execucao(run: RunResult, campo: str, conf: Confirmatorio) -> str:
    base = f"run_incompativel_com_congelamento run={run.run_id} campo={campo}"
    return f"^{re.escape(base)} freeze={conf.manifesto.freeze_id}$"


def _cenarios_da_execucao(
    conf: Confirmatorio,
) -> dict[str, Callable[[], tuple[list[RunResult], str]]]:
    """Por nome em `campo=` (ou `metodos`): execuções em que só ele diverge e a mensagem."""
    alvo = conf.runs[M_TEMP]

    def com(campo: str, **trocas: object) -> tuple[list[RunResult], str]:
        runs = [alvo.model_copy(update=trocas), *conf.runs[1:]]
        return runs, _mensagem_da_execucao(alvo, campo, conf)

    outro_ambiente = MUTACOES_DO_AMBIENTE["pacotes"](alvo.ambiente)
    sem_b_proc = [run for run in conf.runs if run.metodo is not MetodoId.B_PROC]
    faltam = (
        "avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias metodos=B_PROC "
        f"freeze={conf.manifesto.freeze_id}"
    )
    return {
        "codigo": lambda: com("codigo", codigo=OUTRO_CODIGO),
        "config": lambda: com("config", config_hash=OUTRO_SHA),
        "ambiente": lambda: com("ambiente", ambiente=outro_ambiente),
        "catalogo": lambda: com("catalogo", catalogo_regras_sha256=OUTRO_SHA),
        "politica": lambda: com("politica", politica_id="politica_inventada"),
        "entradas": lambda: com("entradas", entradas=()),
        "metodos": lambda: (sem_b_proc, f"^{re.escape(faltam)}$"),
    }


def test_todo_campo_conferido_na_execucao_tem_cenario_de_divergencia(
    confirmatorio: Confirmatorio,
) -> None:
    esperados = {campo.execucao for campo in CAMPOS_DO_MANIFESTO.values() if campo.execucao}
    assert set(_cenarios_da_execucao(confirmatorio)) == esperados


EXECUCOES = sorted(c.execucao for c in CAMPOS_DO_MANIFESTO.values() if c.execucao)


@pytest.mark.parametrize("campo", EXECUCOES)
def test_divergencia_na_execucao_e_recusada(confirmatorio: Confirmatorio, campo: str) -> None:
    runs, mensagem = _cenarios_da_execucao(confirmatorio)[campo]()
    with pytest.raises(PortaoRecusado, match=mensagem):
        verificar_congelamento_completo(confirmatorio.manifesto, confirmatorio.estado, runs)


def test_readme_lista_todo_campo_do_manifesto() -> None:
    texto = README.read_text(encoding="utf-8")
    assert [nome for nome in FreezeManifest.model_fields if f"`{nome}`" not in texto] == []
