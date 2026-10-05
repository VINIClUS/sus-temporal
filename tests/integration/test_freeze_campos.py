"""Todo campo do FreezeManifest é conferido ou declarado informativo, com o motivo (T11).

Cenário SINTETICO rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Um campo novo no manifesto sem classificação, ou classificado como conferido sem cenário de
divergência, derruba os testes daqui.
"""

from __future__ import annotations

import re
import shutil
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

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import RunResult
    from sustemporal.evaluation.freeze_conferencia import EstadoAtual

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


def _cenarios_do_estado(
    conf: Confirmatorio, raiz: Path, catalogo: Path
) -> dict[str, Callable[[], tuple[FreezeManifest, EstadoAtual]]]:
    """Por nome em `freeze_incompativel campos=`: manifesto e estado em que só ele diverge."""
    manifesto, estado = conf.manifesto, conf.estado

    def catalogo_alterado() -> tuple[FreezeManifest, EstadoAtual]:
        catalogo.write_text(catalogo.read_text(encoding="utf-8") + "\n# alterado\n")
        return manifesto, estado

    def manifesto_com(**campos: object) -> tuple[FreezeManifest, EstadoAtual]:
        return manifesto.model_copy(update=campos), estado

    outro_bootstrap = manifesto.bootstrap.model_copy(update={"reamostragens": 7})
    atributos = estado.features.atributos
    outra_config = estado.config.model_copy(update={"semente": 7})
    return {
        "config": lambda: (manifesto, conf.estado_com(config=outra_config)),
        "codigo": lambda: (manifesto, conf.estado_com(codigo=OUTRO_CODIGO)),
        "ambiente": lambda: (
            manifesto,
            conf.estado_com(ambiente=MUTACOES_DO_AMBIENTE["python"](estado.ambiente)),
        ),
        "catalogos": catalogo_alterado,
        "entradas": lambda: (
            manifesto,
            conf.estado_com(datasets=[*estado.datasets, sia_pa_desconhecido(raiz)]),
        ),
        "split": lambda: (
            manifesto,
            conf.estado_com(split=estado.split.model_copy(update={"limites": ("outro",)})),
        ),
        "features": lambda: (
            manifesto,
            conf.estado_com(features=FeatureSpec(feature_set_id="outro", atributos=atributos)),
        ),
        "bootstrap": lambda: manifesto_com(bootstrap=outro_bootstrap),
        "metricas": lambda: manifesto_com(metricas=("outra_metrica",)),
        "comparacoes": lambda: manifesto_com(comparacoes_primarias=("M_TEMP_x_B_ML",)),
        "catalogo": lambda: (manifesto, conf.estado_com(regras=carregar_regras()[:-1])),
        "politica": lambda: (manifesto, conf.estado_com(politicas=(estado.politicas or [])[:-1])),
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
    manifesto, estado = _cenarios_do_estado(confirmatorio, tmp_path, catalogo)[campo]()
    with pytest.raises(PortaoRecusado, match=_mensagem_do_estado(confirmatorio, campo)):
        verificar_congelamento_completo(manifesto, estado)


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
