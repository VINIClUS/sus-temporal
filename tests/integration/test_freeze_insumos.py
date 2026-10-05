"""A entrada de validação inteira das regras é congelada e conferida campo a campo (T11).

Cada campo da `EntradaValidacao` que muda o resultado das regras (auxiliares, seleções,
cobertura, `SnapshotSet`, integridade, política, identidade adicional) precisa estar entre o que
o congelamento fixa e a execução de regras confirmatória repete; o campo que o congelamento não
fixava deixava passar a execução que usou outro (outro SIGTAP, outro estado de integridade).
Cenário SINTETICO rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Nenhum resultado empírico.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from tests.fixtures.protocolo_cli import (
    REGISTRO,
    config_confirmatoria_yaml,
    config_yaml,
    congelar_pela_cli,
    executar_cli,
    gravar_insumos,
    gravar_runs,
    manifesto_da_cli,
    preparar_cli,
    runs_da_cli,
)
from tests.fixtures.protocolo_confirmatorio import (
    POLITICAS_DO_PROTOCOLO,
    Confirmatorio,
    como_real,
    insumos_do_teste,
    montar_confirmatorio,
)
from tests.fixtures.protocolo_dados import cenario_baseline
from tests.fixtures.protocolo_insumos import (
    ARTEFATO_DO_INSUMO,
    ESQUEMA_COBERTURA,
    ESQUEMA_SELECAO,
    ESQUEMA_SIGTAP,
    conjunto_sintetico,
    entrada_da_politica,
    entradas_das_execucoes,
    execucao_com_entrada,
    snapshots_sinteticos,
)

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import conteudo_identidade
from sustemporal.contracts.experiment import FreezeManifest, Particao
from sustemporal.errors import ConfigInvalida, ExitCode, PortaoRecusado
from sustemporal.evaluation.freeze_conferencia import (
    verificar_congelamento_completo,
    verificar_execucao,
)
from sustemporal.evaluation.metrics import evaluate_runs
from sustemporal.rules.entrada import ARQUIVO_ENTRADA, EntradaValidacao
from sustemporal.temporal.politicas import carregar_politica

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport, RunResult

OUTRA_VERSAO = "2099-12"
OUTRO_SHA = "f" * 64
M_TEMP, B_ATEND, B_PROC, B_ML = 0, 1, 2, 3


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _variacoes(
    conf: Confirmatorio,
) -> dict[str, tuple[Callable[[EntradaValidacao], EntradaValidacao], str]]:
    """Por campo de `EntradaValidacao`: a alteração só nele e o `campo=` que a conferência acusa.

    O `dataset` de outra partição tira o TESTE das entradas da execução, que também diverge.
    """
    particoes = conf.cenario.split.particoes
    assert particoes is not None

    def trocar(**campos: object) -> Callable[[EntradaValidacao], EntradaValidacao]:
        return lambda entrada: entrada.model_copy(update=campos)

    def com_outro_sigtap(entrada: EntradaValidacao) -> EntradaValidacao:
        outro = conjunto_sintetico(ESQUEMA_SIGTAP, OUTRA_VERSAO)
        return entrada.model_copy(update={"auxiliares": (entrada.auxiliares[0], outro)})

    def com_integridade_alterada(entrada: EntradaValidacao) -> EntradaValidacao:
        alterado = EstadoIntegridade.QUARENTENA_CHECKSUM
        estados = {**entrada.integridade, ARTEFATO_DO_INSUMO: alterado}
        return entrada.model_copy(update={"integridade": estados})

    def com_politica_alterada(entrada: EntradaValidacao) -> EntradaValidacao:
        assert entrada.politica is not None
        alterada = entrada.politica.model_copy(update={"politica_id": "politica_alterada"})
        return entrada.model_copy(update={"politica": alterada})

    outras = conjunto_sintetico
    return {
        "dataset": (trocar(dataset=como_real(particoes[Particao.CALIBRACAO])), "entradas,dataset"),
        "snapshots": (trocar(snapshots=snapshots_sinteticos(OUTRA_VERSAO)), "snapshots"),
        "auxiliares": (com_outro_sigtap, "auxiliares"),
        "selecoes": (trocar(selecoes=outras(ESQUEMA_SELECAO, OUTRA_VERSAO)), "selecoes"),
        "cobertura": (trocar(cobertura=outras(ESQUEMA_COBERTURA, OUTRA_VERSAO)), "cobertura"),
        "integridade": (com_integridade_alterada, "integridade"),
        "politica_documentada": (
            trocar(politica_documentada=carregar_politica("B_PROC")),
            "politica_documentada",
        ),
        "politica": (com_politica_alterada, "politica"),
        "identidade_adicional": (
            trocar(identidade_adicional={"recorte_territorial": OUTRO_SHA}),
            "identidade_adicional",
        ),
    }


def _mensagem(run: RunResult, campo: str, conf: Confirmatorio) -> str:
    base = f"run_incompativel_com_congelamento run={run.run_id} campo={campo}"
    return f"^{re.escape(base)} freeze={conf.manifesto.freeze_id}$"


def _com_entrada_alterada(
    conf: Confirmatorio, indice: int, alterar: Callable[[EntradaValidacao], EntradaValidacao]
) -> tuple[list[RunResult], dict[str, EntradaValidacao]]:
    """Execuções e entradas em que a execução do `indice` usou a entrada alterada, coerente."""
    run = conf.runs[indice]
    entrada = alterar(conf.entradas[run.run_id])
    runs = [*conf.runs[:indice], execucao_com_entrada(run, entrada), *conf.runs[indice + 1 :]]
    return runs, {**conf.entradas, run.run_id: entrada}


def _verificar(
    conf: Confirmatorio, runs: list[RunResult], entradas: dict[str, EntradaValidacao]
) -> None:
    verificar_congelamento_completo(conf.manifesto, conf.estado, runs, entradas)


def _avaliar(
    conf: Confirmatorio, out: Path, runs: list[RunResult], entradas: dict[str, EntradaValidacao]
) -> EvaluationReport:
    return evaluate_runs(
        runs,
        conf.rotulos,
        conf.cenario.split,
        out,
        bootstrap=conf.manifesto.bootstrap,
        congelamento=conf.referencia(entradas=entradas),
    )


def test_manifesto_grava_a_identidade_de_cada_campo_da_entrada_por_politica(
    confirmatorio: Confirmatorio,
) -> None:
    congeladas = confirmatorio.manifesto.entradas_validacao
    assert congeladas is not None
    assert set(congeladas) == set(POLITICAS_DO_PROTOCOLO)
    for politica, campos in congeladas.items():
        assert set(campos) == set(EntradaValidacao.model_fields), politica
    por_politica = [congeladas[p] for p in POLITICAS_DO_PROTOCOLO]
    assert len({campos["snapshots"] for campos in por_politica}) == len(POLITICAS_DO_PROTOCOLO)
    assert len({campos["selecoes"] for campos in por_politica}) == len(POLITICAS_DO_PROTOCOLO)
    assert len({campos["cobertura"] for campos in por_politica}) == 1
    assert len({campos["auxiliares"] for campos in por_politica}) == 1


def test_a_politica_congelada_da_entrada_e_a_do_catalogo_congelado(
    confirmatorio: Confirmatorio,
) -> None:
    congeladas = confirmatorio.manifesto.entradas_validacao
    catalogo = confirmatorio.manifesto.politicas_sha256
    assert congeladas is not None
    assert catalogo is not None
    for politica in POLITICAS_DO_PROTOCOLO:
        assert congeladas[politica]["politica"] == catalogo[politica]


def test_execucoes_cuja_entrada_gravada_so_traz_a_mais_a_politica_resolvida_passam(
    confirmatorio: Confirmatorio,
) -> None:
    for run in confirmatorio.runs[:B_ML]:
        assert confirmatorio.entradas[run.run_id].politica is not None
    _verificar(confirmatorio, confirmatorio.runs, confirmatorio.entradas)


def test_todo_campo_da_entrada_de_validacao_tem_cenario_de_divergencia(
    confirmatorio: Confirmatorio,
) -> None:
    assert set(_variacoes(confirmatorio)) == set(EntradaValidacao.model_fields)


@pytest.mark.parametrize("indice", [M_TEMP, B_ATEND, B_PROC], ids=["m_temp", "b_atend", "b_proc"])
@pytest.mark.parametrize("campo", sorted(EntradaValidacao.model_fields))
def test_execucao_de_regras_cuja_entrada_difere_da_congelada_em_um_campo_e_recusada(
    confirmatorio: Confirmatorio, indice: int, campo: str
) -> None:
    alterar, esperado = _variacoes(confirmatorio)[campo]
    runs, entradas = _com_entrada_alterada(confirmatorio, indice, alterar)
    mensagem = _mensagem(confirmatorio.runs[indice], esperado, confirmatorio)
    with pytest.raises(PortaoRecusado, match=mensagem):
        _verificar(confirmatorio, runs, entradas)


def test_entrada_alterada_e_recusada_antes_de_ler_dados_e_de_gravar(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    alterar, esperado = _variacoes(confirmatorio)["integridade"]
    runs, entradas = _com_entrada_alterada(confirmatorio, M_TEMP, alterar)
    mensagem = _mensagem(confirmatorio.runs[M_TEMP], esperado, confirmatorio)
    with pytest.raises(PortaoRecusado, match=mensagem):
        _avaliar(confirmatorio, tmp_path / "av", runs, entradas)
    assert not (tmp_path / "av").exists()


def test_varios_campos_divergentes_saem_na_ordem_da_entrada(confirmatorio: Confirmatorio) -> None:
    variacoes = _variacoes(confirmatorio)
    alteracoes = [
        variacoes[campo][0] for campo in ("integridade", "snapshots", "identidade_adicional")
    ]

    def todas(entrada: EntradaValidacao) -> EntradaValidacao:
        for alterar in alteracoes:
            entrada = alterar(entrada)
        return entrada

    runs, entradas = _com_entrada_alterada(confirmatorio, M_TEMP, todas)
    campos = "snapshots,integridade,identidade_adicional"
    mensagem = _mensagem(confirmatorio.runs[M_TEMP], campos, confirmatorio)
    with pytest.raises(PortaoRecusado, match=mensagem):
        _verificar(confirmatorio, runs, entradas)


def test_execucao_de_regras_sem_entrada_de_validacao_e_recusada(
    confirmatorio: Confirmatorio,
) -> None:
    run = confirmatorio.runs[B_ATEND]
    entradas = {k: v for k, v in confirmatorio.entradas.items() if k != run.run_id}
    with pytest.raises(PortaoRecusado, match=_mensagem(run, "entrada_validacao", confirmatorio)):
        _verificar(confirmatorio, confirmatorio.runs, entradas)


def test_entrada_de_outra_execucao_e_recusada_como_entrada_de_validacao(
    confirmatorio: Confirmatorio,
) -> None:
    run = confirmatorio.runs[M_TEMP]
    de_outra = confirmatorio.entradas[confirmatorio.runs[B_ATEND].run_id]
    entradas = {**confirmatorio.entradas, run.run_id: de_outra}
    with pytest.raises(PortaoRecusado, match=_mensagem(run, "entrada_validacao", confirmatorio)):
        _verificar(confirmatorio, confirmatorio.runs, entradas)


def test_baseline_nao_e_conferido_na_entrada_de_validacao(confirmatorio: Confirmatorio) -> None:
    baseline = confirmatorio.runs[B_ML]
    assert baseline.politica_id is None
    verificar_execucao(confirmatorio.manifesto, baseline, config=confirmatorio.config)


def test_execucao_de_politica_desconhecida_diverge_so_em_politica(
    confirmatorio: Confirmatorio,
) -> None:
    original = confirmatorio.runs[M_TEMP]
    run = original.model_copy(update={"politica_id": "politica_inventada"})
    with pytest.raises(PortaoRecusado, match=_mensagem(run, "politica", confirmatorio)):
        verificar_execucao(
            confirmatorio.manifesto,
            run,
            config=confirmatorio.config,
            entrada=confirmatorio.entradas[original.run_id],
        )


def test_manifesto_sem_insumos_recusa_toda_execucao_de_regras(
    tmp_path: Path, cenario: Cenario
) -> None:
    conf = montar_confirmatorio(tmp_path, cenario, insumos={})
    assert conf.manifesto.entradas_validacao is None
    run = conf.runs[M_TEMP]
    with pytest.raises(PortaoRecusado, match=_mensagem(run, "entrada_validacao", conf)):
        _verificar(conf, conf.runs, conf.entradas)


def test_politica_sem_insumos_congelados_recusa_so_as_execucoes_dela(
    tmp_path: Path, cenario: Cenario
) -> None:
    insumos = {k: v for k, v in insumos_do_teste(cenario).items() if k != "B_PROC"}
    conf = montar_confirmatorio(tmp_path, cenario, insumos=insumos)
    for run in conf.runs[:B_PROC]:
        entrada = conf.entradas[run.run_id]
        verificar_execucao(conf.manifesto, run, config=conf.config, entrada=entrada)
    run = conf.runs[B_PROC]
    entrada = conf.entradas[run.run_id]
    with pytest.raises(PortaoRecusado, match=_mensagem(run, "entrada_validacao", conf)):
        verificar_execucao(conf.manifesto, run, config=conf.config, entrada=entrada)


def test_manifesto_sem_insumos_nao_leva_o_campo_novo_na_identidade(
    tmp_path: Path, cenario: Cenario
) -> None:
    manifesto = montar_confirmatorio(tmp_path, cenario, insumos={}).manifesto
    identidade = conteudo_identidade(manifesto, excluir={"freeze_id"})
    conteudo = identidade["conteudo"]
    assert isinstance(conteudo, dict)
    assert "entradas_validacao" not in conteudo
    assert manifesto.freeze_id == FreezeManifest.calcular_id(identidade)


def test_congelar_recusa_insumos_de_outra_populacao(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.particoes is not None
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    de_outra = insumos_do_teste(cenario)["B_ATEND"].model_copy(update={"dataset": calibracao})
    insumos = {**insumos_do_teste(cenario), "B_ATEND": de_outra}
    with pytest.raises(ConfigInvalida, match="congelamento_insumos_de_outra_populacao") as erro:
        montar_confirmatorio(tmp_path, cenario, insumos=insumos)
    assert "politicas=B_ATEND" in str(erro.value)


def test_congelar_recusa_insumo_com_politica_diferente_da_congelada(
    tmp_path: Path, cenario: Cenario
) -> None:
    base = insumos_do_teste(cenario)
    outra = carregar_politica("B_ATEND").model_copy(update={"politica_id": "outra"})
    com_outra = base["B_ATEND"].model_copy(update={"politica": outra})
    with pytest.raises(ConfigInvalida, match="congelamento_insumos_com_politica_diferente") as erro:
        montar_confirmatorio(tmp_path, cenario, insumos={**base, "B_ATEND": com_outra})
    assert "politica=B_ATEND" in str(erro.value)


def test_cli_congela_a_identidade_de_cada_campo_da_convencao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    congeladas = manifesto_da_cli(tmp_path, freeze).entradas_validacao
    assert congeladas is not None
    assert set(congeladas) == set(POLITICAS_DO_PROTOCOLO)
    assert all(set(campos) == set(EntradaValidacao.model_fields) for campos in congeladas.values())


def test_cli_freeze_sem_insumos_sai_com_config_invalida_e_nao_congela(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    preparar_cli(tmp_path, monkeypatch)
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    pasta = tmp_path / "saidas" / "split" / "insumos"
    assert f"freeze_sem_insumos_das_execucoes pasta={pasta}" in capsys.readouterr().err
    assert not (tmp_path / "frozen").exists()


def test_cli_freeze_recusa_insumo_ilegivel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario = preparar_cli(tmp_path, monkeypatch)
    arquivo = gravar_insumos(tmp_path, cenario) / "B_ATEND.json"
    arquivo.write_text("{", encoding="utf-8")
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert f"freeze_insumos_ilegiveis arquivo={arquivo}" in capsys.readouterr().err
    assert not (tmp_path / "frozen").exists()


def test_cli_freeze_recusa_insumo_de_outra_populacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario = preparar_cli(tmp_path, monkeypatch)
    assert cenario.split.particoes is not None
    arquivo = gravar_insumos(tmp_path, cenario) / "B_ATEND.json"
    calibracao = como_real(cenario.split.particoes[Particao.CALIBRACAO])
    teste = como_real(cenario.split.particoes[Particao.TESTE])
    de_outra = entrada_da_politica(teste, "B_ATEND").model_copy(update={"dataset": calibracao})
    arquivo.write_text(de_outra.model_dump_json(), encoding="utf-8")
    codigo = executar_cli(["freeze", "--config", str(config_yaml(tmp_path))])
    assert codigo == ExitCode.CONFIG_INVALIDA
    assert "congelamento_insumos_de_outra_populacao politicas=B_ATEND" in capsys.readouterr().err


def _avaliar_pela_cli(raiz: Path, freeze: str) -> int:
    config = config_confirmatoria_yaml(raiz, freeze)
    return executar_cli(["evaluate", "--config", str(config), "--freeze", freeze])


def test_cli_avalia_o_confirmatorio_cujas_entradas_sao_as_congeladas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    pasta = tmp_path / "saidas" / "runs"
    assert all((pasta / run.run_id / ARQUIVO_ENTRADA).is_file() for run in runs[:B_ML])
    assert not (pasta / runs[B_ML].run_id / ARQUIVO_ENTRADA).exists()
    assert _avaliar_pela_cli(tmp_path, freeze) == ExitCode.OK


def test_cli_recusa_o_confirmatorio_com_entrada_de_outra_integridade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    alvo = runs[B_ATEND]
    gravada = entradas_das_execucoes(runs)[alvo.run_id]
    estados = {**gravada.integridade, ARTEFATO_DO_INSUMO: EstadoIntegridade.QUARENTENA_TRUNCADO}
    alterada = gravada.model_copy(update={"integridade": estados})
    gravar_runs(tmp_path, runs, entradas={alvo.run_id: alterada})
    assert _avaliar_pela_cli(tmp_path, freeze) == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert f"run_incompativel_com_congelamento run={alvo.run_id} campo=integridade" in erro
    assert not (tmp_path / "frozen" / REGISTRO).exists()
    assert not (tmp_path / "saidas" / "avaliacao").exists()


def test_cli_recusa_o_confirmatorio_sem_o_arquivo_da_entrada_de_validacao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    alvo = runs[B_PROC]
    (tmp_path / "saidas" / "runs" / alvo.run_id / ARQUIVO_ENTRADA).unlink()
    assert _avaliar_pela_cli(tmp_path, freeze) == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert f"run_incompativel_com_congelamento run={alvo.run_id} campo=entrada_validacao" in erro
    assert not (tmp_path / "frozen" / REGISTRO).exists()


@pytest.mark.parametrize(
    ("conteudo", "motivo"),
    [
        (b"{", "ValidationError"),
        (b"\xff\xfe\x00{", "UnicodeDecodeError"),
        (b"{}", "ValidationError"),
    ],
    ids=["json_truncado", "utf8_invalido", "fora_do_contrato"],
)
def test_cli_recusa_o_confirmatorio_com_entrada_de_validacao_ilegivel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    conteudo: bytes,
    motivo: str,
) -> None:
    cenario, freeze = congelar_pela_cli(tmp_path, monkeypatch)
    runs = runs_da_cli(tmp_path, cenario, freeze)
    gravar_runs(tmp_path, runs)
    alvo = runs[M_TEMP]
    (tmp_path / "saidas" / "runs" / alvo.run_id / ARQUIVO_ENTRADA).write_bytes(conteudo)
    assert _avaliar_pela_cli(tmp_path, freeze) == ExitCode.PORTAO_RECUSADO
    erro = capsys.readouterr().err
    assert f"evaluate_entrada_ilegivel run={alvo.run_id} motivo={motivo}" in erro
    assert f"run_incompativel_com_congelamento run={alvo.run_id} campo=entrada_validacao" in erro
