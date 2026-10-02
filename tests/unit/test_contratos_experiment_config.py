import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from sustemporal.contracts.annotation import AnnotationSample, Estrato
from sustemporal.contracts.base import (
    Confirmacao,
    DocRef,
    OrigemDados,
    Proveniencia,
    hash_canonico,
)
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.evaluation import EvaluationReport, IntervaloConfianca, ValorMetrica
from sustemporal.contracts.experiment import (
    A_DEFINIR,
    Ambiente,
    Atributo,
    BootstrapSpec,
    CodeVersion,
    CohortSpec,
    CorrecaoMultiplicidade,
    DecisaoPortao,
    EstadoExecucao,
    FeatureSpec,
    FreezeManifest,
    IntervaloParticao,
    ModoExecucao,
    MunicipioTerritorio,
    Particao,
    Portao,
    RunResult,
    SplitManifest,
    SplitSpec,
    Territorio,
    TipoExecucao,
)
from sustemporal.contracts.records import ColunaCanonica, EsquemaCanonico, PapelColuna
from sustemporal.contracts.temporal import CompetenciaAtendimento
from tests.fixtures.sintetico.contratos import (
    dataset_sintetico,
    features_sinteticas,
    split_sintetico,
)

_SHA = "a" * 64
_FREEZE = f"frz_{'b' * 64}"
_ART_A = f"art_{'a' * 64}"
_ART_B = f"art_{'b' * 64}"
_INSTANTE = datetime(2026, 9, 1, tzinfo=UTC)
_DES, _CAL, _TES = Particao.DESENVOLVIMENTO, Particao.CALIBRACAO, Particao.TESTE
_PLANO = ((_DES, "201801", "202212"), (_CAL, "202301", "202312"), (_TES, "202401", "202512"))
_HOLM = BootstrapSpec(correcao=CorrecaoMultiplicidade.HOLM)
_CHAVES = st.text(alphabet="abcdefgh_", min_size=1, max_size=6)
_EXPLORATORIO = {
    "modo": ModoExecucao.EXPLORATORIO,
    "origem_dados": OrigemDados.SINTETICO,
    "freeze_id": None,
}
_DECISOES = {
    Portao.G0: ("CONTINUAR", "AMPLIAR_SP", "RESTRINGIR_FAMILIAS", "REFORMULAR"),
    Portao.G1: ("APROVADO", "REPROVADO"),
    Portao.G2: ("ABRIR_TESTE", "ADIAR"),
}
_VALIDAS = [(portao, d) for portao, decisoes in _DECISOES.items() for d in decisoes]
_DE_OUTRO_PORTAO = [(p, d) for p in Portao for q, ds in _DECISOES.items() if q is not p for d in ds]


def _split(*intervalos: tuple[Particao, str, str]) -> SplitSpec:
    escolhidos = intervalos or _PLANO
    return SplitSpec(
        intervalos=tuple(IntervaloParticao(particao=p, inicio=i, fim=f) for p, i, f in escolhidos)
    )


def _docref() -> DocRef:
    return DocRef(doc_id="lista_drs", titulo="DRS XI", estado="PENDENTE", proveniencia="SECUNDARIA")


def _codigo(sujo: bool = False) -> CodeVersion:
    return CodeVersion(commit="abc123", sujo=sujo, versao_pacote="0.1.0")


def _ambiente(**campos: object) -> Ambiente:
    return Ambiente.model_validate({"python": "3.12.7", "plataforma": "linux"} | campos)


def _esquema() -> EsquemaCanonico:
    papeis = {
        "row_id": PapelColuna.CHAVE,
        "idade": PapelColuna.ATRIBUTO,
        "pa_indica": PapelColuna.ROTULO,
        "qtd_aprovada": PapelColuna.DIAGNOSTICO,
        "motivo_glosa": PapelColuna.DIAGNOSTICO,
    }
    colunas = tuple(
        ColunaCanonica(nome=nome, tipo="TEXTO", papel=papel, anulavel=papel != "CHAVE")
        for nome, papel in papeis.items()
    )
    return EsquemaCanonico(schema_id="sia_pa.v1", descricao="", chave=("row_id",), colunas=colunas)


def _features(
    *colunas: str, schema_id: str = "sia_pa.v1", transformacao: str = "id"
) -> FeatureSpec:
    atributos = tuple(
        Atributo(nome=f"f_{c}", schema_id=schema_id, coluna=c, transformacao=transformacao)
        for c in colunas
    )
    return FeatureSpec(feature_set_id="fs_1", atributos=atributos)


def _run_result(**campos: object) -> RunResult:
    base = {
        "run_id": "run_1",
        "tipo": TipoExecucao.VALIDACAO,
        "modo": ModoExecucao.CONFIRMATORIO,
        "config_hash": _SHA,
        "codigo": _codigo(),
        "ambiente": _ambiente(),
        "estado": EstadoExecucao.CONCLUIDA,
        "iniciado_em": _INSTANTE,
        "freeze_id": _FREEZE,
        "origem_dados": OrigemDados.REAL,
    }
    return RunResult.model_validate(base | campos)


def _campos_freeze(**campos: object) -> dict[str, object]:
    base = {
        "criado_em": _INSTANTE,
        "config_hash": _SHA,
        "codigo": _codigo(),
        "ambiente": _ambiente(),
        "catalogos_sha256": {"regras": _SHA},
        "datasets": (dataset_sintetico(),),
        "split": split_sintetico(),
        "features": features_sinteticas(),
        "bootstrap": _HOLM,
        "metricas": ("cobertura_rejeicoes",),
        "comparacoes_primarias": ("M_TEMP_x_B_ATEND", "M_TEMP_x_B_PROC"),
        "margens": {"M_TEMP_x_B_ATEND": "0.05"},
        "decisao_g0": "experiments/decisions/G0.yaml",
    }
    return base | campos


def _decisao(portao: Portao, decisao: str, **campos: object) -> DecisaoPortao:
    base = {
        "portao": portao,
        "decisao": decisao,
        "data": "2026-11-30",
        "responsaveis": ("pesquisador",),
        "registrado_por_humano": True,
        "freeze_id": _FREEZE,
    }
    return DecisaoPortao.model_validate(base | campos)


def _coorte() -> CohortSpec:
    return CohortSpec(
        cohort_id="drs_xi", uf="SP", territorio="drs_xi", inicio="201801", fim="202512"
    )


def _run_config(**campos: object) -> RunConfig:
    base = {
        "versao": "1",
        "modo": ModoExecucao.CONFIRMATORIO,
        "origem_dados": OrigemDados.REAL,
        "freeze_id": _FREEZE,
        "bootstrap": _HOLM,
    }
    return RunConfig.model_validate(base | campos)


def _municipio(ibge7: str = "3541406", ibge6: str = "354140") -> MunicipioTerritorio:
    return MunicipioTerritorio(ibge7=ibge7, ibge6=ibge6, nome="Municipio", regiao="DRS XI")


def _territorio(**campos: object) -> Territorio:
    base = {
        "territorio_id": "drs_xi",
        "descricao": "DRS XI",
        "uf": "SP",
        "municipios": (_municipio(), _municipio("3541307", "354130")),
        "proveniencia": Proveniencia.SECUNDARIA,
        "confirmacao": Confirmacao.A_CONFIRMAR,
        "fontes": (_docref(),),
    }
    return Territorio.model_validate(base | campos)


def _relatorio(**campos: object) -> EvaluationReport:
    base = {
        "report_id": "rel_1",
        "modo": ModoExecucao.EXPLORATORIO,
        "origem_dados": OrigemDados.SINTETICO,
        "criado_em": _INSTANTE,
    }
    return EvaluationReport.model_validate(base | campos)


def _metrica(**campos: object) -> ValorMetrica:
    base = {"nome": "cobertura_rejeicoes", "numerador": 0, "denominador": 0}
    return ValorMetrica.model_validate(base | campos)


def _amostra(**campos: object) -> AnnotationSample:
    estrato = Estrato(nome="BPA_I", populacao=100, amostra=2, prob_inclusao="0.02")
    base = {
        "sample_id": "amostra_1",
        "semente": 2027,
        "estratos": (estrato,),
        "casos": (f"{_ART_A}#1", f"{_ART_A}#2"),
        "formulario_versao": "1",
    }
    return AnnotationSample.model_validate(base | campos)


@pytest.mark.parametrize(
    "intervalos",
    [
        ((_DES, "201801", "202301"), (_CAL, "202301", "202312"), (_TES, "202401", "202512")),
        ((_CAL, "202301", "202312"), (_DES, "201801", "202212"), (_TES, "202401", "202512")),
    ],
)
def test_particoes_rejeitam_sobreposicao_ou_ordem_cronologica_invertida(intervalos: tuple) -> None:
    with pytest.raises(ValidationError, match="particoes_"):
        _split(*intervalos)


def test_particoes_rejeitam_intervalo_invertido() -> None:
    with pytest.raises(ValidationError, match="particao_invertida"):
        _split((_DES, "202212", "201801"), (_CAL, "202301", "202312"), (_TES, "202401", "202512"))


@pytest.mark.parametrize(
    "intervalos",
    [
        ((_DES, "201801", "202212"), (_TES, "202401", "202512")),
        ((_DES, "201801", "202212"), (_TES, "202301", "202312"), (_TES, "202401", "202512")),
    ],
)
def test_particoes_aparecem_uma_vez_cada(intervalos: tuple) -> None:
    with pytest.raises(ValidationError, match="particoes_fora_da_ordem"):
        _split(*intervalos)


def test_particoes_do_plano_usam_competencia_de_processamento() -> None:
    assert [i.particao for i in _split().intervalos] == [_DES, _CAL, _TES]
    with pytest.raises(ValidationError, match="tempo_incompativel"):
        IntervaloParticao(particao=_DES, inicio=CompetenciaAtendimento("201801"), fim="202212")
    with pytest.raises(ValidationError):
        SplitSpec(base_temporal="ATENDIMENTO", intervalos=_split().intervalos)


def test_particao_de_teste_nao_precede_desenvolvimento() -> None:
    with pytest.raises(ValidationError):
        _split((_TES, "201801", "202212"), (_CAL, "202301", "202312"), (_DES, "202401", "202512"))


def test_manifesto_rejeita_artefato_de_teste_ja_inspecionado() -> None:
    campos = {"split_id": "split_1", "spec": _split(), "dataset_hash": f"lh1:{_SHA}"}
    contagens = {
        "linhas_por_particao": dict.fromkeys(Particao, 1),
        "hash_por_particao": dict.fromkeys(Particao, f"lh1:{_SHA}"),
    }
    disjunto = SplitManifest(**campos, **contagens, artefatos_teste=(_ART_A,))
    assert disjunto.artefatos_teste == (_ART_A,)
    with pytest.raises(ValidationError, match="teste_contem_artefato_inspecionado"):
        SplitManifest(
            **campos,
            **contagens,
            artefatos_inspecionados=(_ART_A,),
            artefatos_teste=(_ART_A, _ART_B),
        )


def test_colunas_proibidas_sinaliza_tudo_que_nao_e_atributo() -> None:
    features = _features("idade", "qtd_aprovada", "motivo_glosa", "row_id", "nova")
    proibidas = ("qtd_aprovada", "motivo_glosa", "row_id", "nova")
    assert features.colunas_proibidas(_esquema()) == proibidas
    assert _features("idade").colunas_proibidas(_esquema()) == ()


def test_colunas_proibidas_avalia_apenas_atributos_do_esquema_informado() -> None:
    assert _features("motivo_glosa", schema_id="cnes_pf.v1").colunas_proibidas(_esquema()) == ()


@pytest.mark.parametrize(
    "campos",
    [{"freeze_id": None}, {"codigo": _codigo(sujo=True)}, {"origem_dados": OrigemDados.SINTETICO}],
)
def test_execucao_confirmatoria_exige_freeze_codigo_limpo_e_dados_reais(
    campos: dict[str, object],
) -> None:
    assert _run_result().modo is ModoExecucao.CONFIRMATORIO
    with pytest.raises(ValidationError, match="execucao_confirmatoria_invalida"):
        _run_result(**campos)


def test_execucao_exploratoria_dispensa_congelamento() -> None:
    assert _run_result(codigo=_codigo(sujo=True), **_EXPLORATORIO).freeze_id is None
    with pytest.raises(ValidationError):
        _run_result(freeze_id="frz_curto")


def test_freeze_id_e_derivado_do_conteudo_e_estavel() -> None:
    congelamento = FreezeManifest.criar(**_campos_freeze())
    conteudo = congelamento.model_dump(mode="json", exclude={"freeze_id"}, exclude_none=True)
    assert congelamento.freeze_id == f"frz_{hash_canonico({'v': 1, 'conteudo': conteudo})}"
    assert FreezeManifest.model_validate_json(congelamento.model_dump_json()) == congelamento
    adulterado = congelamento.model_dump() | {"metricas": ("outra_metrica",)}
    with pytest.raises(ValidationError, match="freeze_id_nao_corresponde_ao_conteudo"):
        FreezeManifest.model_validate(adulterado)


@pytest.mark.parametrize("freeze_id", [f"frz_{'0' * 64}", "frz_provisorio"])
def test_congelamento_rejeita_id_que_nao_deriva_do_conteudo(freeze_id: str) -> None:
    with pytest.raises(ValidationError, match="freeze_id_nao_corresponde_ao_conteudo"):
        FreezeManifest.model_validate(_campos_freeze(freeze_id=freeze_id))


@pytest.mark.parametrize(
    "campos",
    [
        {"comparacoes_primarias": (A_DEFINIR,)},
        {"metricas": ("cobertura", A_DEFINIR)},
        {"bootstrap": BootstrapSpec()},
        {"ambiente": _ambiente(pacotes={"duckdb": A_DEFINIR})},
        {"features": _features("idade", transformacao=A_DEFINIR)},
    ],
)
def test_congelamento_rejeita_a_definir_em_qualquer_nivel(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="congelamento_com_valor_a_definir"):
        FreezeManifest.criar(**_campos_freeze(**campos))


def test_congelamento_rejeita_a_definir_em_chave_de_dicionario() -> None:
    with pytest.raises(ValidationError, match="congelamento_com_valor_a_definir"):
        FreezeManifest.criar(**_campos_freeze(margens={A_DEFINIR: "0.05"}))


@pytest.mark.parametrize(("portao", "decisao"), _VALIDAS)
def test_decisao_valida_do_portao_e_aceita(portao: Portao, decisao: str) -> None:
    familias = ("PROCEDIMENTO_CBO",) if decisao == "RESTRINGIR_FAMILIAS" else ()
    assert _decisao(portao, decisao, familias_aprovadas=familias).decisao == decisao


@pytest.mark.parametrize(
    ("portao", "decisao"), [*_DE_OUTRO_PORTAO, (Portao.G1, "aprovado"), (Portao.G0, "")]
)
def test_decisao_de_outro_portao_ou_desconhecida_e_rejeitada(portao: Portao, decisao: str) -> None:
    with pytest.raises(ValidationError, match="decisao_invalida"):
        _decisao(portao, decisao)


@pytest.mark.parametrize("valor", [False, "false", None])
def test_decisao_exige_registro_por_humano(valor: object) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G1, "APROVADO", registrado_por_humano=valor)


def test_decisao_g2_exige_freeze_id() -> None:
    assert _decisao(Portao.G0, "CONTINUAR", freeze_id=None).freeze_id is None
    with pytest.raises(ValidationError, match="decisao_g2_exige_freeze_id"):
        _decisao(Portao.G2, "ABRIR_TESTE", freeze_id=None)


@pytest.mark.parametrize("responsaveis", [(), ("",)])
def test_decisao_exige_responsavel(responsaveis: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        _decisao(Portao.G1, "APROVADO", responsaveis=responsaveis)


def test_config_confirmatoria_exige_freeze_id() -> None:
    assert _run_config().freeze_id == _FREEZE
    with pytest.raises(ValidationError, match="confirmatorio_exige_freeze_id"):
        _run_config(freeze_id=None)


@pytest.mark.parametrize("origem", [OrigemDados.SINTETICO, None])
def test_config_confirmatoria_exige_dados_reais(origem: OrigemDados | None) -> None:
    with pytest.raises(ValidationError, match="confirmatorio_exige_dados_reais"):
        _run_config(origem_dados=origem)


@pytest.mark.parametrize(
    "campos",
    [
        {"bootstrap": BootstrapSpec()},
        {"coorte": _coorte()},
        {"catalogos": {"regras": A_DEFINIR}},
        {"politica_id": A_DEFINIR},
    ],
)
def test_config_confirmatoria_rejeita_a_definir(campos: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="confirmatorio_com_valor_a_definir"):
        _run_config(**campos)


def test_config_exploratoria_aceita_valores_a_definir() -> None:
    config = _run_config(bootstrap=BootstrapSpec(), coorte=_coorte(), **_EXPLORATORIO)
    assert config.bootstrap.correcao is CorrecaoMultiplicidade.A_DEFINIR


@given(st.dictionaries(_CHAVES, _CHAVES, max_size=5))
def test_config_hash_independe_da_ordem_dos_catalogos(catalogos: dict[str, str]) -> None:
    invertidos = dict(reversed(list(catalogos.items())))
    config = _run_config(catalogos=catalogos)
    assert _run_config(catalogos=invertidos).config_hash == config.config_hash
    assert RunConfig.model_validate_json(config.model_dump_json()).config_hash == config.config_hash
    assert re.fullmatch(r"[0-9a-f]{64}", config.config_hash)


def test_config_hash_muda_com_a_configuracao() -> None:
    assert _run_config(semente=7).config_hash != _run_config().config_hash


def test_config_confirmatoria_rejeita_freeze_id_vazio() -> None:
    with pytest.raises(ValidationError):
        _run_config(freeze_id="")


def test_municipio_exige_ibge6_prefixo_do_ibge7() -> None:
    assert _municipio().ibge6 == "354140"
    with pytest.raises(ValidationError, match="ibge6_nao_e_prefixo_do_ibge7"):
        _municipio("3541406", "354130")
    with pytest.raises(ValidationError):
        MunicipioTerritorio(ibge7=3541406, ibge6="354140", nome="M", regiao="R")


@pytest.mark.parametrize(
    "campos", [{"municipios": ()}, {"municipios": (_municipio(), _municipio())}, {"fontes": ()}]
)
def test_territorio_exige_municipios_unicos_e_fonte(campos: dict[str, object]) -> None:
    assert len(_territorio().municipios) == 2
    erro = r"territorio_municipios_vazios_ou_repetidos|too_short"
    with pytest.raises(ValidationError, match=erro):
        _territorio(**campos)


def test_relatorio_sintetico_nao_pode_ser_confirmatorio() -> None:
    assert _relatorio().origem_dados is OrigemDados.SINTETICO
    with pytest.raises(ValidationError, match="relatorio_sintetico_confirmatorio"):
        _relatorio(modo=ModoExecucao.CONFIRMATORIO, freeze_id=_FREEZE, decisao_g2="G2.yaml")


@pytest.mark.parametrize("campos", [{"freeze_id": None}, {"decisao_g2": None}, {"freeze_id": ""}])
def test_relatorio_confirmatorio_exige_freeze_e_decisao_g2(campos: dict[str, object]) -> None:
    confirmatorio = {"modo": ModoExecucao.CONFIRMATORIO, "origem_dados": OrigemDados.REAL}
    completo = confirmatorio | {"freeze_id": _FREEZE, "decisao_g2": "G2.yaml"}
    assert _relatorio(**completo).modo is ModoExecucao.CONFIRMATORIO
    with pytest.raises(ValidationError, match=r"relatorio_confirmatorio_sem_freeze_ou_g2|frz_"):
        _relatorio(**(completo | campos))


def test_metrica_com_denominador_zero_nao_tem_valor() -> None:
    assert _metrica().valor is None
    with pytest.raises(ValidationError, match="metrica_com_denominador_zero"):
        _metrica(valor="0")


def test_metrica_com_denominador_positivo_exige_valor_decimal() -> None:
    assert _metrica(numerador=1, denominador=4, valor="0.25").valor == Decimal("0.25")
    with pytest.raises(ValidationError, match="metrica_sem_valor"):
        _metrica(numerador=1, denominador=4)
    with pytest.raises(ValidationError):
        _metrica(numerador=1, denominador=4, valor=0.25)
    with pytest.raises(ValidationError, match="intervalo_invertido"):
        IntervaloConfianca(inferior="0.3", superior="0.2")


def test_amostra_exclui_casos_de_treino_e_repetidos() -> None:
    assert _amostra(casos_treino=(f"{_ART_A}#9",)).casos_treino == (f"{_ART_A}#9",)
    with pytest.raises(ValidationError, match="caso_de_treino_na_amostra_final"):
        _amostra(casos_treino=(f"{_ART_A}#1",))
    with pytest.raises(ValidationError, match="caso_repetido"):
        _amostra(casos=(f"{_ART_A}#1", f"{_ART_A}#1"))


@pytest.mark.parametrize(
    "campos", [{"amostra": 101}, {"prob_inclusao": "0"}, {"prob_inclusao": "1.01"}]
)
def test_estrato_rejeita_amostra_ou_probabilidade_invalida(campos: dict[str, object]) -> None:
    base = {"nome": "BPA_I", "populacao": 100, "amostra": 10, "prob_inclusao": "0.1"}
    with pytest.raises(ValidationError, match="estrato_"):
        Estrato.model_validate(base | campos)
