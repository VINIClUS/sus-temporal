"""CNES ST do contexto do `validate --ingest` conferido pelo registro e pelo corte (SINTETICO).

Como a produção, o CNES ST da pasta só entra no contexto se o registro o conhece e o seletor do
T06, até o `corte_observacao`, o escolhe com os artefatos da pasta; ao contrário dela, só a seleção
completa (`SELECIONADA`) vale, porque ausência cadastral não pode vir de arquivo parcial. O que
não passa fica fora do contexto, com um log por conjunto, e nunca recusa a execução.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.rules.ingest_cadastros import cadastros_aceitos
from sustemporal.temporal.registry import RegistroTemporal
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    import pytest

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion

    _Item = tuple[ArtifactObservation, ArtifactVersion]

_ST, _PF = "cnes_estabelecimento.v1", "cnes_estab_cbo.v1"
_JAN, _FEV = "202301", "202302"
_CORTE = "2026-01-02T12:00:00+00:00"
_DIA_INICIAL, _DIA_ATE_O_CORTE, _DIA_APOS_O_CORTE = 0, 1, 3
_LOG = "sustemporal.rules.ingest_cadastros"
_IGNORADO = "cadastro_do_contexto_ignorado"


def _config(corte: str | None = _CORTE) -> RunConfig:
    campos: dict[str, object] = {
        "versao": "1",
        "piloto": {
            "uf": "SP",
            "competencias_processamento": [_FEV],
            "territorio": "catalog/territorio/drs_xi.yaml",
            "familias_fontes": ["SIA_PA", "CNES_ST"],
        },
    }
    if corte is not None:
        campos["corte_observacao"] = corte
    return RunConfig.model_validate(campos)


def _item(
    competencia: str,
    conteudo: str,
    dias: int,
    *,
    fonte: FamiliaFonte = FamiliaFonte.CNES_ST,
    parte: str | None = None,
    uf: str = "SP",
    integridade_observada: EstadoIntegridade | None = None,
) -> _Item:
    observacao, versao = observar(
        fonte,
        competencia,
        conteudo,
        dias,
        parte=parte,
        uf=uf,
        integridade_observada=integridade_observada,
    )
    assert versao is not None
    return observacao, versao


def _registro(
    *itens: _Item, partes: dict[tuple[FamiliaFonte, str], frozenset[str]] | None = None
) -> RegistroTemporal:
    return RegistroTemporal(
        tuple(observacao for observacao, _ in itens),
        {versao.artifact_id: versao for _, versao in itens},
        partes or {},
    )


def _conjunto(*artefatos: str, schema_id: str = _ST) -> DatasetRef:
    hash_logico = f"lh1:{'a' * 64}"
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artefatos),
        schema_id=schema_id,
        caminho=f"/sintetico/{schema_id}.parquet",
        hash_logico=hash_logico,
        linhas=1,
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="teste",
    )


def _aceitos(
    conjuntos: list[DatasetRef], registro: RegistroTemporal, corte: str | None = _CORTE
) -> list[DatasetRef]:
    return cadastros_aceitos({_ST: conjuntos}, registro, _config(corte))[_ST]


def _ignorados(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [m for m in caplog.messages if m.startswith(_IGNORADO)]


def test_st_observado_ate_o_corte_entra_no_contexto(caplog: pytest.LogCaptureFixture) -> None:
    item = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    conjunto = _conjunto(item[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(item)) == [conjunto]
    assert not _ignorados(caplog)


def test_st_sem_corte_na_configuracao_entra_pelo_registro() -> None:
    item = _item(_JAN, "st-jan", _DIA_APOS_O_CORTE)
    conjunto = _conjunto(item[1].artifact_id)
    assert _aceitos([conjunto], _registro(item), corte=None) == [conjunto]


def test_st_observado_so_apos_o_corte_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    item = _item(_JAN, "st-jan", _DIA_APOS_O_CORTE)
    conjunto = _conjunto(item[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(item)) == []
    (mensagem,) = _ignorados(caplog)
    assert mensagem.startswith(f"{_IGNORADO} schema={_ST} dataset={conjunto.dataset_id} ")
    assert "motivo=selecao_nao_aceita competencia=202301 estado=FORA_DO_CORTE" in mensagem


def test_st_fora_do_registro_fica_fora_do_contexto(caplog: pytest.LogCaptureFixture) -> None:
    item = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    desconhecido = f"art_{'1' * 64}"
    conjunto = _conjunto(item[1].artifact_id, desconhecido)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(item)) == []
    (mensagem,) = _ignorados(caplog)
    assert f"motivo=fora_do_registro artefatos=['{desconhecido}']" in mensagem


def test_st_com_registro_vazio_fica_fora_do_contexto() -> None:
    conjunto = _conjunto(f"art_{'1' * 64}")
    assert _aceitos([conjunto], _registro()) == []


def test_st_em_quarentena_fica_fora_do_contexto(caplog: pytest.LogCaptureFixture) -> None:
    quarentena = EstadoIntegridade.QUARENTENA_CHECKSUM
    item = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE, integridade_observada=quarentena)
    conjunto = _conjunto(item[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(item)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=selecao_nao_aceita competencia=202301 estado=EM_QUARENTENA" in mensagem


def test_st_republicado_com_conteudo_divergente_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    antigo = _item(_JAN, "st-jan", _DIA_INICIAL)
    novo = _item(_JAN, "st-jan-outro", _DIA_ATE_O_CORTE)
    conjuntos = [_conjunto(antigo[1].artifact_id), _conjunto(novo[1].artifact_id)]
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos(conjuntos, _registro(antigo, novo)) == []
    assert len(_ignorados(caplog)) == 2
    assert all("estado=AMBIGUA" in mensagem for mensagem in _ignorados(caplog))


def test_st_de_versao_que_o_seletor_nao_escolheu_ate_o_corte_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    escolhida = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    republicada = _item(_JAN, "st-jan-outro", _DIA_APOS_O_CORTE)
    conjunto = _conjunto(republicada[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(escolhida, republicada)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=artefatos_diferentes_da_selecao competencia=202301" in mensagem
    assert f"pasta=['{republicada[1].artifact_id}']" in mensagem
    assert f"selecionados=['{escolhida[1].artifact_id}']" in mensagem


def test_competencia_com_artefatos_diferentes_dos_selecionados_sai_inteira_do_contexto() -> None:
    escolhida = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    republicada = _item(_JAN, "st-jan-outro", _DIA_APOS_O_CORTE)
    conjuntos = [_conjunto(escolhida[1].artifact_id), _conjunto(republicada[1].artifact_id)]
    assert _aceitos(conjuntos, _registro(escolhida, republicada)) == []


def test_cada_competencia_do_st_e_conferida_pelo_seu_proprio_corte() -> None:
    janeiro = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    fevereiro = _item(_FEV, "st-fev", _DIA_APOS_O_CORTE)
    do_mes = [_conjunto(janeiro[1].artifact_id), _conjunto(fevereiro[1].artifact_id)]
    assert _aceitos(do_mes, _registro(janeiro, fevereiro)) == [do_mes[0]]


def test_conjunto_com_duas_competencias_sai_se_uma_delas_nao_passa() -> None:
    janeiro = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    fevereiro = _item(_FEV, "st-fev", _DIA_APOS_O_CORTE)
    uniao = _conjunto(janeiro[1].artifact_id, fevereiro[1].artifact_id)
    assert _aceitos([uniao], _registro(janeiro, fevereiro)) == []


def test_st_de_outra_fonte_do_registro_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pf = _item(_JAN, "pf-jan", _DIA_ATE_O_CORTE, fonte=FamiliaFonte.CNES_PF)
    conjunto = _conjunto(pf[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(pf)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=selecao_nao_aceita competencia=202301 estado=AUSENTE" in mensagem


def test_st_de_outra_uf_fica_fora_do_contexto() -> None:
    item = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE, uf="MG")
    assert _aceitos([_conjunto(item[1].artifact_id)], _registro(item)) == []


def test_st_com_selecao_incompleta_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A produção aceita `INCOMPLETA` e a marca na cobertura; o cadastro não tem essa marca."""
    parte_a = _item(_JAN, "st-jan-a", _DIA_ATE_O_CORTE, parte="a")
    conjunto = _conjunto(parte_a[1].artifact_id)
    esperadas = {(FamiliaFonte.CNES_ST, _JAN): frozenset({"a", "b"})}
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(parte_a, partes=esperadas)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=selecao_nao_aceita competencia=202301 estado=INCOMPLETA" in mensagem


def test_st_com_todas_as_partes_que_o_seletor_escolheu_entra_no_contexto() -> None:
    parte_a = _item(_JAN, "st-jan-a", _DIA_ATE_O_CORTE, parte="a")
    parte_b = _item(_JAN, "st-jan-b", _DIA_ATE_O_CORTE, parte="b")
    esperadas = {(FamiliaFonte.CNES_ST, _JAN): frozenset({"a", "b"})}
    conjuntos = [_conjunto(parte_a[1].artifact_id), _conjunto(parte_b[1].artifact_id)]
    assert _aceitos(conjuntos, _registro(parte_a, parte_b, partes=esperadas)) == conjuntos


def test_st_sem_uma_das_partes_que_o_seletor_escolheu_fica_fora_do_contexto(
    caplog: pytest.LogCaptureFixture,
) -> None:
    parte_a = _item(_JAN, "st-jan-a", _DIA_ATE_O_CORTE, parte="a")
    parte_b = _item(_JAN, "st-jan-b", _DIA_ATE_O_CORTE, parte="b")
    esperadas = {(FamiliaFonte.CNES_ST, _JAN): frozenset({"a", "b"})}
    conjunto = _conjunto(parte_a[1].artifact_id)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([conjunto], _registro(parte_a, parte_b, partes=esperadas)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=artefatos_diferentes_da_selecao competencia=202301" in mensagem
    selecionados = sorted([parte_a[1].artifact_id, parte_b[1].artifact_id])
    assert f"selecionados={selecionados}" in mensagem


def test_conjunto_sem_artefatos_fica_fora_do_contexto(caplog: pytest.LogCaptureFixture) -> None:
    item = _item(_JAN, "st-jan", _DIA_ATE_O_CORTE)
    with caplog.at_level(logging.WARNING, logger=_LOG):
        assert _aceitos([_conjunto()], _registro(item)) == []
    (mensagem,) = _ignorados(caplog)
    assert "motivo=sem_artefatos" in mensagem


def test_so_o_cadastro_do_contexto_e_conferido_os_demais_auxiliares_passam() -> None:
    item = _item(_JAN, "st-jan", _DIA_APOS_O_CORTE)
    cadastro = _conjunto(item[1].artifact_id)
    das_regras = _conjunto(f"art_{'2' * 64}", schema_id=_PF)
    auxiliares = {_PF: [das_regras], _ST: [cadastro]}

    aceitos = cadastros_aceitos(auxiliares, _registro(item), _config())

    assert aceitos == {_PF: [das_regras], _ST: []}
    assert auxiliares == {_PF: [das_regras], _ST: [cadastro]}


def test_esquema_sem_conjuntos_na_pasta_continua_sem_conjuntos() -> None:
    assert cadastros_aceitos({_ST: []}, _registro(), _config()) == {_ST: []}
