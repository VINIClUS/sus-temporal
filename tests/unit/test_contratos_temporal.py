import operator
from collections.abc import Callable
from datetime import UTC, date, datetime
from itertools import permutations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from sustemporal.contracts.base import DocRef, FamiliaFonte, hash_canonico
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CompetenciaAtendimento,
    CompetenciaProcessamento,
    CriterioTemporal,
    EstadoSelecao,
    MetodoId,
    PoliticaTemporal,
    SelecaoVersao,
    SnapshotSet,
    TipoPolitica,
    TipoTempo,
    VigenciaDocumentada,
)

_TIPOS = (CompetenciaAtendimento, CompetenciaProcessamento, CompetenciaArquivo)
_PARES_DE_TIPOS = list(permutations(_TIPOS, 2))
_COMPETENCIAS = st.builds(
    lambda ano, mes: f"{ano:04d}{mes:02d}", st.integers(1900, 2100), st.integers(1, 12)
)
_A = f"art_{'a' * 64}"
_B = f"art_{'b' * 64}"
_C = f"art_{'c' * 64}"


def _docref(estado: str = "PENDENTE") -> DocRef:
    sha256 = "e" * 64 if estado == "PRESERVADO" else None
    return DocRef(
        doc_id="portaria_sas",
        titulo="Portaria",
        estado=estado,
        sha256=sha256,
        proveniencia="OFICIAL_DOCUMENTO",
    )


def _criterio(**campos: object) -> CriterioTemporal:
    base = {"fonte": FamiliaFonte.CNES_PF, "base": BaseTemporal.PROCESSAMENTO}
    return CriterioTemporal.model_validate(base | campos)


def _politica(**campos: object) -> PoliticaTemporal:
    base = {
        "politica_id": "pol_documentada",
        "tipo": TipoPolitica.DOCUMENTADA,
        "metodo": MetodoId.M_TEMP,
        "criterios": (_criterio(),),
        "documento": _docref(),
    }
    return PoliticaTemporal.model_validate(base | campos)


def _selecao(
    estado: EstadoSelecao = EstadoSelecao.SELECIONADA,
    artefatos: tuple[str, ...] = (_A,),
    **campos: object,
) -> SelecaoVersao:
    base = {
        "fonte": FamiliaFonte.CNES_PF,
        "base": BaseTemporal.PROCESSAMENTO,
        "competencia_requerida": "201801",
        "estado": estado,
        "artifact_ids": artefatos,
        "motivo": "criterio_documentado",
    }
    return SelecaoVersao.model_validate(base | campos)


def _vigencia(**campos: object) -> VigenciaDocumentada:
    base = {
        "inicio": "201801",
        "fim": "201812",
        "referente_a": TipoTempo.PROCESSAMENTO,
        "documento": _docref(),
    }
    return VigenciaDocumentada.model_validate(base | campos)


def _campos_snapshot(**campos: object) -> dict[str, object]:
    base = {
        "artifact_ids": (_A, _B),
        "observation_ids": (f"obs_{'1' * 32}",),
        "dataset_hashes": (f"lh1:{'d' * 64}",),
        "selecoes": (_selecao(),),
        "corte_observacao": datetime(2026, 9, 1, tzinfo=UTC),
    }
    return base | campos


@given(valor=_COMPETENCIAS, par=st.sampled_from(_PARES_DE_TIPOS))
def test_competencias_de_tipos_diferentes_nunca_sao_iguais(valor: str, par: tuple) -> None:
    primeira, segunda = (tipo(valor) for tipo in par)
    assert (primeira == segunda) is False
    assert primeira != segunda
    assert len({primeira, segunda}) == 2


@pytest.mark.parametrize(("tipo_a", "tipo_b"), _PARES_DE_TIPOS)
@pytest.mark.parametrize("operador", [operator.lt, operator.le, operator.gt, operator.ge])
def test_ordenacao_entre_tipos_diferentes_levanta_type_error(
    tipo_a: type, tipo_b: type, operador: Callable[[object, object], bool]
) -> None:
    with pytest.raises(TypeError, match="comparacao_entre_tempos_distintos"):
        operador(tipo_a("201801"), tipo_b("201802"))


def test_mesmo_tipo_compara_por_valor_e_nao_iguala_texto() -> None:
    janeiro = CompetenciaAtendimento("201801")
    assert janeiro == CompetenciaAtendimento("201801")
    assert hash(janeiro) == hash(CompetenciaAtendimento("201801"))
    assert janeiro < CompetenciaAtendimento("201802")
    assert janeiro != "201801"
    with pytest.raises(TypeError):
        operator.lt(janeiro, "201802")


@pytest.mark.parametrize("tipo", _TIPOS)
@pytest.mark.parametrize(
    "entrada", [201801, 201801.0, datetime(2018, 1, 1, tzinfo=UTC), date(2018, 1, 1), None]
)
def test_competencia_nao_e_construida_de_data_ou_numero(tipo: type, entrada: object) -> None:
    with pytest.raises(ValueError, match="competencia_invalida"):
        tipo(entrada)
    with pytest.raises(ValidationError):
        TypeAdapter(tipo).validate_python(entrada)


@pytest.mark.parametrize("tipo", _TIPOS)
@pytest.mark.parametrize(
    "texto", ["201800", "201813", "20181", "2018011", "2018-01", " 201801", "201801\n", "ano201"]
)
def test_rejeita_competencia_fora_do_formato_aaaamm(tipo: type, texto: str) -> None:
    with pytest.raises(ValueError, match="competencia_invalida"):
        tipo(texto)


def test_rejeita_competencia_com_digitos_nao_ascii() -> None:
    with pytest.raises(ValueError, match="competencia_invalida"):
        CompetenciaAtendimento("٢٠١٨" + "01")


@pytest.mark.parametrize("tipo", _TIPOS)
@pytest.mark.parametrize(
    ("origem", "meses", "destino"),
    [
        ("201801", -1, "201712"),
        ("201712", 1, "201801"),
        ("201812", 13, "202001"),
        ("201801", -13, "201612"),
        ("201806", 0, "201806"),
        ("202012", -24, "201812"),
    ],
)
def test_deslocar_preserva_o_tipo_e_atravessa_a_virada_do_ano(
    tipo: type, origem: str, meses: int, destino: str
) -> None:
    deslocada = tipo(origem).deslocar(meses)
    assert type(deslocada) is tipo
    assert deslocada == tipo(destino)


@given(valor=_COMPETENCIAS, tipo=st.sampled_from(_TIPOS))
def test_deslocar_um_mes_e_o_mes_civil_seguinte(valor: str, tipo: type) -> None:
    competencia = tipo(valor)
    seguinte = competencia.deslocar(1)
    virada = competencia.mes == 12
    assert seguinte.ano == competencia.ano + (1 if virada else 0)
    assert seguinte.mes == (1 if virada else competencia.mes + 1)


@given(valor=_COMPETENCIAS, meses=st.integers(-1200, 1200), tipo=st.sampled_from(_TIPOS))
def test_deslocar_ida_e_volta_retorna_a_origem(valor: str, meses: int, tipo: type) -> None:
    competencia = tipo(valor)
    assert competencia.deslocar(meses).deslocar(-meses) == competencia


@given(valor=_COMPETENCIAS, meses=st.integers(1, 1200))
def test_deslocar_para_frente_produz_competencia_posterior(valor: str, meses: int) -> None:
    competencia = CompetenciaProcessamento(valor)
    assert competencia < competencia.deslocar(meses)
    assert competencia.deslocar(-meses) < competencia


@pytest.mark.parametrize(("tipo_campo", "tipo_valor"), _PARES_DE_TIPOS)
def test_campo_de_um_tipo_rejeita_instancia_de_outro(tipo_campo: type, tipo_valor: type) -> None:
    with pytest.raises(ValidationError, match="tempo_incompativel"):
        TypeAdapter(tipo_campo).validate_python(tipo_valor("201801"))


@pytest.mark.parametrize("outro", [CompetenciaAtendimento, CompetenciaProcessamento])
def test_selecao_rejeita_competencia_que_nao_e_de_arquivo(outro: type) -> None:
    with pytest.raises(ValidationError, match="tempo_incompativel"):
        _selecao(competencia_requerida=outro("201801"))


def test_campo_converte_texto_no_tipo_declarado_e_sobrevive_ao_json() -> None:
    selecao = _selecao(competencia_requerida="201801")
    assert selecao.competencia_requerida == CompetenciaArquivo("201801")
    assert SelecaoVersao.model_validate_json(selecao.model_dump_json()) == selecao


@pytest.mark.parametrize("outro", [CompetenciaAtendimento, CompetenciaArquivo])
def test_vigencia_recusa_competencia_de_outro_tipo(outro: type) -> None:
    with pytest.raises(TypeError, match="vigencia_refere"):
        _vigencia().contem(outro("201806"))


@pytest.mark.parametrize(
    ("valor", "contida"),
    [("201712", False), ("201801", True), ("201806", True), ("201812", True), ("201901", False)],
)
def test_vigencia_contem_limites_inclusivos(valor: str, contida: bool) -> None:
    assert _vigencia().contem(CompetenciaProcessamento(valor)) is contida


def test_vigencia_sem_limites_contem_qualquer_competencia_do_tipo() -> None:
    assert _vigencia(inicio=None, fim=None).contem(CompetenciaProcessamento("190001"))


@pytest.mark.parametrize(
    ("inicio", "fim"), [("201813", None), (None, "2018-12"), ("201901", "201812")]
)
def test_vigencia_rejeita_limite_invalido_ou_invertido(inicio: str | None, fim: str | None) -> None:
    with pytest.raises(ValidationError):
        _vigencia(inicio=inicio, fim=fim)


def test_politica_documentada_exige_documento() -> None:
    with pytest.raises(ValidationError, match="politica_documentada_exige_documento"):
        _politica(documento=None)


def test_politica_exploratoria_dispensa_documento() -> None:
    politica = _politica(tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA, documento=None)
    assert politica.documento_pendente is False


def test_politica_nao_resolvida_nao_tem_criterios() -> None:
    with pytest.raises(ValidationError, match="politica_nao_resolvida_sem_criterios"):
        _politica(tipo=TipoPolitica.NAO_RESOLVIDA, documento=None)
    vazia = _politica(tipo=TipoPolitica.NAO_RESOLVIDA, criterios=(), documento=None)
    assert vazia.criterios == ()


@pytest.mark.parametrize("tipo", [TipoPolitica.DOCUMENTADA, TipoPolitica.ALTERNATIVA_EXPLORATORIA])
def test_politica_resolvida_exige_criterio(tipo: TipoPolitica) -> None:
    with pytest.raises(ValidationError, match="politica_sem_criterios"):
        _politica(tipo=tipo, criterios=())


def test_politica_rejeita_fonte_repetida() -> None:
    criterios = (_criterio(), _criterio(base=BaseTemporal.ATENDIMENTO, deslocamento_meses=-1))
    with pytest.raises(ValidationError, match="politica_com_fonte_repetida"):
        _politica(criterios=criterios)


@pytest.mark.parametrize(
    "campo", ["fallback", "mes_vizinho", "usar_mes_vizinho", "tolerancia_meses", "alternativa"]
)
def test_politica_nao_admite_fallback_para_mes_vizinho(campo: str) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _politica(**{campo: True})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _criterio(**{campo: True})


def test_politica_e_criterio_nao_declaram_campo_de_vizinhanca() -> None:
    nomes = set(PoliticaTemporal.model_fields) | set(CriterioTemporal.model_fields)
    suspeitos = {n for n in nomes if any(p in n for p in ("vizinh", "fallback", "toleran"))}
    assert suspeitos == set()


@pytest.mark.parametrize(("estado", "pendente"), [("PENDENTE", True), ("PRESERVADO", False)])
def test_politica_sinaliza_documento_pendente(estado: str, pendente: bool) -> None:
    assert _politica(documento=_docref(estado)).documento_pendente is pendente


@pytest.mark.parametrize(
    ("estado", "artefatos"),
    [
        (EstadoSelecao.SELECIONADA, (_A,)),
        (EstadoSelecao.SELECIONADA, (_A, _B)),
        (EstadoSelecao.AMBIGUA, (_A, _B)),
        (EstadoSelecao.AUSENTE, ()),
        (EstadoSelecao.NAO_RESOLVIDA, ()),
        (EstadoSelecao.INCOMPLETA, ()),
        (EstadoSelecao.EM_QUARENTENA, (_A,)),
        (EstadoSelecao.FORA_DO_CORTE, ()),
    ],
)
def test_selecao_aceita_artefatos_coerentes_com_o_estado(
    estado: EstadoSelecao, artefatos: tuple[str, ...]
) -> None:
    assert _selecao(estado, artefatos).artifact_ids == artefatos


@pytest.mark.parametrize(
    ("estado", "artefatos"),
    [
        (EstadoSelecao.SELECIONADA, ()),
        (EstadoSelecao.AMBIGUA, ()),
        (EstadoSelecao.AMBIGUA, (_A,)),
        (EstadoSelecao.AUSENTE, (_A,)),
        (EstadoSelecao.NAO_RESOLVIDA, (_A,)),
    ],
)
def test_selecao_rejeita_artefatos_incoerentes_com_o_estado(
    estado: EstadoSelecao, artefatos: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        _selecao(estado, artefatos)


def test_selecao_rejeita_artifact_id_malformado() -> None:
    with pytest.raises(ValidationError, match="selecao_artifact_id_invalido"):
        _selecao(artefatos=("art_curto",))


def test_snapshot_id_e_derivado_do_conteudo() -> None:
    snapshot = SnapshotSet.criar(**_campos_snapshot())
    conteudo = snapshot.model_dump(mode="json", exclude={"snapshot_id"}, exclude_none=True)
    assert snapshot.snapshot_id == f"snap_{hash_canonico({'v': 1, 'conteudo': conteudo})}"
    assert SnapshotSet.criar(**_campos_snapshot()).snapshot_id == snapshot.snapshot_id


@pytest.mark.parametrize(
    "alteracao",
    [
        {"dataset_hashes": (f"lh1:{'f' * 64}",)},
        {"observation_ids": ()},
        {"congelado": True},
        {"corte_observacao": None},
        {"selecoes": (_selecao(EstadoSelecao.AUSENTE, ()),)},
    ],
)
def test_snapshot_id_muda_quando_o_conteudo_muda(alteracao: dict[str, object]) -> None:
    original = SnapshotSet.criar(**_campos_snapshot())
    assert SnapshotSet.criar(**_campos_snapshot(**alteracao)).snapshot_id != original.snapshot_id


def test_snapshot_rejeita_conteudo_adulterado() -> None:
    adulterado = SnapshotSet.criar(**_campos_snapshot()).model_dump()
    adulterado["dataset_hashes"] = (f"lh1:{'f' * 64}",)
    with pytest.raises(ValidationError, match="snapshot_id_nao_corresponde_ao_conteudo"):
        SnapshotSet.model_validate(adulterado)


@pytest.mark.parametrize("snapshot_id", [f"snap_{'0' * 64}", "snap_provisorio", ""])
def test_snapshot_rejeita_id_que_nao_deriva_do_conteudo(snapshot_id: str) -> None:
    with pytest.raises(ValidationError, match="snapshot_id_nao_corresponde_ao_conteudo"):
        SnapshotSet.model_validate(_campos_snapshot(snapshot_id=snapshot_id))


@pytest.mark.parametrize("artefatos", [(_B, _A), (_A, _A)])
def test_snapshot_exige_artefatos_ordenados_e_unicos(artefatos: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="snapshot_artefatos_devem_ser_ordenados_e_unicos"):
        SnapshotSet.criar(**_campos_snapshot(artifact_ids=artefatos))


def test_snapshot_congelado_mantem_id_ao_revalidar() -> None:
    selecoes = (_selecao(competencia_requerida="201801"),)
    congelado = SnapshotSet.criar(**_campos_snapshot(congelado=True, selecoes=selecoes))
    via_python = SnapshotSet.model_validate(congelado.model_dump())
    via_json = SnapshotSet.model_validate_json(congelado.model_dump_json())
    assert via_python == congelado
    assert via_json == congelado
    assert via_json.snapshot_id == congelado.snapshot_id


def test_snapshot_rejeita_selecao_de_artefato_fora_do_conjunto() -> None:
    with pytest.raises(ValidationError):
        SnapshotSet.criar(**_campos_snapshot(selecoes=(_selecao(artefatos=(_C,)),)))


def test_snapshot_rejeita_artifact_id_malformado() -> None:
    with pytest.raises(ValidationError):
        SnapshotSet.criar(**_campos_snapshot(artifact_ids=("qualquer",), selecoes=()))


@pytest.mark.parametrize("observacao", [f"obs_{'2' * 32}", "obs_curto", "", f"obs_{'1' * 32}\n"])
def test_snapshot_rejeita_selecao_com_observacao_fora_do_conjunto(observacao: str) -> None:
    citada = _selecao(observation_ids=(f"obs_{'1' * 32}",))
    assert SnapshotSet.criar(**_campos_snapshot(selecoes=(citada,))).selecoes == (citada,)
    externa = _selecao(observation_ids=(f"obs_{'1' * 32}", observacao))
    with pytest.raises(ValidationError, match="snapshot_selecao_com_observacao_externa"):
        SnapshotSet.criar(**_campos_snapshot(selecoes=(externa,)))
