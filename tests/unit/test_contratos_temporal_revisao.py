"""Tempo: identidade estável do snapshot, seleção completa e políticas coerentes com o método."""

import pytest
from pydantic import ValidationError

from sustemporal.contracts.temporal import (
    BaseTemporal,
    EstadoSelecao,
    MetodoId,
    SnapshotSet,
    TipoPolitica,
)
from tests.unit.test_contratos_temporal import _campos_snapshot, _criterio, _politica, _selecao

_A = f"art_{'a' * 64}"
_B = f"art_{'b' * 64}"
_ARTEFATOS_VALIDOS = {
    EstadoSelecao.SELECIONADA: (_A,),
    EstadoSelecao.AMBIGUA: (_A, _B),
    EstadoSelecao.AUSENTE: (),
    EstadoSelecao.INCOMPLETA: (_A,),
    EstadoSelecao.EM_QUARENTENA: (_A,),
    EstadoSelecao.FORA_DO_CORTE: (),
}
_EXPLORATORIA = TipoPolitica.ALTERNATIVA_EXPLORATORIA


class _SnapshotComCampoNovo(SnapshotSet):
    x: str | None = None


def test_campo_opcional_novo_nao_muda_o_snapshot_id() -> None:
    original = SnapshotSet.criar(**_campos_snapshot())
    assert _SnapshotComCampoNovo.criar(**_campos_snapshot()).snapshot_id == original.snapshot_id


@pytest.mark.parametrize("estado", list(_ARTEFATOS_VALIDOS))
@pytest.mark.parametrize("ausente", ["base", "competencia_requerida"])
def test_selecao_resolvida_exige_base_e_competencia(estado: EstadoSelecao, ausente: str) -> None:
    artefatos = _ARTEFATOS_VALIDOS[estado]
    assert _selecao(estado, artefatos).competencia_requerida is not None
    with pytest.raises(ValidationError, match="selecao_sem_base_ou_competencia"):
        _selecao(estado, artefatos, **{ausente: None})


def test_selecao_nao_resolvida_dispensa_base_e_competencia() -> None:
    nao_resolvida = _selecao(EstadoSelecao.NAO_RESOLVIDA, (), base=None, competencia_requerida=None)
    assert nao_resolvida.base is None
    with pytest.raises(ValidationError, match="selecao_sem_base_ou_competencia"):
        _selecao(EstadoSelecao.AUSENTE, (), base=None, competencia_requerida=None)


@pytest.mark.parametrize(
    ("metodo", "criterio"),
    [
        (MetodoId.B_ATEND, {"base": BaseTemporal.PROCESSAMENTO}),
        (MetodoId.B_ATEND, {"base": BaseTemporal.ATENDIMENTO, "deslocamento_meses": -1}),
        (MetodoId.B_PROC, {"base": BaseTemporal.ATENDIMENTO}),
        (MetodoId.B_PROC, {"base": BaseTemporal.PROCESSAMENTO, "deslocamento_meses": 1}),
        (MetodoId.B_ML, {"base": BaseTemporal.PROCESSAMENTO}),
        (MetodoId.CONTROLE_TRIVIAL, {"base": BaseTemporal.ATENDIMENTO}),
    ],
)
def test_politica_da_baseline_segue_o_metodo(metodo: MetodoId, criterio: dict[str, object]) -> None:
    criterios = (_criterio(**criterio),)
    m_temp = _politica(tipo=_EXPLORATORIA, metodo=MetodoId.M_TEMP, criterios=criterios)
    assert m_temp.criterios == criterios
    with pytest.raises(ValidationError, match="politica_incoerente_com_metodo"):
        _politica(tipo=_EXPLORATORIA, metodo=metodo, criterios=criterios)


@pytest.mark.parametrize(
    ("metodo", "base"),
    [(MetodoId.B_ATEND, BaseTemporal.ATENDIMENTO), (MetodoId.B_PROC, BaseTemporal.PROCESSAMENTO)],
)
def test_baseline_deterministica_usa_so_a_propria_competencia(
    metodo: MetodoId, base: BaseTemporal
) -> None:
    coerente = _politica(tipo=_EXPLORATORIA, metodo=metodo, criterios=(_criterio(base=base),))
    assert coerente.metodo is metodo
    deslocada = _criterio(base=base, deslocamento_meses=-2)
    with pytest.raises(ValidationError, match="politica_incoerente_com_metodo"):
        _politica(tipo=_EXPLORATORIA, metodo=metodo, criterios=(deslocada,))


@pytest.mark.parametrize("metodo", [MetodoId.B_ML, MetodoId.CONTROLE_TRIVIAL])
def test_politica_sem_selecao_temporal_nao_tem_criterios(metodo: MetodoId) -> None:
    sem_criterios = {"tipo": TipoPolitica.NAO_RESOLVIDA, "criterios": (), "documento": None}
    assert _politica(metodo=metodo, **sem_criterios).criterios == ()
    with pytest.raises(ValidationError, match="politica_incoerente_com_metodo"):
        _politica(metodo=metodo, tipo=_EXPLORATORIA, documento=None)


def test_snapshot_registra_hash_logico_da_cobertura() -> None:
    assert "cobertura_hash_logico" in SnapshotSet.model_fields
    sem_cobertura = SnapshotSet.criar(**_campos_snapshot())
    nulo = SnapshotSet.criar(**_campos_snapshot(cobertura_hash_logico=None))
    assert nulo.snapshot_id == sem_cobertura.snapshot_id
    com_cobertura = SnapshotSet.criar(**_campos_snapshot(cobertura_hash_logico=f"lh1:{'e' * 64}"))
    assert com_cobertura.snapshot_id != sem_cobertura.snapshot_id
    with pytest.raises(ValidationError):
        SnapshotSet.criar(**_campos_snapshot(cobertura_hash_logico="lh1:curto"))
