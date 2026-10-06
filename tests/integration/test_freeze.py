"""Congelamento, registro e avaliação do T11 (SINTETICO; decisões só em diretório temporário)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.fixtures.protocolo_avaliacao import (
    CODIGO_LIMPO,
    escrever_decisao,
    relogio,
    run_agregados,
)
from tests.fixtures.protocolo_cli import gravar_insumos
from tests.fixtures.protocolo_dados import Cenario, cenario_baseline

from sustemporal.cli import main
from sustemporal.config import load_config
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.evaluation import EvaluationReport
from sustemporal.contracts.experiment import (
    Atributo,
    FeatureSpec,
    ModoExecucao,
    Particao,
    RunResult,
)
from sustemporal.contracts.temporal import MetodoId
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro, PortaoRecusado
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.freeze import Protocolo, carregar_freeze, congelar
from sustemporal.evaluation.freeze_conferencia import EstadoAtual, verificar_congelamento_completo
from sustemporal.evaluation.freeze_registro import (
    exigir_rodada_permitida,
    ler_registro,
    registrar_execucao,
)
from sustemporal.evaluation.metrics import ReferenciaCongelamento, evaluate_runs
from sustemporal.runtime_info import ambiente

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts.experiment import FreezeManifest

CATALOGO_SIA_PA = Path(__file__).resolve().parents[2] / "catalog" / "schemas" / "sia_pa.yaml"
CATALOGOS = {"esquema_sia_pa": CATALOGO_SIA_PA}
CONFIG_PROTOCOLO: dict[str, Any] = {
    "versao": "1",
    "origem_dados": "SINTETICO",
    "bootstrap": {"correcao": "HOLM", "reamostragens": 200},
    "catalogos": {nome: str(caminho) for nome, caminho in CATALOGOS.items()},
}


def _protocolo(cenario: Cenario, **config: Any) -> Protocolo:
    return Protocolo(
        config=RunConfig.model_validate({**CONFIG_PROTOCOLO, **config}),
        split=cenario.split,
        features=FEATURES_PADRAO,
        dataset=cenario.dataset,
        rotulos=cenario.rotulos,
        catalogos=CATALOGOS,
    )


def _congelar(tmp_path: Path, cenario: Cenario, destino: str = "frozen") -> FreezeManifest:
    decisoes = tmp_path / "decisoes"
    escrever_decisao(decisoes, "G0", "CONTINUAR")
    return congelar(
        _protocolo(cenario),
        tmp_path / destino,
        decisoes=decisoes,
        codigo=CODIGO_LIMPO,
        relogio=relogio,
    )


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


def test_manifesto_deterministico(tmp_path: Path, cenario: Cenario) -> None:
    primeiro = _congelar(tmp_path, cenario)
    segundo = _congelar(tmp_path, cenario)
    outro_destino = _congelar(tmp_path, cenario, "frozen_2")
    assert primeiro == segundo == outro_destino
    arquivos = sorted((tmp_path / "frozen").iterdir())
    assert [a.name for a in arquivos] == [f"{primeiro.freeze_id}.json"]
    assert primeiro.comparacoes_primarias == ("M_TEMP_x_B_ATEND", "M_TEMP_x_B_PROC")
    assert primeiro.bootstrap.semente == 2027
    assert primeiro.decisao_g0 == "experiments/decisions/g0_teste.yaml"
    assert {d.schema_id for d in primeiro.datasets} == {"sia_pa.v1", "sia_pa_rotulos.v1"}
    assert carregar_freeze(tmp_path / "frozen", primeiro.freeze_id) == primeiro


@pytest.mark.parametrize("decisao", [None, "REFORMULAR"])
def test_recusa_sem_g0(tmp_path: Path, cenario: Cenario, decisao: str | None) -> None:
    decisoes = tmp_path / "decisoes"
    if decisao is not None:
        escrever_decisao(decisoes, "G0", decisao)
    with pytest.raises(PortaoRecusado):
        congelar(
            _protocolo(cenario),
            tmp_path / "frozen",
            decisoes=decisoes,
            codigo=CODIGO_LIMPO,
            relogio=relogio,
        )
    assert not (tmp_path / "frozen").exists()


def test_recusa_protocolo_com_valor_a_definir(tmp_path: Path, cenario: Cenario) -> None:
    escrever_decisao(tmp_path / "decisoes", "G0", "CONTINUAR")
    with pytest.raises(ConfigInvalida, match="congelamento_invalido"):
        congelar(
            _protocolo(cenario, bootstrap={"correcao": "A_DEFINIR"}),
            tmp_path / "frozen",
            decisoes=tmp_path / "decisoes",
            codigo=CODIGO_LIMPO,
            relogio=relogio,
        )


def _compativel(manifesto: FreezeManifest, cenario: Cenario, **trocas: Any) -> None:
    argumentos: dict[str, Any] = {
        "config": RunConfig.model_validate(CONFIG_PROTOCOLO),
        "split": cenario.split,
        "features": FEATURES_PADRAO,
        "datasets": [cenario.dataset, cenario.rotulos],
        "codigo": CODIGO_LIMPO,
        "ambiente": ambiente(Path.cwd()),
    }
    verificar_congelamento_completo(manifesto, EstadoAtual(**{**argumentos, **trocas}))


def test_recusa_entrada_incompativel(tmp_path: Path, cenario: Cenario) -> None:
    manifesto = _congelar(tmp_path, cenario)
    _compativel(manifesto, cenario)
    outro_atributo = Atributo(
        nome="cbo", schema_id="sia_pa.v1", coluna="cbo", transformacao="CATEGORICA"
    )
    trocas: dict[str, Any] = {
        "features": FeatureSpec(feature_set_id="outro", atributos=(outro_atributo,)),
        "codigo": CODIGO_LIMPO.model_copy(update={"commit": "b" * 40}),
        "config": RunConfig.model_validate({**CONFIG_PROTOCOLO, "semente": "7"}),
        "datasets": [cenario.dataset.model_copy(update={"hash_logico": f"lh1:{'f' * 64}"})],
        "split": cenario.split.model_copy(update={"split_id": "spl_outro"}),
    }
    for campo, valor in trocas.items():
        with pytest.raises(PortaoRecusado, match="freeze_incompativel"):
            _compativel(manifesto, cenario, **{campo: valor})
    with pytest.raises(PortaoRecusado, match="freeze_incompativel"):
        _compativel(manifesto, cenario, codigo=CODIGO_LIMPO.model_copy(update={"sujo": True}))


def test_config_confirmatoria_do_mesmo_protocolo_e_compativel(
    tmp_path: Path, cenario: Cenario
) -> None:
    escrever_decisao(tmp_path / "decisoes", "G0", "CONTINUAR")
    manifesto = congelar(
        _protocolo(cenario, origem_dados="REAL"),
        tmp_path / "frozen",
        decisoes=tmp_path / "decisoes",
        codigo=CODIGO_LIMPO,
        relogio=relogio,
    )
    confirmatoria = RunConfig.model_validate(
        {
            **CONFIG_PROTOCOLO,
            "modo": "CONFIRMATORIO",
            "origem_dados": "REAL",
            "freeze_id": manifesto.freeze_id,
        }
    )
    _compativel(manifesto, cenario, config=confirmatoria)
    with pytest.raises(PortaoRecusado, match="freeze_incompativel campos=config"):
        _compativel(manifesto, cenario, config=RunConfig.model_validate(CONFIG_PROTOCOLO))


def test_manifesto_adulterado_e_recusado(tmp_path: Path, cenario: Cenario) -> None:
    manifesto = _congelar(tmp_path, cenario)
    caminho = tmp_path / "frozen" / f"{manifesto.freeze_id}.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados["comparacoes_primarias"] = ["M_TEMP_x_B_ML"]
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="congelamento_invalido"):
        carregar_freeze(tmp_path / "frozen", manifesto.freeze_id)


def _relatorio(report_id: str, **campos: Any) -> EvaluationReport:
    base: dict[str, Any] = {
        "report_id": report_id,
        "modo": "EXPLORATORIO",
        "origem_dados": "SINTETICO",
        "criado_em": "2026-01-01T00:00:00Z",
        "metricas": [{"nome": "M.cobertura_rejeicoes", "numerador": 0, "denominador": 0}],
    }
    return EvaluationReport.model_validate({**base, **campos})


FREEZE_A = f"frz_{'1' * 64}"
FREEZE_B = f"frz_{'2' * 64}"


def _confirmatorio(report_id: str, freeze_id: str = FREEZE_A) -> EvaluationReport:
    return _relatorio(
        report_id,
        modo="CONFIRMATORIO",
        origem_dados="REAL",
        freeze_id=freeze_id,
        decisao_g2="experiments/decisions/g2_teste.yaml",
        metricas=[],
    )


def test_registro_append_only(tmp_path: Path) -> None:
    registro = tmp_path / "registro.jsonl"
    nulo = registrar_execucao(registro, _relatorio("rep_a"), relogio=relogio)
    assert nulo["metricas_nulas"] == 1
    registrar_execucao(registro, _confirmatorio("rep_b"), relogio=relogio)
    with pytest.raises(ValueError, match="correcao_sem_declaracao"):
        registrar_execucao(registro, _confirmatorio("rep_c"), corrige="rep_b", relogio=relogio)
    with pytest.raises(ValueError, match="correcao_de_execucao_inexistente"):
        registrar_execucao(
            registro, _confirmatorio("rep_c"), corrige="rep_x", declaracao="bug", relogio=relogio
        )
    registrar_execucao(
        registro,
        _confirmatorio("rep_c"),
        corrige="rep_b",
        declaracao="erro de agregação corrigido no commit X",
        relogio=relogio,
    )
    entradas = ler_registro(registro)
    assert [e["report_id"] for e in entradas] == ["rep_a", "rep_b", "rep_c"]
    assert entradas[2]["corrige"] == "rep_b"
    linhas = registro.read_text(encoding="utf-8").splitlines()
    linhas[0] = linhas[0].replace("rep_a", "rep_z")
    registro.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with pytest.raises(FalhaOperacionalErro, match="registro_adulterado"):
        registrar_execucao(registro, _relatorio("rep_d"), relogio=relogio)


def _com_byte_invalido(registro: Path) -> None:
    registrar_execucao(registro, _relatorio("rep_a"), relogio=relogio)
    registro.write_bytes(registro.read_bytes() + b"\xff\n")


ILEGIVEIS: dict[str, Callable[[Path], None]] = {
    "utf8_invalido": _com_byte_invalido,
    "diretorio": lambda registro: registro.mkdir(),
}


@pytest.mark.parametrize("estrago", sorted(ILEGIVEIS))
def test_registro_ilegivel_e_falha_operacional(tmp_path: Path, estrago: str) -> None:
    """Auditoria final, F4: o byte 0xFF ou o registro que não abre não escapam como traceback."""
    registro = tmp_path / "registro.jsonl"
    ILEGIVEIS[estrago](registro)
    with pytest.raises(FalhaOperacionalErro, match="registro_adulterado motivo="):
        ler_registro(registro)
    with pytest.raises(FalhaOperacionalErro, match="registro_adulterado"):
        exigir_rodada_permitida(registro, ModoExecucao.CONFIRMATORIO, FREEZE_A)
    with pytest.raises(FalhaOperacionalErro, match="registro_adulterado"):
        registrar_execucao(registro, _relatorio("rep_b"), relogio=relogio)


def test_segunda_rodada_confirmatoria_exige_correcao_declarada(tmp_path: Path) -> None:
    """Só a estrutura do registro: relatórios sem dados, nenhum resultado empírico."""
    freeze = f"frz_{'1' * 64}"
    campos = {
        "modo": "CONFIRMATORIO",
        "origem_dados": "REAL",
        "freeze_id": freeze,
        "decisao_g2": "experiments/decisions/g2_teste.yaml",
        "metricas": [],
    }
    registro = tmp_path / "registro.jsonl"
    registrar_execucao(registro, _relatorio("rep_1", **campos), relogio=relogio)
    with pytest.raises(PortaoRecusado, match="reabertura_do_teste_sem_correcao_declarada"):
        registrar_execucao(registro, _relatorio("rep_2", **campos), relogio=relogio)
    with pytest.raises(PortaoRecusado, match="reabertura_do_teste_sem_correcao_declarada"):
        exigir_rodada_permitida(registro, ModoExecucao.CONFIRMATORIO, freeze)
    exigir_rodada_permitida(registro, ModoExecucao.EXPLORATORIO, freeze)
    registrar_execucao(
        registro,
        _relatorio("rep_2", **campos),
        corrige="rep_1",
        declaracao="bug no carregamento; rodada rep_1 preservada",
        relogio=relogio,
    )
    assert len(ler_registro(registro)) == 2


def test_correcao_de_outro_congelamento_ou_de_exploratorio_nao_reabre_o_teste(
    tmp_path: Path,
) -> None:
    """Só a estrutura do registro: relatórios sem dados, nenhum resultado empírico."""
    registro = tmp_path / "registro.jsonl"
    registrar_execucao(registro, _confirmatorio("rep_a1", FREEZE_A), relogio=relogio)
    registrar_execucao(registro, _confirmatorio("rep_b1", FREEZE_B), relogio=relogio)
    registrar_execucao(registro, _relatorio("rep_expl", freeze_id=FREEZE_A), relogio=relogio)
    antes = registro.read_text(encoding="utf-8")
    alvos = {
        "rep_b1": "correcao_de_outro_congelamento",
        "rep_expl": "correcao_de_relatorio_nao_confirmatorio",
        "rep_x": "correcao_de_execucao_inexistente",
    }
    for alvo, motivo in alvos.items():
        with pytest.raises(ValueError, match=motivo):
            registrar_execucao(
                registro,
                _confirmatorio("rep_a2", FREEZE_A),
                corrige=alvo,
                declaracao="bug no carregamento",
                relogio=relogio,
            )
    assert registro.read_text(encoding="utf-8") == antes
    with pytest.raises(PortaoRecusado, match="reabertura_do_teste_sem_correcao_declarada"):
        registrar_execucao(registro, _confirmatorio("rep_a2", FREEZE_A), relogio=relogio)
    registrar_execucao(
        registro,
        _confirmatorio("rep_a2", FREEZE_A),
        corrige="rep_a1",
        declaracao="bug no carregamento; rodada rep_a1 preservada",
        relogio=relogio,
    )
    entradas = ler_registro(registro)
    assert [e["report_id"] for e in entradas] == ["rep_a1", "rep_b1", "rep_expl", "rep_a2"]
    assert entradas[3]["corrige"] == "rep_a1"


def test_correcao_na_primeira_rodada_nao_cita_relatorio_de_outro_congelamento(
    tmp_path: Path,
) -> None:
    registro = tmp_path / "registro.jsonl"
    registrar_execucao(registro, _confirmatorio("rep_a1", FREEZE_A), relogio=relogio)
    with pytest.raises(ValueError, match="correcao_de_outro_congelamento"):
        registrar_execucao(
            registro,
            _confirmatorio("rep_b1", FREEZE_B),
            corrige="rep_a1",
            declaracao="bug",
            relogio=relogio,
        )
    assert [e["report_id"] for e in ler_registro(registro)] == ["rep_a1"]


def _runs_exploratorios(
    cenario: Cenario, out: Path, config: RunConfig | None = None
) -> list[RunResult]:
    """Execuções exploratórias sobre a CALIBRACAO, feitas com `config` (a do cenário se omitida)."""
    assert cenario.split.particoes is not None
    config = config or cenario.config
    comuns: dict[str, Any] = {
        "config_hash": config.config_hash,
        "entradas": (cenario.split.particoes[Particao.CALIBRACAO],),
    }
    calibracao = [
        linha for linha in cenario.linhas if linha.competencia_processamento in {"202301"}
    ]
    resultados = {
        MetodoId.M_TEMP: {
            linha.row_id: "ALERTA" if linha.procedimento == "0000000001" else "ABSTENCAO"
            for linha in calibracao
        },
        MetodoId.B_ATEND: {linha.row_id: "SEM_VIOLACAO_VERIFICADA" for linha in calibracao},
        MetodoId.B_PROC: {linha.row_id: "ALERTA" for linha in calibracao[:5]},
    }
    runs = [run_agregados(m, r, out, **comuns) for m, r in resultados.items()]
    runs.append(fit_baseline(cenario.split, FEATURES_PADRAO, config, out / "bml"))
    return runs


def test_avaliacao_exploratoria_na_calibracao(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    runs = _runs_exploratorios(cenario, tmp_path / "runs")
    relatorio = evaluate_runs(runs, rotulos, cenario.split, tmp_path / "avaliacao")
    assert relatorio.modo is ModoExecucao.EXPLORATORIO
    assert relatorio.origem_dados is OrigemDados.SINTETICO
    metricas = {(m.nome, m.estrato): m for m in relatorio.metricas}
    for metodo in ("M_TEMP", "B_ATEND", "B_PROC", "B_ML", "CONTROLE_TRIVIAL"):
        assert (f"{metodo}.cobertura_rejeicoes", "TOTAL") in metricas
    assert metricas[("M_TEMP.cobertura_rejeicoes", "TOTAL")].ic is not None
    assert metricas[("B_ATEND.cobertura_rejeicoes", "TOTAL")].numerador == 0
    for estrato in ("TOTAL", "sensibilidade_blocos_temporais"):
        assert ("diferenca.M_TEMP_x_B_ATEND.cobertura_rejeicoes", estrato) in metricas
    assert ("divergencia.M_TEMP_x_B_PROC.so_M_TEMP", "TOTAL") in metricas
    populacao = metricas[("populacao.tamanho_estrato", "TOTAL")]
    assert populacao.numerador == cenario.split.linhas_por_particao[Particao.CALIBRACAO]
    assert (tmp_path / "avaliacao" / f"{relatorio.report_id}.json").is_file()
    assert any("estabelecimento" in nota for nota in relatorio.notas)


def test_avaliacao_exploratoria_nao_usa_o_teste(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    runs = _runs_exploratorios(cenario, tmp_path / "runs")
    with pytest.raises(PortaoRecusado, match="avaliacao_exploratoria_no_teste"):
        evaluate_runs(
            runs,
            cenario.split.rotulos_por_particao[Particao.TESTE],
            cenario.split,
            tmp_path / "avaliacao",
        )


def test_rotulos_fora_do_split_sao_recusados(tmp_path: Path, cenario: Cenario) -> None:
    runs = _runs_exploratorios(cenario, tmp_path / "runs")
    with pytest.raises(ValueError, match="rotulos_fora_do_split"):
        evaluate_runs(runs, cenario.rotulos, cenario.split, tmp_path / "avaliacao")


def _config_cli(tmp_path: Path, **extra: str) -> Path:
    linhas = [
        'versao: "1"',
        f"origem_dados: {extra.pop('origem_dados', 'SINTETICO')}",
        "runtime:",
        f"  raiz_saidas: {tmp_path / 'saidas'}",
        f"  dir_congelamentos: {tmp_path / 'frozen'}",
        "bootstrap:",
        "  correcao: HOLM",
        "  reamostragens: 100",
        "catalogos:",
        f"  esquema_sia_pa: {CATALOGO_SIA_PA}",
        *(f"{chave}: {valor}" for chave, valor in extra.items()),
    ]
    caminho = tmp_path / "config.yaml"
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return caminho


def test_freeze_cli_sem_g0_sai_com_codigo_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["freeze", "--config", str(_config_cli(tmp_path))]) == ExitCode.PORTAO_RECUSADO


def test_evaluate_confirmatorio_sem_g2_sai_com_codigo_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    freeze = f"frz_{'2' * 64}"
    config = _config_cli(tmp_path, origem_dados="REAL", modo="CONFIRMATORIO", freeze_id=freeze)
    argumentos = ["evaluate", "--config", str(config), "--freeze", freeze]
    assert main(argumentos) == ExitCode.PORTAO_RECUSADO


def test_cli_congela_e_avalia_exploratorio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = tmp_path / "trabalho"
    raiz.mkdir()
    cenario = cenario_baseline(raiz / "saidas", competencias=("202001", "202301", "202401"))
    config = _config_cli(raiz)
    runs = _runs_exploratorios(cenario, raiz / "saidas" / "runs", load_config(config))
    for run in runs:
        destino = raiz / "saidas" / "runs" / run.run_id
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "run.json").write_text(run.model_dump_json(), encoding="utf-8")
    monkeypatch.chdir(raiz)
    monkeypatch.setattr("sustemporal.evaluation.cli.versao_codigo", lambda _: CODIGO_LIMPO)
    escrever_decisao(raiz / "experiments" / "decisions", "G0", "CONTINUAR")
    gravar_insumos(raiz, cenario)
    assert main(["freeze", "--config", str(config)]) == ExitCode.OK
    (manifesto,) = sorted((raiz / "frozen").glob("frz_*.json"))
    freeze = manifesto.stem
    argumentos = ["evaluate", "--config", str(config), "--freeze", freeze, "--exploratory"]
    assert main(argumentos) == ExitCode.OK
    (entrada,) = ler_registro(raiz / "frozen" / "registro_execucoes.jsonl")
    assert entrada["freeze_id"] == freeze
    assert entrada["modo"] == "EXPLORATORIO"


def test_intervalo_reamostra_estabelecimentos(tmp_path: Path, cenario: Cenario) -> None:
    from sustemporal.contracts.experiment import BootstrapSpec
    from sustemporal.evaluation.bootstrap import intervalo_razao

    assert cenario.split.rotulos_por_particao is not None
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    alertas = {
        lp.row_id: "ALERTA" if lp.cnes in {"0000000", "0000001"} else "ABSTENCAO"
        for lp in calibracao
    }
    run = run_agregados(MetodoId.M_TEMP, alertas, tmp_path / "runs")
    spec = BootstrapSpec(reamostragens=300, correcao="HOLM")
    relatorio = evaluate_runs([run], rotulos, cenario.split, tmp_path / "av", bootstrap=spec)
    metrica = next(
        m
        for m in relatorio.metricas
        if (m.nome, m.estrato) == ("M_TEMP.cobertura_verificabilidade", "TOTAL")
    )
    ordenadas = sorted(calibracao, key=lambda lp: lp.row_id)
    nums = [int(alertas[lp.row_id] == "ALERTA") for lp in ordenadas]
    esperado = intervalo_razao(nums, [1] * len(nums), [lp.cnes or "" for lp in ordenadas], spec)
    assert metrica.ic == esperado


def test_confirmatorio_com_execucao_de_outro_freeze_e_recusado(
    tmp_path: Path, cenario: Cenario
) -> None:
    assert cenario.split.rotulos_por_particao is not None
    teste = [lp for lp in cenario.linhas if lp.competencia_processamento == "202401"]
    run = run_agregados(MetodoId.M_TEMP, {lp.row_id: "ALERTA" for lp in teste}, tmp_path / "runs")
    confirmatorio = run.model_copy(
        update={"modo": ModoExecucao.CONFIRMATORIO, "freeze_id": f"frz_{'3' * 64}"}
    )
    with pytest.raises(PortaoRecusado, match="execucao_de_outro_freeze"):
        evaluate_runs(
            [confirmatorio],
            cenario.split.rotulos_por_particao[Particao.TESTE],
            cenario.split,
            tmp_path / "av",
            congelamento=ReferenciaCongelamento(
                f"frz_{'4' * 64}", "experiments/decisions/g2.yaml", tmp_path / "decisoes"
            ),
        )


def test_confirmatorio_sem_g2_e_recusado_na_biblioteca(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    freeze = f"frz_{'5' * 64}"
    teste = [lp for lp in cenario.linhas if lp.competencia_processamento == "202401"]
    run = run_agregados(MetodoId.M_TEMP, {lp.row_id: "ALERTA" for lp in teste}, tmp_path / "runs")
    confirmatorio = run.model_copy(update={"modo": ModoExecucao.CONFIRMATORIO, "freeze_id": freeze})
    with pytest.raises(PortaoRecusado, match="portao_sem_decisao"):
        evaluate_runs(
            [confirmatorio],
            cenario.split.rotulos_por_particao[Particao.TESTE],
            cenario.split,
            tmp_path / "av",
            congelamento=ReferenciaCongelamento(
                freeze, "experiments/decisions/g2.yaml", tmp_path / "decisoes"
            ),
        )


def test_predicoes_de_outra_execucao_nao_entram(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    (bml,) = [
        r for r in _runs_exploratorios(cenario, tmp_path / "runs") if r.metodo is MetodoId.B_ML
    ]
    outro = bml.model_copy(update={"run_id": "bml_outra_execucao"})
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    relatorio = evaluate_runs([outro], rotulos, cenario.split, tmp_path / "av")
    abstencao = next(
        m for m in relatorio.metricas if (m.nome, m.estrato) == ("B_ML.abstencao", "TOTAL")
    )
    assert abstencao.numerador == abstencao.denominador > 0


def test_rotulos_que_nao_cobrem_a_particao_sao_falha_operacional(
    tmp_path: Path, cenario: Cenario
) -> None:
    from tests.fixtures.protocolo_dados import gravar_rotulos

    assert cenario.split.rotulos_por_particao is not None
    teste = [lp for lp in cenario.linhas if lp.competencia_processamento == "202401"]
    trocado = gravar_rotulos({lp.row_id: "APROVADO_TOTAL" for lp in teste}, tmp_path / "t.parquet")
    adulterado = {**cenario.split.rotulos_por_particao, Particao.CALIBRACAO: trocado}
    split = cenario.split.model_copy(update={"rotulos_por_particao": adulterado})
    runs = _runs_exploratorios(cenario, tmp_path / "runs")[:1]
    with pytest.raises(FalhaOperacionalErro, match="rotulos_fora_da_particao"):
        evaluate_runs(runs, trocado, split, tmp_path / "av")


def test_relatorio_nunca_e_sobrescrito(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    runs = _runs_exploratorios(cenario, tmp_path / "runs")[:1]
    primeiro = evaluate_runs(runs, rotulos, cenario.split, tmp_path / "av", relogio=relogio)
    caminho = tmp_path / "av" / f"{primeiro.report_id}.json"
    caminho.write_text(caminho.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(FalhaOperacionalErro, match="relatorio_existente_divergente"):
        evaluate_runs(runs, rotulos, cenario.split, tmp_path / "av", relogio=relogio)


def test_diferenca_nula_mantem_intervalo(tmp_path: Path, cenario: Cenario) -> None:
    assert cenario.split.rotulos_por_particao is not None
    rotulos = cenario.split.rotulos_por_particao[Particao.CALIBRACAO]
    calibracao = [lp for lp in cenario.linhas if lp.competencia_processamento == "202301"]
    iguais = {lp.row_id: "ALERTA" for lp in calibracao}
    runs = [
        run_agregados(MetodoId.M_TEMP, iguais, tmp_path / "runs"),
        run_agregados(MetodoId.B_ATEND, iguais, tmp_path / "runs"),
    ]
    relatorio = evaluate_runs(runs, rotulos, cenario.split, tmp_path / "av")
    diferenca = next(
        m
        for m in relatorio.metricas
        if (m.nome, m.estrato) == ("diferenca.M_TEMP_x_B_ATEND.cobertura_rejeicoes", "TOTAL")
    )
    assert diferenca.valor == 0
    assert diferenca.ic is not None
