"""Rodada registrada do congelamento como o registro a descreve (T14); SINTETICO.

O relatório lido em `avaliacao/<freeze_id>/<report_id>.json` só vale se bate com a entrada do
registro de rodadas (`report_id`, `freeze_id`, modo, origem dos dados, lista de execuções e a
contagem das métricas); um relatório válido que não é o registrado é original indisponível.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.evaluation import EvaluationReport, ValorMetrica
from sustemporal.contracts.experiment import (
    Ambiente,
    CodeVersion,
    EstadoExecucao,
    ModoExecucao,
    RunResult,
    TipoExecucao,
)
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import FalhaOperacionalErro
from sustemporal.evaluation.cli import REGISTRO
from sustemporal.evaluation.freeze_registro import ler_registro, registrar_execucao
from sustemporal.reporting.reproduce_original import (
    Original,
    campos_que_nao_conferem,
    ler_original,
)
from sustemporal.reporting.reproduce_varredura import Dano
from tests.fixtures.reproducao_estragos import estragado

if TYPE_CHECKING:
    from pathlib import Path

FREEZE = "frz_" + "a" * 64
OUTRO_FREEZE = "frz_" + "b" * 64
REPORT = "rep_" + "c" * 64
RUN_A = "val_" + "a" * 40
RUN_B = "val_" + "b" * 40
RUN_C = "val_" + "c" * 40
G2 = "experiments/decisions/g2.yaml"
INSTANTE = datetime(2026, 1, 1, tzinfo=UTC)


def _metrica(nome: str, *, nula: bool = False) -> ValorMetrica:
    if nula:
        return ValorMetrica(nome=nome, numerador=0, denominador=0)
    return ValorMetrica(nome=nome, numerador=1, denominador=2, valor=Decimal("0.5"))


def _relatorio(**trocas: Any) -> EvaluationReport:
    campos: dict[str, Any] = {
        "report_id": REPORT,
        "modo": ModoExecucao.EXPLORATORIO,
        "origem_dados": OrigemDados.SINTETICO,
        "freeze_id": FREEZE,
        "runs": ("run_a", "run_b"),
        "metricas": (_metrica("m1"), _metrica("m2", nula=True), _metrica("m3")),
        "notas": ("particao=CALIBRACAO",),
        "criado_em": INSTANTE,
        **trocas,
    }
    return EvaluationReport(**campos)


def _config(tmp_path: Path) -> RunConfig:
    runtime = {
        "raiz_saidas": str(tmp_path / "saidas"),
        "dir_congelamentos": str(tmp_path / "congelamentos"),
    }
    return RunConfig.model_validate({"versao": "1", "runtime": runtime})


def _registrar(tmp_path: Path, registrada: EvaluationReport) -> None:
    registrar_execucao(tmp_path / "congelamentos" / REGISTRO, registrada)


def _gravar(tmp_path: Path, relatorio: EvaluationReport, nome: str = REPORT) -> None:
    pasta = tmp_path / "saidas" / "avaliacao" / FREEZE
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome}.json").write_text(relatorio.model_dump_json(), encoding="utf-8")


def _lido(tmp_path: Path, relatorio: EvaluationReport) -> Original:
    """Registra `_relatorio()` e deixa em seu lugar o `relatorio` que o arquivo traz."""
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, relatorio)
    return ler_original(_config(tmp_path), FREEZE)


def test_relatorio_que_bate_com_a_entrada_do_registro_e_o_original(tmp_path: Path) -> None:
    original = _lido(tmp_path, _relatorio())
    assert original.relatorio == _relatorio()
    assert original.observacoes == ()


def test_sem_registro_de_rodadas_nao_ha_original(tmp_path: Path) -> None:
    _gravar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, dict(original.execucoes), original.observacoes) == (None, {}, ())


def test_rodada_de_outro_congelamento_ou_modo_nao_e_a_deste(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio(freeze_id=OUTRO_FREEZE))
    _gravar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert original.relatorio is None
    assert original.observacoes == ()


def test_relatorio_ausente_nao_e_relatorio_diferente_do_registrado(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio())
    original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, original.observacoes) == (None, ())


TROCAS = {
    "report_id": {"report_id": "rep_" + "d" * 64},
    "freeze_id": {"freeze_id": OUTRO_FREEZE},
    "modo": {
        "modo": ModoExecucao.CONFIRMATORIO,
        "origem_dados": OrigemDados.REAL,
        "decisao_g2": G2,
    },
    "origem_dados": {"origem_dados": OrigemDados.REAL},
    "decisao_g2": {"decisao_g2": G2},
    "runs": {"runs": ("run_a", "run_c")},
    "metricas": {"metricas": (_metrica("m1"), _metrica("m2", nula=True))},
    "metricas_nulas": {"metricas": (_metrica("m1"), _metrica("m2"), _metrica("m3"))},
}


@pytest.mark.parametrize("campo", list(TROCAS))
def test_relatorio_que_nao_e_o_registrado_vira_original_indisponivel(
    tmp_path: Path, campo: str
) -> None:
    original = _lido(tmp_path, _relatorio(**TROCAS[campo]))
    assert original.relatorio is None
    esperado = {"modo": "modo,origem_dados,decisao_g2"}.get(campo, campo)
    assert original.observacoes == (
        f"relatorio_original_nao_confere_com_o_registro campos={esperado}",
    )


def test_decisao_g2_do_relatorio_so_confere_com_a_do_registro() -> None:
    entrada: dict[str, Any] = {"report_id": REPORT, "freeze_id": FREEZE, "modo": "EXPLORATORIO"}
    entrada |= {"origem_dados": "SINTETICO", "runs": ["run_a", "run_b"], "metricas": 3}
    entrada |= {"metricas_nulas": 1, "decisao_g2": None}
    assert campos_que_nao_conferem(_relatorio(), entrada) == []
    assert campos_que_nao_conferem(_relatorio(decisao_g2=G2), entrada) == ["decisao_g2"]
    assert campos_que_nao_conferem(_relatorio(), {**entrada, "decisao_g2": G2}) == ["decisao_g2"]


def test_execucoes_em_outra_ordem_nao_conferem(tmp_path: Path) -> None:
    original = _lido(tmp_path, _relatorio(runs=("run_b", "run_a")))
    assert original.relatorio is None
    assert original.observacoes[0].endswith("campos=runs")


def test_varios_campos_diferentes_saem_todos_na_ordem_do_registro(tmp_path: Path) -> None:
    trocas = {**TROCAS["freeze_id"], **TROCAS["runs"], **TROCAS["origem_dados"]}
    original = _lido(tmp_path, _relatorio(**trocas))
    assert original.observacoes == (
        "relatorio_original_nao_confere_com_o_registro campos=freeze_id,origem_dados,runs",
    )


def test_campos_que_nao_conferem_so_olha_o_que_o_registro_traz() -> None:
    relatorio = _relatorio()
    entrada: dict[str, Any] = {
        "report_id": REPORT,
        "freeze_id": FREEZE,
        "modo": "EXPLORATORIO",
        "origem_dados": "SINTETICO",
        "runs": ["run_a", "run_b"],
        "metricas": 3,
        "metricas_nulas": 1,
    }
    assert campos_que_nao_conferem(relatorio, entrada) == []
    assert campos_que_nao_conferem(relatorio, {**entrada, "metricas_nulas": 0}) == [
        "metricas_nulas"
    ]
    assert campos_que_nao_conferem(relatorio, {**entrada, "runs": ["run_a"]}) == ["runs"]


def test_entrada_sem_um_campo_do_registro_nao_confere_com_o_relatorio() -> None:
    entrada: dict[str, Any] = {"report_id": REPORT}
    campos = campos_que_nao_conferem(_relatorio(), entrada)
    assert campos == ["freeze_id", "modo", "origem_dados", "runs", "metricas", "metricas_nulas"]


def _execucao(run_id: str, metodo: MetodoId | None) -> RunResult:
    return RunResult(
        run_id=run_id,
        tipo=TipoExecucao.VALIDACAO,
        metodo=metodo,
        modo=ModoExecucao.EXPLORATORIO,
        config_hash="a" * 64,
        codigo=CodeVersion(commit="abc", sujo=False, versao_pacote="0.1"),
        ambiente=Ambiente(python="3.12", plataforma="linux"),
        estado=EstadoExecucao.CONCLUIDA,
        iniciado_em=INSTANTE,
        origem_dados=OrigemDados.SINTETICO,
    )


def _gravar_execucoes(tmp_path: Path, *execucoes: RunResult) -> Original:
    """Registra uma rodada com os três `run_id` e grava só as `execucoes` dadas."""
    relatorio = _relatorio(runs=(RUN_A, RUN_B, RUN_C))
    _registrar(tmp_path, relatorio)
    _gravar(tmp_path, relatorio)
    for execucao in execucoes:
        pasta = tmp_path / "saidas" / "runs" / execucao.run_id
        pasta.mkdir(parents=True)
        (pasta / "run_result.json").write_text(execucao.model_dump_json(), encoding="utf-8")
    return ler_original(_config(tmp_path), FREEZE)


def test_execucao_registrada_que_nao_existe_nao_impede_ler_as_seguintes(tmp_path: Path) -> None:
    primeira = _execucao(RUN_A, MetodoId.M_TEMP)
    terceira = _execucao(RUN_C, MetodoId.B_PROC)
    original = _gravar_execucoes(tmp_path, primeira, terceira)
    assert dict(original.execucoes) == {MetodoId.M_TEMP: primeira, MetodoId.B_PROC: terceira}


def test_execucao_registrada_sem_metodo_fica_de_fora(tmp_path: Path) -> None:
    sem_metodo = _execucao(RUN_A, None)
    com_metodo = _execucao(RUN_B, MetodoId.B_ATEND)
    original = _gravar_execucoes(tmp_path, sem_metodo, com_metodo)
    assert dict(original.execucoes) == {MetodoId.B_ATEND: com_metodo}


def test_metodo_com_duas_execucoes_registradas_fica_sem_original_e_vira_observacao(
    tmp_path: Path,
) -> None:
    primeira = _execucao(RUN_A, MetodoId.M_TEMP)
    segunda = _execucao(RUN_B, MetodoId.M_TEMP)
    outro = _execucao(RUN_C, MetodoId.B_PROC)
    original = _gravar_execucoes(tmp_path, primeira, segunda, outro)
    assert dict(original.execucoes) == {MetodoId.B_PROC: outro}
    assert original.observacoes == ("execucao_registrada_repetida metodo=M_TEMP",)


def test_execucao_repetida_do_metodo_conta_uma_observacao_so_e_nao_volta_na_terceira(
    tmp_path: Path,
) -> None:
    execucoes = [_execucao(run, MetodoId.M_TEMP) for run in (RUN_A, RUN_B, RUN_C)]
    original = _gravar_execucoes(tmp_path, *execucoes)
    assert dict(original.execucoes) == {}
    assert original.observacoes == ("execucao_registrada_repetida metodo=M_TEMP",)


def test_execucao_repetida_junta_a_observacao_do_relatorio_que_nao_confere(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio(runs=(RUN_A, RUN_B, RUN_C)))
    _gravar(tmp_path, _relatorio(runs=(RUN_A, RUN_B)))
    for execucao in (_execucao(RUN_A, MetodoId.B_PROC), _execucao(RUN_B, MetodoId.B_PROC)):
        pasta = tmp_path / "saidas" / "runs" / execucao.run_id
        pasta.mkdir(parents=True)
        (pasta / "run_result.json").write_text(execucao.model_dump_json(), encoding="utf-8")
    original = ler_original(_config(tmp_path), FREEZE)
    assert original.observacoes == (
        "relatorio_original_nao_confere_com_o_registro campos=runs",
        "execucao_registrada_repetida metodo=B_PROC",
    )


def test_relatorio_que_nao_confere_e_registrado_no_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="sustemporal.reporting.reproduce_original"):
        _lido(tmp_path, _relatorio(runs=("run_a", "run_c")))
    assert f"relatorio_original_nao_confere report={REPORT} campos=runs" in caplog.messages


@pytest.mark.parametrize(
    ("dano", "erro"),
    [(Dano.DIRETORIO, "IsADirectoryError"), (Dano.PERMISSAO, "PermissionError")],
)
def test_registro_que_nao_abre_deixa_a_rodada_sem_original_e_diz_por_que(
    tmp_path: Path, dano: Dano, erro: str
) -> None:
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, _relatorio())
    with estragado(tmp_path / "congelamentos" / REGISTRO, dano):
        original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, dict(original.execucoes)) == (None, {})
    assert original.observacoes == (f"registro_ilegivel erro={erro}",)


def _ler_registro_que_traduz_o_erro_de_leitura(registro: Path) -> list[dict[str, Any]]:
    """O `ler_registro` que põe o erro de leitura em `registro_adulterado` (auditoria F4, S5)."""
    try:
        return ler_registro(registro)
    except (OSError, UnicodeDecodeError) as erro:
        raise FalhaOperacionalErro(f"registro_adulterado erro={type(erro).__name__}") from erro


@pytest.mark.parametrize(
    ("dano", "erro"),
    [(Dano.DIRETORIO, "IsADirectoryError"), (Dano.PERMISSAO, "PermissionError")],
)
def test_registro_que_nao_abre_segue_sem_original_mesmo_se_o_ler_registro_traduz_o_erro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dano: Dano, erro: str
) -> None:
    alvo = "sustemporal.reporting.reproduce_original.ler_registro"
    monkeypatch.setattr(alvo, _ler_registro_que_traduz_o_erro_de_leitura)
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, _relatorio())
    with estragado(tmp_path / "congelamentos" / REGISTRO, dano):
        original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, dict(original.execucoes)) == (None, {})
    assert original.observacoes == (f"registro_ilegivel erro={erro}",)


def test_registro_com_bytes_que_nao_decodificam_e_registro_adulterado(tmp_path: Path) -> None:
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, _relatorio())
    with (
        estragado(tmp_path / "congelamentos" / REGISTRO, Dano.BYTES),
        pytest.raises(FalhaOperacionalErro, match=r"^registro_adulterado erro=UnicodeDecodeError$"),
    ):
        ler_original(_config(tmp_path), FREEZE)


def test_registro_ilegivel_registra_o_arquivo_e_o_erro_no_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caminho = tmp_path / "congelamentos" / REGISTRO
    _registrar(tmp_path, _relatorio())
    with (
        caplog.at_level(logging.WARNING, logger="sustemporal.reporting.reproduce_original"),
        estragado(caminho, Dano.DIRETORIO),
    ):
        ler_original(_config(tmp_path), FREEZE)
    assert f"registro_ilegivel caminho={caminho} erro=IsADirectoryError" in caplog.messages


@pytest.mark.parametrize("dano", list(Dano))
def test_relatorio_original_que_nao_abre_e_original_indisponivel_sem_observacao(
    tmp_path: Path, dano: Dano
) -> None:
    _registrar(tmp_path, _relatorio())
    _gravar(tmp_path, _relatorio())
    with estragado(tmp_path / "saidas" / "avaliacao" / FREEZE / f"{REPORT}.json", dano):
        original = ler_original(_config(tmp_path), FREEZE)
    assert (original.relatorio, original.observacoes) == (None, ())


@pytest.mark.parametrize("dano", list(Dano))
def test_execucao_registrada_que_nao_abre_fica_sem_original_e_as_outras_seguem(
    tmp_path: Path, dano: Dano
) -> None:
    primeira, segunda = _execucao(RUN_A, MetodoId.M_TEMP), _execucao(RUN_B, MetodoId.B_ATEND)
    _registrar(tmp_path, _relatorio(runs=(RUN_A, RUN_B)))
    _gravar(tmp_path, _relatorio(runs=(RUN_A, RUN_B)))
    for execucao in (primeira, segunda):
        pasta = tmp_path / "saidas" / "runs" / execucao.run_id
        pasta.mkdir(parents=True)
        (pasta / "run_result.json").write_text(execucao.model_dump_json(), encoding="utf-8")
    with estragado(tmp_path / "saidas" / "runs" / RUN_A / "run_result.json", dano):
        original = ler_original(_config(tmp_path), FREEZE)
    assert dict(original.execucoes) == {MetodoId.B_ATEND: segunda}
    assert original.observacoes == ()
