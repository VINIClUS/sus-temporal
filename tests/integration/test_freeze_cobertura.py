"""Cobertura dos resultados de cada método sobre a população avaliada (T11, SINTETICO).

Uma execução CONCLUIDA cuja saída omite registros do TESTE seguia para a rodada, e cada
resultado ausente virava abstenção. Cenário sintético rotulado REAL só nos contratos;
decisões G0/G2 só em diretórios temporários. Nenhum resultado empírico.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, run_agregados
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_runs,
    manifesto_da_cli,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    CONFIG_PROTOCOLO,
    Confirmatorio,
    como_real,
    config_confirmatoria,
    montar_confirmatorio,
    resultados_do_teste,
    run_compativel,
    split_como_real,
)
from tests.fixtures.protocolo_dados import cenario_baseline
from tests.fixtures.protocolo_predicoes import predicoes_sem_linhas_do_teste

from sustemporal.config import load_config
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import Particao
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ExitCode, PortaoRecusado
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport, RunResult, SplitManifest

M_TEMP, B_ATEND, B_ML = 0, 1, 3
POR_COMPETENCIA = 30
METODOS = ("M_TEMP", "B_ATEND", "B_PROC", "B_ML")
NOTA = "cobertura_dos_resultados"


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _avaliar(conf: Confirmatorio, out: Path, runs: list[RunResult]) -> EvaluationReport:
    return evaluate_runs(
        runs,
        conf.rotulos,
        conf.cenario.split,
        out,
        bootstrap=conf.manifesto.bootstrap,
        congelamento=conf.referencia(),
    )


def _trocar(conf: Confirmatorio, raiz: Path, indice: int, **campos: object) -> list[RunResult]:
    """Execuções com a do `indice` refeita pelos `campos` de `run_compativel`."""
    antiga = conf.runs[indice]
    assert antiga.metodo is not None
    nova = run_compativel(
        conf.cenario, conf.manifesto, conf.config, raiz / "novas", antiga.metodo, **campos
    )
    return [*conf.runs[:indice], nova, *conf.runs[indice + 1 :]]


def _sem_os_primeiros(conf: Confirmatorio, metodo: MetodoId, omitidos: int) -> dict[str, str]:
    completos = resultados_do_teste(conf.cenario, metodo)
    return dict(sorted(completos.items())[omitidos:])


def _mensagem(metodo: str, ausentes: int, extras: int) -> str:
    base = f"execucao_com_cobertura_incompleta metodo={metodo} ausentes={ausentes} extras={extras}"
    return f"^{re.escape(base)}$"


def _da_calibracao(conf: Confirmatorio) -> list[str]:
    linhas = conf.cenario.linhas
    return [lp.row_id for lp in linhas if lp.competencia_processamento == "202301"]


@pytest.mark.parametrize("indice", [M_TEMP, B_ML], ids=["motor", "baseline"])
@pytest.mark.parametrize("omitidos", [1, 7, POR_COMPETENCIA])
def test_confirmatorio_recusa_execucao_sem_resultado_de_linhas_do_teste(
    tmp_path: Path, confirmatorio: Confirmatorio, indice: int, omitidos: int
) -> None:
    metodo = confirmatorio.runs[indice].metodo
    assert metodo is not None
    resultados = _sem_os_primeiros(confirmatorio, metodo, omitidos)
    runs = _trocar(confirmatorio, tmp_path, indice, resultados=resultados)
    with pytest.raises(PortaoRecusado, match=_mensagem(metodo.value, omitidos, 0)):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_confirmatorio_recusa_pelo_primeiro_metodo_em_ordem_alfabetica(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    sem_dois = _sem_os_primeiros(confirmatorio, MetodoId.M_TEMP, 2)
    runs = _trocar(confirmatorio, tmp_path, M_TEMP, resultados=sem_dois)
    sem_cinco = _sem_os_primeiros(confirmatorio, MetodoId.B_ATEND, 5)
    runs = _trocar(replace(confirmatorio, runs=runs), tmp_path, B_ATEND, resultados=sem_cinco)
    with pytest.raises(PortaoRecusado, match=_mensagem("B_ATEND", 5, 0)):
        _avaliar(confirmatorio, tmp_path / "av", runs)


def test_confirmatorio_recusa_resultado_de_linha_fora_do_teste_se_a_execucao_so_declara_o_teste(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    completos = resultados_do_teste(confirmatorio.cenario, MetodoId.M_TEMP)
    com_extras = {**completos, **dict.fromkeys(_da_calibracao(confirmatorio), "ALERTA")}
    runs = _trocar(confirmatorio, tmp_path, M_TEMP, resultados=com_extras)
    with pytest.raises(PortaoRecusado, match=_mensagem("M_TEMP", 0, POR_COMPETENCIA)):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_confirmatorio_aceita_resultado_de_outras_particoes_se_a_execucao_as_declara(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    split = confirmatorio.cenario.split
    assert split.particoes is not None
    completos = resultados_do_teste(confirmatorio.cenario, MetodoId.M_TEMP)
    com_extras = {**completos, **dict.fromkeys(_da_calibracao(confirmatorio), "ALERTA")}
    calibracao = como_real(split.particoes[Particao.CALIBRACAO])
    runs = _trocar(
        confirmatorio, tmp_path, M_TEMP, resultados=com_extras, entradas_a_mais=(calibracao,)
    )
    relatorio = _avaliar(confirmatorio, tmp_path / "av", runs)
    nota = f"cobertura_dos_resultados metodo=M_TEMP ausentes=0 extras={POR_COMPETENCIA}"
    assert nota in relatorio.notas


def test_relatorio_confirmatorio_registra_a_cobertura_de_cada_metodo_em_ordem_alfabetica(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    relatorio = _avaliar(confirmatorio, tmp_path / "av", confirmatorio.runs)
    notas = [nota for nota in relatorio.notas if nota.startswith(NOTA)]
    assert notas == [f"{NOTA} metodo={m} ausentes=0 extras=0" for m in sorted(METODOS)]


@pytest.mark.parametrize("com_manifesto", [False, True], ids=["sem_manifesto", "com_manifesto"])
def test_exploratorio_so_registra_as_contagens_de_cobertura(
    tmp_path: Path, cenario: Cenario, com_manifesto: bool
) -> None:
    assert cenario.split.rotulos_por_particao is not None
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    parcial = {lp.row_id: "ALERTA" for lp in calibracao[:5]}
    run = run_agregados(MetodoId.B_PROC, parcial, tmp_path / "exploratorio")
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    congelamento = None
    if com_manifesto:
        manifesto = montar_confirmatorio(tmp_path, cenario).manifesto
        congelamento = ReferenciaCongelamento(manifesto.freeze_id, manifesto=manifesto)
    relatorio = evaluate_runs(
        [run], rotulos, cenario.split, tmp_path / "av", congelamento=congelamento
    )
    ausentes = len(calibracao) - 5
    assert f"{NOTA} metodo=B_PROC ausentes={ausentes} extras=0" in relatorio.notas
    abstencao = next(m for m in relatorio.metricas if m.nome == "B_PROC.abstencao")
    assert abstencao.numerador == ausentes


@dataclass(frozen=True)
class ComBaselineReal:
    """Confirmatório com as três execuções do motor e o baseline ajustado pelo `fit_baseline`."""

    conf: Confirmatorio
    split: SplitManifest
    runs: list[RunResult]

    def avaliar(self, out: Path, runs: list[RunResult] | None = None) -> EvaluationReport:
        rotulos = (self.split.rotulos_por_particao or {})[Particao.TESTE]
        return evaluate_runs(
            self.runs if runs is None else runs,
            rotulos,
            self.split,
            out,
            bootstrap=self.conf.manifesto.bootstrap,
            congelamento=self.conf.referencia(),
        )


@pytest.fixture
def com_baseline_real(
    tmp_path: Path, cenario: Cenario, monkeypatch: pytest.MonkeyPatch
) -> ComBaselineReal:
    monkeypatch.setattr("sustemporal.evaluation.baselines.versao_codigo", lambda _: CODIGO_LIMPO)
    runtime = {"dir_congelamentos": str(tmp_path / "frozen")}
    real = split_como_real(cenario.split)
    protocolo = RunConfig.model_validate({**CONFIG_PROTOCOLO, "runtime": runtime})
    conf = montar_confirmatorio(tmp_path, cenario, config=protocolo, split=real)
    config = config_confirmatoria(conf.manifesto.freeze_id, runtime=runtime)
    baseline = fit_baseline(
        real, FEATURES_PADRAO, config, tmp_path / "bml", decisoes=conf.decisoes, codigo=CODIGO_LIMPO
    )
    motores = [
        run_compativel(cenario, conf.manifesto, config, tmp_path / "motor", metodo)
        for metodo in (MetodoId.M_TEMP, MetodoId.B_ATEND, MetodoId.B_PROC)
    ]
    estado = conf.estado_com(config=config)
    return ComBaselineReal(replace(conf, config=config, estado=estado), real, [*motores, baseline])


def test_baseline_real_no_confirmatorio_tem_cobertura_completa_nos_dois_metodos(
    tmp_path: Path, com_baseline_real: ComBaselineReal
) -> None:
    relatorio = com_baseline_real.avaliar(tmp_path / "av")
    for metodo in ("B_ML", "CONTROLE_TRIVIAL"):
        assert f"cobertura_dos_resultados metodo={metodo} ausentes=0 extras=0" in relatorio.notas


@pytest.mark.parametrize(
    ("metodo", "quantas", "ausentes"),
    [("B_ML", 4, 4), ("CONTROLE_TRIVIAL", None, POR_COMPETENCIA), ("B_ML", None, POR_COMPETENCIA)],
    ids=["b_ml_parcial", "controle_trivial_sem_nenhuma", "b_ml_sem_nenhuma"],
)
def test_baseline_com_predicoes_do_teste_a_menos_e_recusado(
    tmp_path: Path,
    com_baseline_real: ComBaselineReal,
    metodo: str,
    quantas: int | None,
    ausentes: int,
) -> None:
    *motores, baseline = com_baseline_real.runs
    cortada = predicoes_sem_linhas_do_teste(
        baseline, tmp_path / "cortada", metodo=metodo, quantas=quantas
    )
    with pytest.raises(PortaoRecusado, match=_mensagem(metodo, ausentes, 0)):
        com_baseline_real.avaliar(tmp_path / "av", [*motores, cortada])
    assert not (tmp_path / "av").exists()


def test_cli_recusa_o_confirmatorio_com_execucao_sem_resultado_de_linhas_do_teste(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    config = load_config(config_confirmatoria_yaml(tmp_path, freeze))
    completos = resultados_do_teste(cenario, MetodoId.B_PROC)
    parcial = run_compativel(
        cenario,
        manifesto_da_cli(tmp_path, freeze),
        config,
        tmp_path / "saidas" / "runs",
        MetodoId.B_PROC,
        resultados=dict(sorted(completos.items())[3:]),
    )
    gravar_runs(tmp_path, [*(r for r in runs if r.metodo is not MetodoId.B_PROC), parcial])
    argumentos = ["evaluate", "--config", str(config_confirmatoria_yaml(tmp_path, freeze))]
    assert executar_cli([*argumentos, "--freeze", freeze]) == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert "execucao_com_cobertura_incompleta metodo=B_PROC ausentes=3 extras=0" in erro
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()
