"""Execuções confirmatórias conferidas contra o FreezeManifest antes de ler dados (T11).

Cenário SINTETICO rotulado REAL só nos contratos; decisões G0/G2 só em diretórios temporários.
Nenhum resultado empírico: as execuções são tabelas sintéticas para exercitar os portões.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO
from tests.fixtures.protocolo_confirmatorio import (
    CONFIG_PROTOCOLO,
    Confirmatorio,
    como_real,
    config_confirmatoria,
    montar_confirmatorio,
    politicas_do_catalogo,
    sia_pa_desconhecido,
    split_como_real,
)
from tests.fixtures.protocolo_dados import cenario_baseline

from sustemporal.contracts.base import conteudo_identidade, hash_canonico
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import (
    EstadoExecucao,
    FreezeManifest,
    ModoExecucao,
    Particao,
    TipoExecucao,
)
from sustemporal.errors import ConfigInvalida, PortaoRecusado
from sustemporal.evaluation.baselines import fit_baseline
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.freeze_conferencia import verificar_execucao
from sustemporal.evaluation.metrics import evaluate_runs
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256
from sustemporal.temporal.politicas import carregar_politica

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.fixtures.protocolo_dados import Cenario

    from sustemporal.contracts import EvaluationReport, RunResult

OUTRO_CODIGO = CODIGO_LIMPO.model_copy(update={"commit": "b" * 40})
OUTRO_HASH = f"lh1:{'e' * 64}"
OUTRO_SHA = "f" * 64
OUTRO_FREEZE = f"frz_{'9' * 64}"
M_TEMP, B_ATEND, B_PROC, B_ML = range(4)


@pytest.fixture(scope="module")
def cenario(tmp_path_factory: pytest.TempPathFactory) -> Cenario:
    return cenario_baseline(tmp_path_factory.mktemp("cenario"))


@pytest.fixture
def confirmatorio(tmp_path: Path, cenario: Cenario) -> Confirmatorio:
    return montar_confirmatorio(tmp_path, cenario)


def _avaliar(
    conf: Confirmatorio, out: Path, runs: list[RunResult] | None = None, **trocas: Any
) -> EvaluationReport:
    return evaluate_runs(
        conf.runs if runs is None else runs,
        conf.rotulos,
        conf.cenario.split,
        out,
        bootstrap=conf.manifesto.bootstrap,
        congelamento=conf.referencia(**trocas),
    )


def _mensagem(run: RunResult, campo: str, conf: Confirmatorio) -> str:
    base = f"run_incompativel_com_congelamento run={run.run_id} campo={campo}"
    return f"^{re.escape(base)} freeze={conf.manifesto.freeze_id}$"


def test_execucoes_compativeis_com_o_manifesto_sao_avaliadas(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    relatorio = _avaliar(confirmatorio, tmp_path / "av")
    assert relatorio.modo is ModoExecucao.CONFIRMATORIO
    assert relatorio.freeze_id == confirmatorio.manifesto.freeze_id
    assert relatorio.decisao_g2 == confirmatorio.g2
    assert sorted(relatorio.runs) == sorted(run.run_id for run in confirmatorio.runs)
    assert (tmp_path / "av" / f"{relatorio.report_id}.json").is_file()
    esquemas = {d.schema_id for run in confirmatorio.runs for d in run.entradas}
    assert "sigtap_procedimento.v1" in esquemas


def test_relatorio_traz_o_tamanho_do_estrato_de_cada_estabelecimento(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    relatorio = _avaliar(confirmatorio, tmp_path / "av")
    tamanhos = {
        m.estrato: m.numerador for m in relatorio.metricas if m.nome == "populacao.tamanho_estrato"
    }
    por_estabelecimento = {e: n for e, n in tamanhos.items() if e.startswith("estabelecimento=")}
    assert por_estabelecimento == {
        "estabelecimento=0000000": 8,
        "estabelecimento=0000001": 8,
        "estabelecimento=0000002": 7,
        "estabelecimento=0000003": 7,
    }
    assert sum(por_estabelecimento.values()) == tamanhos["TOTAL"]
    assert tamanhos["competencia=202401"] == tamanhos["instrumento=C"] == tamanhos["TOTAL"]


def _particao(conf: Confirmatorio, particao: Particao) -> Any:
    assert conf.cenario.split.particoes is not None
    return como_real(conf.cenario.split.particoes[particao])


def _divergencias(conf: Confirmatorio, raiz: Path) -> dict[str, Callable[[], dict[str, Any]]]:
    teste = conf.runs[M_TEMP].entradas[0]
    return {
        "commit_diferente": lambda: {"codigo": OUTRO_CODIGO},
        "codigo_sujo": lambda: {"codigo": CODIGO_LIMPO.model_copy(update={"sujo": True})},
        "config_diferente": lambda: {"config_hash": OUTRO_SHA},
        "catalogo_diferente": lambda: {"catalogo_regras_sha256": OUTRO_SHA},
        "catalogo_ausente": lambda: {"catalogo_regras_sha256": None},
        "politica_fora_do_congelamento": lambda: {"politica_id": "politica_inventada"},
        "politica_ausente": lambda: {"politica_id": None},
        "entrada_de_outro_conteudo": lambda: {
            "entradas": (teste.model_copy(update={"hash_logico": OUTRO_HASH}),)
        },
        "entrada_desconhecida_junto_da_valida": lambda: {
            "entradas": (teste, sia_pa_desconhecido(raiz))
        },
        "rotulos_de_outro_conteudo": lambda: {
            "entradas": (teste, conf.rotulos.model_copy(update={"hash_logico": OUTRO_HASH}))
        },
        "sem_entradas": lambda: {"entradas": ()},
        "so_a_particao_de_calibracao": lambda: {
            "entradas": (_particao(conf, Particao.CALIBRACAO),)
        },
        "so_a_particao_de_desenvolvimento": lambda: {
            "entradas": (_particao(conf, Particao.DESENVOLVIMENTO),)
        },
        "calibracao_com_rotulos_do_teste": lambda: {
            "entradas": (_particao(conf, Particao.CALIBRACAO), conf.rotulos)
        },
        "dataset_completo_sem_a_particao": lambda: {"entradas": (como_real(conf.cenario.dataset),)},
        "hash_do_teste_em_conjunto_de_outro_esquema": lambda: {
            "entradas": (teste.model_copy(update={"schema_id": "sigtap_procedimento.v1"}),)
        },
    }


CASOS = [
    ("commit_diferente", "codigo"),
    ("codigo_sujo", "codigo"),
    ("config_diferente", "config"),
    ("catalogo_diferente", "catalogo"),
    ("catalogo_ausente", "catalogo"),
    ("politica_fora_do_congelamento", "politica"),
    ("politica_ausente", "politica"),
    ("entrada_de_outro_conteudo", "entradas"),
    ("entrada_desconhecida_junto_da_valida", "entradas"),
    ("rotulos_de_outro_conteudo", "entradas"),
    ("sem_entradas", "entradas"),
    ("so_a_particao_de_calibracao", "entradas"),
    ("so_a_particao_de_desenvolvimento", "entradas"),
    ("calibracao_com_rotulos_do_teste", "entradas"),
    ("dataset_completo_sem_a_particao", "entradas"),
    ("hash_do_teste_em_conjunto_de_outro_esquema", "entradas"),
]


@pytest.mark.parametrize(("caso", "campo"), CASOS)
def test_execucao_com_o_mesmo_freeze_mas_identidade_diferente_e_recusada(
    tmp_path: Path, confirmatorio: Confirmatorio, caso: str, campo: str
) -> None:
    alvo = confirmatorio.runs[M_TEMP]
    trocas = _divergencias(confirmatorio, tmp_path)[caso]()
    runs = [alvo.model_copy(update=trocas), *confirmatorio.runs[1:]]
    with pytest.raises(PortaoRecusado, match=_mensagem(alvo, campo, confirmatorio)):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_baseline_ml_confere_codigo_mas_nao_exige_catalogo_nem_politica(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    baseline = confirmatorio.runs[B_ML]
    assert baseline.catalogo_regras_sha256 is None
    assert baseline.politica_id is None
    runs = [*confirmatorio.runs[:B_ML], baseline.model_copy(update={"codigo": OUTRO_CODIGO})]
    with pytest.raises(PortaoRecusado, match=_mensagem(baseline, "codigo", confirmatorio)):
        _avaliar(confirmatorio, tmp_path / "av", runs)


@pytest.mark.parametrize(
    ("faltam", "metodos"),
    [
        ([B_PROC], "B_PROC"),
        ([M_TEMP], "M_TEMP"),
        ([B_ATEND, B_PROC], "B_ATEND,B_PROC"),
        ([M_TEMP, B_ATEND, B_PROC], "B_ATEND,B_PROC,M_TEMP"),
    ],
)
def test_confirmatorio_sem_execucao_de_metodo_das_comparacoes_primarias_e_recusado(
    tmp_path: Path, confirmatorio: Confirmatorio, faltam: list[int], metodos: str
) -> None:
    runs = [run for indice, run in enumerate(confirmatorio.runs) if indice not in faltam]
    freeze = confirmatorio.manifesto.freeze_id
    mensagem = (
        f"avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias metodos={metodos} "
        f"freeze={freeze}"
    )
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(mensagem)}$"):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_confirmatorio_nao_exige_execucao_dos_metodos_secundarios(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    relatorio = _avaliar(confirmatorio, tmp_path / "av", confirmatorio.runs[:B_ML])
    assert len(relatorio.runs) == B_ML


@pytest.mark.parametrize("tipo", [TipoExecucao.PILOTO, TipoExecucao.AVALIACAO])
def test_so_o_baseline_dispensa_catalogo_e_politica(
    tmp_path: Path, confirmatorio: Confirmatorio, tipo: TipoExecucao
) -> None:
    alvo = confirmatorio.runs[M_TEMP]
    sem_regras = {"tipo": tipo, "catalogo_regras_sha256": None, "politica_id": None}
    runs = [alvo.model_copy(update=sem_regras), *confirmatorio.runs[1:]]
    with pytest.raises(PortaoRecusado, match=_mensagem(alvo, "catalogo,politica", confirmatorio)):
        _avaliar(confirmatorio, tmp_path / "av", runs)


def test_baseline_ajustado_no_confirmatorio_passa_na_conferencia_do_manifesto(
    tmp_path: Path, cenario: Cenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sustemporal.evaluation.baselines.versao_codigo", lambda _: CODIGO_LIMPO)
    runtime = {"dir_congelamentos": str(tmp_path / "frozen")}
    protocolo = RunConfig.model_validate({**CONFIG_PROTOCOLO, "runtime": runtime})
    real = split_como_real(cenario.split)
    conf = montar_confirmatorio(tmp_path, cenario, config=protocolo, split=real)
    config = config_confirmatoria(conf.manifesto.freeze_id, runtime=runtime)
    run = fit_baseline(
        real,
        FEATURES_PADRAO,
        config,
        tmp_path / "bml",
        decisoes=conf.decisoes,
        codigo=CODIGO_LIMPO,
    )
    assert run.tipo is TipoExecucao.BASELINE_ML
    verificar_execucao(conf.manifesto, run, config=config)


def _baseline_com(conf: Confirmatorio, particoes: tuple[Particao, ...]) -> RunResult:
    entradas = tuple(_particao(conf, particao) for particao in particoes)
    return conf.runs[B_ML].model_copy(update={"entradas": entradas})


def test_baseline_com_varias_particoes_passa_quando_inclui_a_de_teste(
    confirmatorio: Confirmatorio,
) -> None:
    todas = (Particao.DESENVOLVIMENTO, Particao.CALIBRACAO, Particao.TESTE)
    baseline = _baseline_com(confirmatorio, todas)
    verificar_execucao(confirmatorio.manifesto, baseline, config=confirmatorio.config)


@pytest.mark.parametrize(
    "particoes",
    [(Particao.DESENVOLVIMENTO, Particao.CALIBRACAO), (Particao.CALIBRACAO,)],
    ids=["treino_e_calibracao", "so_calibracao"],
)
def test_baseline_sem_a_particao_de_teste_e_recusado(
    confirmatorio: Confirmatorio, particoes: tuple[Particao, ...]
) -> None:
    baseline = _baseline_com(confirmatorio, particoes)
    with pytest.raises(PortaoRecusado, match=_mensagem(baseline, "entradas", confirmatorio)):
        verificar_execucao(confirmatorio.manifesto, baseline, config=confirmatorio.config)


@pytest.mark.parametrize(
    ("estado", "falhas"),
    [
        (EstadoExecucao.PARCIAL, 2),
        (EstadoExecucao.FALHOU, 1),
        (EstadoExecucao.PARCIAL, 0),
        (EstadoExecucao.CONCLUIDA, 1),
    ],
)
def test_confirmatorio_recusa_execucao_que_nao_concluiu_ou_tem_falhas(
    tmp_path: Path, confirmatorio: Confirmatorio, estado: EstadoExecucao, falhas: int
) -> None:
    alvo = confirmatorio.runs[B_PROC]
    incompleta = alvo.model_copy(update={"estado": estado, "falhas": falhas})
    runs = [*confirmatorio.runs[:B_PROC], incompleta, *confirmatorio.runs[B_PROC + 1 :]]
    mensagem = (
        f"execucao_incompleta_no_confirmatorio run={alvo.run_id} estado={estado.value} "
        f"falhas={falhas}"
    )
    with pytest.raises(PortaoRecusado, match=f"^{re.escape(mensagem)}$"):
        _avaliar(confirmatorio, tmp_path / "av", runs)
    assert not (tmp_path / "av").exists()


def test_divergencia_acusa_todos_os_campos_na_ordem_do_protocolo(
    tmp_path: Path, confirmatorio: Confirmatorio
) -> None:
    alvo = confirmatorio.runs[B_ATEND]
    trocas = {
        "codigo": OUTRO_CODIGO,
        "config_hash": OUTRO_SHA,
        "catalogo_regras_sha256": OUTRO_SHA,
        "politica_id": None,
        "entradas": (),
    }
    runs = [*confirmatorio.runs[:B_ATEND], alvo.model_copy(update=trocas), *confirmatorio.runs[2:]]
    campos = "codigo,config,catalogo,politica,entradas"
    with pytest.raises(PortaoRecusado, match=_mensagem(alvo, campos, confirmatorio)):
        _avaliar(confirmatorio, tmp_path / "av", runs)


def test_execucao_incompativel_e_recusada_antes_de_ler_qualquer_dado(tmp_path: Path) -> None:
    cenario = cenario_baseline(tmp_path / "cenario")
    conf = montar_confirmatorio(tmp_path, cenario)
    assert cenario.split.particoes is not None
    populacao = cenario.split.particoes[Particao.TESTE]
    saidas = [dataset for run in conf.runs for dataset in run.saidas]
    for dataset in (populacao, conf.rotulos, *saidas):
        Path(dataset.caminho).unlink()
    divergente = conf.runs[M_TEMP].model_copy(update={"codigo": OUTRO_CODIGO})
    with pytest.raises(PortaoRecusado, match="run_incompativel_com_congelamento"):
        _avaliar(conf, tmp_path / "av", [divergente, *conf.runs[1:]])


@pytest.mark.parametrize("trocas", [{"manifesto": None}, {"config": None}])
def test_confirmatorio_exige_o_manifesto_e_a_config_do_congelamento(
    tmp_path: Path, confirmatorio: Confirmatorio, trocas: dict[str, None]
) -> None:
    with pytest.raises(PortaoRecusado, match="avaliacao_confirmatoria_sem_manifesto_do_freeze"):
        _avaliar(confirmatorio, tmp_path / "av", **trocas)
    assert not (tmp_path / "av").exists()


def test_manifesto_de_outro_congelamento_e_recusado(
    tmp_path: Path, cenario: Cenario, confirmatorio: Confirmatorio
) -> None:
    outro_protocolo = RunConfig.model_validate({**CONFIG_PROTOCOLO, "semente": "7"})
    outro = montar_confirmatorio(tmp_path / "outro", cenario, config=outro_protocolo)
    assert outro.manifesto.freeze_id != confirmatorio.manifesto.freeze_id
    with pytest.raises(PortaoRecusado, match="avaliacao_confirmatoria_sem_manifesto_do_freeze"):
        _avaliar(confirmatorio, tmp_path / "av", manifesto=outro.manifesto)


def _config_de_outro_congelamento(caso: str, freeze: str) -> RunConfig:
    return {
        "protocolo_diferente": lambda: config_confirmatoria(freeze, semente="7"),
        "freeze_diferente": lambda: config_confirmatoria(OUTRO_FREEZE),
        "config_exploratoria": lambda: RunConfig.model_validate(
            {**CONFIG_PROTOCOLO, "freeze_id": freeze}
        ),
    }[caso]()


@pytest.mark.parametrize("caso", ["protocolo_diferente", "freeze_diferente", "config_exploratoria"])
def test_config_que_nao_abre_o_teste_do_congelamento_recusa_as_execucoes(
    tmp_path: Path, confirmatorio: Confirmatorio, caso: str
) -> None:
    config = _config_de_outro_congelamento(caso, confirmatorio.manifesto.freeze_id)
    feitas_com_ela = [
        run.model_copy(update={"config_hash": config.config_hash}) for run in confirmatorio.runs
    ]
    with pytest.raises(
        PortaoRecusado, match=_mensagem(feitas_com_ela[M_TEMP], "config", confirmatorio)
    ):
        _avaliar(confirmatorio, tmp_path / "av", feitas_com_ela, config=config)


def test_manifesto_sem_catalogo_e_politicas_recusa_validacao_mas_nao_baseline(
    tmp_path: Path, cenario: Cenario
) -> None:
    conf = montar_confirmatorio(tmp_path, cenario, regras=(), politicas=())
    assert conf.manifesto.catalogo_regras_sha256 is None
    assert conf.manifesto.politicas_sha256 is None
    with pytest.raises(PortaoRecusado, match="campo=catalogo,politica"):
        _avaliar(conf, tmp_path / "av")
    sem_identidade = {"catalogo_regras_sha256": None, "politica_id": None}
    runs = [conf.runs[M_TEMP].model_copy(update=sem_identidade), *conf.runs[1:]]
    with pytest.raises(PortaoRecusado, match="campo=catalogo,politica"):
        _avaliar(conf, tmp_path / "av", runs)
    verificar_execucao(conf.manifesto, conf.runs[B_ML], config=conf.config)


def test_congelamento_registra_a_identidade_do_catalogo_de_regras_e_das_politicas(
    confirmatorio: Confirmatorio,
) -> None:
    manifesto = confirmatorio.manifesto
    assert manifesto.catalogo_regras_sha256 == catalogo_sha256(carregar_regras())
    esperado = {
        politica.politica_id: hash_canonico(politica.model_dump(mode="json"))
        for politica in politicas_do_catalogo()
    }
    assert manifesto.politicas_sha256 == esperado
    assert set(esperado) == {"M_TEMP_PADRAO", "B_ATEND", "B_PROC"}


def test_congelamento_sem_regras_nem_politicas_nao_muda_a_identidade(
    tmp_path: Path, cenario: Cenario
) -> None:
    manifesto = montar_confirmatorio(tmp_path, cenario, regras=(), politicas=()).manifesto
    campos = conteudo_identidade(manifesto)["conteudo"]
    assert isinstance(campos, dict)
    assert "catalogo_regras_sha256" not in campos
    assert "politicas_sha256" not in campos
    assert FreezeManifest.model_validate_json(manifesto.model_dump_json()) == manifesto


def test_politica_repetida_com_conteudo_diferente_e_recusada(
    tmp_path: Path, cenario: Cenario
) -> None:
    original = carregar_politica("B_ATEND")
    alterada = original.model_copy(update={"criterios": original.criterios[:1]})
    with pytest.raises(ConfigInvalida, match="congelamento_politica_repetida politica=B_ATEND"):
        montar_confirmatorio(tmp_path, cenario, politicas=[original, alterada])
    montar_confirmatorio(tmp_path / "igual", cenario, politicas=[original, original])
