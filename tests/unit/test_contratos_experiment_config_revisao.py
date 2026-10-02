"""Protocolo: decisões de portão, partições, congelamento, atributos, execuções e amostras."""

from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from sustemporal.contracts import experiment
from sustemporal.contracts.annotation import Estrato
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import (
    A_DEFINIR,
    EstadoExecucao,
    FreezeManifest,
    Particao,
    Portao,
    SplitManifest,
)
from sustemporal.contracts.records import DatasetRef, EsquemaCanonico, PapelColuna
from sustemporal.contracts.rules import FamiliaRegra
from tests.fixtures.sintetico.contratos import dataset_sintetico, split_sintetico
from tests.unit.test_contratos_experiment_config import (
    _ART_A,
    _EXPLORATORIO,
    _FREEZE,
    _INSTANTE,
    _amostra,
    _campos_freeze,
    _codigo,
    _decisao,
    _esquema,
    _features,
    _relatorio,
    _run_config,
    _run_result,
    _split,
)

RAIZ = Path(__file__).resolve().parents[2]
_HASH = f"lh1:{'c' * 64}"
_LINHAS = dict.fromkeys(Particao, 1)
_HASHES = dict.fromkeys(Particao, _HASH)
_ESQUEMAS_DO_CATALOGO = [
    EsquemaCanonico.de_yaml(caminho)
    for caminho in sorted((RAIZ / "catalog/schemas").glob("*.yaml"))
]
_TRECHOS_DE_ERRO_OU_APROVACAO = (
    "indica",
    "rotulo",
    "contradic",
    "codoco",
    "flqt",
    "fler",
    "flidade",
    "aprovad",
)
_PAPEIS_FORA_DA_LISTA_POSITIVA = {PapelColuna.DIAGNOSTICO, PapelColuna.BRUTO, PapelColuna.MOTIVO}
_PILOTO = {
    "competencias_processamento": ("201801", "202212"),
    "territorio": "t",
    "familias_fontes": (),
}
_COORTE = {
    "cohort_id": "drs_xi",
    "uf": "SP",
    "territorio": "t",
    "inicio": "201801",
    "fim": "202512",
}


class _CongelamentoComCampoNovo(FreezeManifest):
    x: str | None = None


class _ConfigComCampoNovo(RunConfig):
    x: str | None = None


def _manifesto(**campos: object) -> SplitManifest:
    base = {
        "split_id": "split_1",
        "spec": _split(),
        "dataset_hash": _HASH,
        "linhas_por_particao": _LINHAS,
        "hash_por_particao": _HASHES,
    }
    return SplitManifest.model_validate(base | campos)


@pytest.mark.parametrize(
    "referencia", ["", "   ", "G0.yaml", "experiments/decisions/G0.txt", A_DEFINIR]
)
def test_congelamento_exige_decisao_g0_em_experiments_decisions(referencia: str) -> None:
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        FreezeManifest.criar(**_campos_freeze(decisao_g0=referencia))


def test_decisao_com_data_numerica_e_recusada() -> None:
    assert _decisao(Portao.G0, "CONTINUAR").data.isoformat() == "2026-11-30"
    with pytest.raises(ValidationError, match="data_exige_date_ou_iso"):
        _decisao(Portao.G0, "CONTINUAR", data=0)


def test_restringir_familias_exige_familias_aprovadas() -> None:
    aprovada = _decisao(Portao.G0, "RESTRINGIR_FAMILIAS", familias_aprovadas=("PROCEDIMENTO_CBO",))
    assert aprovada.familias_aprovadas[0] is FamiliaRegra.PROCEDIMENTO_CBO
    with pytest.raises(ValidationError, match="decisao_restringir_familias_sem_familias"):
        _decisao(Portao.G0, "RESTRINGIR_FAMILIAS")


@pytest.mark.parametrize("familias", [("FAMILIA_INVENTADA",), ("procedimento_cbo",), ("",)])
def test_familias_aprovadas_so_aceitam_familias_de_regra(familias: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G0, "RESTRINGIR_FAMILIAS", familias_aprovadas=familias)


@pytest.mark.parametrize("responsaveis", [(" ",), ("pesquisador", "\t"), ("\n",)])
def test_decisao_rejeita_responsavel_em_branco(responsaveis: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G1, "APROVADO", responsaveis=responsaveis)


@pytest.mark.parametrize("ausente", list(Particao))
@pytest.mark.parametrize("campo", ["linhas_por_particao", "hash_por_particao"])
def test_manifesto_exige_contagem_e_hash_de_cada_particao_declarada(
    ausente: Particao, campo: str
) -> None:
    assert _manifesto().linhas_por_particao == _LINHAS
    completo = _LINHAS if campo == "linhas_por_particao" else _HASHES
    incompleto = {
        particao: valor for particao, valor in completo.items() if particao is not ausente
    }
    with pytest.raises(ValidationError, match="split_manifesto_particoes_divergentes"):
        _manifesto(**{campo: incompleto})


def test_campo_opcional_novo_nao_muda_o_freeze_id() -> None:
    original = FreezeManifest.criar(**_campos_freeze())
    assert _CongelamentoComCampoNovo.criar(**_campos_freeze()).freeze_id == original.freeze_id


def test_campo_opcional_novo_nao_muda_o_config_hash() -> None:
    campos = {"versao": "1", "semente": 7}
    novo = _ConfigComCampoNovo.model_validate(campos)
    assert novo.config_hash == RunConfig.model_validate(campos).config_hash


def test_lista_negativa_cobre_rotulos_e_diagnosticos_de_erro_e_aprovacao_do_catalogo() -> None:
    proibidas = getattr(experiment, "COLUNAS_PROIBIDAS_EM_ATRIBUTOS", frozenset())
    colunas = [coluna for esquema in _ESQUEMAS_DO_CATALOGO for coluna in esquema.colunas]
    esperadas = {
        coluna.nome
        for coluna in colunas
        if coluna.papel is PapelColuna.ROTULO
        or (
            coluna.papel in _PAPEIS_FORA_DA_LISTA_POSITIVA
            and any(trecho in coluna.nome for trecho in _TRECHOS_DE_ERRO_OU_APROVACAO)
        )
    }
    exemplos = {"pa_indica", "pa_codoco", "pa_flqt", "pa_fler", "quantidade_aprovada"}
    assert exemplos | {"valor_aprovado", "rotulo"} <= esperadas
    assert esperadas <= proibidas
    atributos = {coluna.nome for coluna in colunas if coluna.papel is PapelColuna.ATRIBUTO}
    assert not proibidas & atributos


@pytest.mark.parametrize(
    "coluna",
    [
        "pa_indica",
        "PA_INDICA",
        "pa_codoco",
        "quantidade_aprovada",
        "valor_aprovado_bruto",
        "rotulo",
    ],
)
def test_feature_spec_recusa_rotulo_e_campos_de_erro_ou_aprovacao(coluna: str) -> None:
    with pytest.raises(ValidationError, match="feature_com_coluna_proibida"):
        _features(coluna)


@pytest.mark.parametrize(
    ("features", "erro"),
    [
        (_features("qtd_aprovada"), "feature_coluna_nao_atributo"),
        (_features("row_id"), "feature_coluna_nao_atributo"),
        (_features("inexistente"), "feature_coluna_nao_atributo"),
        (_features("idade", schema_id="cnes_pf.v1"), "feature_sem_esquema"),
    ],
)
def test_validar_features_exige_coluna_atributo_do_esquema(
    features: experiment.FeatureSpec, erro: str
) -> None:
    validar = getattr(experiment, "validar_features", None)
    assert validar is not None
    assert validar(_features("idade"), [_esquema()]) is None
    with pytest.raises(ValueError, match=erro):
        validar(features, [_esquema()])


@pytest.mark.parametrize(
    "campos",
    [
        {"datasets": ()},
        {"metricas": ()},
        {"comparacoes_primarias": ()},
        {"catalogos_sha256": {}},
        {"split": None},
        {"features": None},
    ],
)
def test_congelamento_exige_insumos_do_protocolo(campos: dict[str, object]) -> None:
    assert FreezeManifest.criar(**_campos_freeze()).split is not None
    with pytest.raises(ValidationError):
        FreezeManifest.criar(**_campos_freeze(**campos))


def test_congelamento_recusa_codigo_sujo() -> None:
    with pytest.raises(ValidationError, match="congelamento_com_codigo_sujo"):
        FreezeManifest.criar(**_campos_freeze(codigo=_codigo(sujo=True)))


def test_config_confirmatoria_exige_rede_desligada() -> None:
    assert _run_config().runtime.rede_permitida is False
    with pytest.raises(ValidationError, match="confirmatorio_exige_rede_desligada"):
        _run_config(runtime={"rede_permitida": True})


def test_piloto_fica_dentro_da_particao_de_desenvolvimento() -> None:
    assert _run_config(piloto=_PILOTO, particoes=_split(), **_EXPLORATORIO).piloto is not None
    fora = _PILOTO | {"competencias_processamento": ("201801", "202301")}
    with pytest.raises(ValidationError, match="piloto_fora_do_desenvolvimento"):
        _run_config(piloto=fora, particoes=_split(), **_EXPLORATORIO)


@pytest.mark.parametrize(("inicio", "fim"), [("201901", "202512"), ("201801", "202412")])
def test_particoes_ficam_dentro_do_intervalo_da_coorte(inicio: str, fim: str) -> None:
    assert _run_config(coorte=_COORTE, particoes=_split(), **_EXPLORATORIO).coorte is not None
    coorte = _COORTE | {"inicio": inicio, "fim": fim}
    with pytest.raises(ValidationError, match="particoes_fora_da_coorte"):
        _run_config(coorte=coorte, particoes=_split(), **_EXPLORATORIO)


def test_execucao_concluida_nao_tem_falhas() -> None:
    assert _run_result(falhas=2, estado=EstadoExecucao.PARCIAL).falhas == 2
    with pytest.raises(ValidationError, match="execucao_concluida_com_falhas"):
        _run_result(falhas=1)


def test_execucao_nao_conclui_antes_de_iniciar() -> None:
    assert _run_result(concluido_em=_INSTANTE).concluido_em == _INSTANTE
    with pytest.raises(ValidationError, match="execucao_conclusao_antes_do_inicio"):
        _run_result(concluido_em=_INSTANTE - timedelta(seconds=1))


def test_amostra_exige_soma_dos_estratos_igual_ao_numero_de_casos() -> None:
    with pytest.raises(ValidationError, match="amostra_estratos_divergem_dos_casos"):
        _amostra(casos=(f"{_ART_A}#1",))


def test_amostra_recusa_estrato_repetido() -> None:
    estrato = Estrato(nome="BPA_I", populacao=100, amostra=1, prob_inclusao="0.01")
    with pytest.raises(ValidationError, match="estrato_repetido"):
        _amostra(estratos=(estrato, estrato))


@pytest.mark.parametrize(
    "campos",
    [
        {"dataset_hash": "x"},
        {"dataset_hash": "a" * 64},
        {"hash_por_particao": dict.fromkeys(Particao, "nao-e-hash")},
    ],
)
def test_split_manifest_exige_hashes_logicos(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _manifesto(**campos)


def test_congelamento_exige_split_de_um_dataset_congelado() -> None:
    outro = split_sintetico().model_dump() | {"dataset_hash": f"lh1:{'e' * 64}"}
    with pytest.raises(ValidationError, match="congelamento_split_de_outro_dataset"):
        FreezeManifest.criar(**_campos_freeze(split=SplitManifest.model_validate(outro)))


def test_execucao_exige_datasets_da_mesma_origem() -> None:
    real = dataset_sintetico()
    sintetico = DatasetRef.model_validate(real.model_dump() | {"origem_dados": "SINTETICO"})
    with pytest.raises(ValidationError, match="execucao_com_dataset_de_outra_origem"):
        _run_result(entradas=(sintetico,))
    with pytest.raises(ValidationError, match="execucao_com_dataset_de_outra_origem"):
        _run_result(
            modo="EXPLORATORIO", origem_dados=OrigemDados.SINTETICO, freeze_id=None, saidas=(real,)
        )


_CONFIRMATORIO_REAL = {
    "modo": "CONFIRMATORIO",
    "origem_dados": OrigemDados.REAL,
    "freeze_id": _FREEZE,
    "decisao_g2": "experiments/decisions/G2.yaml",
}


def test_relatorio_exige_tabelas_da_mesma_origem() -> None:
    real = dataset_sintetico()
    sintetica = DatasetRef.model_validate(real.model_dump() | {"origem_dados": "SINTETICO"})
    assert _relatorio(**_CONFIRMATORIO_REAL, tabelas=(real,)).tabelas == (real,)
    with pytest.raises(ValidationError, match="relatorio_com_tabela_de_outra_origem"):
        _relatorio(**_CONFIRMATORIO_REAL, tabelas=(sintetica,))


@pytest.mark.parametrize("decisao", ["inventada", "G2.yaml", "experiments/decisions/../g2.yaml"])
def test_relatorio_confirmatorio_exige_referencia_de_decisao(decisao: str) -> None:
    with pytest.raises(ValidationError):
        _relatorio(**(_CONFIRMATORIO_REAL | {"decisao_g2": decisao}))


@pytest.mark.parametrize(
    ("populacao", "amostra", "prob"), [(100, 10, "1"), (100, 10, "0.2"), (0, 0, "1")]
)
def test_estrato_exige_probabilidade_igual_a_fracao_amostral(
    populacao: int, amostra: int, prob: str
) -> None:
    with pytest.raises(ValidationError, match="estrato_"):
        Estrato(nome="E", populacao=populacao, amostra=amostra, prob_inclusao=prob)


def test_estrato_aceita_fracao_amostral_na_escala_da_probabilidade() -> None:
    assert Estrato(nome="E", populacao=3, amostra=1, prob_inclusao="0.3333").amostra == 1
