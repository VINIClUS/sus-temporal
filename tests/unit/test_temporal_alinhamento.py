"""Seleção alinhada ao motor: política única da execução, coincidência M_TEMP, lote e coleta."""

from __future__ import annotations

import duckdb

from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    CriterioTemporal,
    EstadoSelecao,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.temporal.lote import selecionar_lote
from sustemporal.temporal.registry import RegistroTemporal, registro_de
from sustemporal.temporal.selector import criterio_da_regra, selecionar_versao, select_snapshots
from tests.fixtures.temporal_registro import observar, registro_producao, regra

PF = FamiliaFonte.CNES_PF
_ATEND = CriterioTemporal(fonte=PF, base=BaseTemporal.ATENDIMENTO)
_JAN = CompetenciaArquivo("201801")
_SEM_CRITERIO = f"politica_sem_criterio_para_a_fonte fonte={PF}"


def _registro(*itens) -> RegistroTemporal:
    return registro_de([o for o, _ in itens], [v for _, v in itens if v is not None])


def _config(politica: str | None = None, *, corte: str | None = None) -> RunConfig:
    campos: dict[str, object] = {
        "versao": "1",
        "piloto": {
            "uf": "SP",
            "competencias_processamento": ["201801"],
            "territorio": "catalog/territorio/drs_xi.yaml",
            "familias_fontes": ["SIA_PA", "CNES_PF"],
        },
    }
    if politica is not None:
        campos["politica_id"] = politica
    if corte is not None:
        campos["corte_observacao"] = corte
    return RunConfig.model_validate(campos)


def _m_temp() -> PoliticaTemporal:
    return PoliticaTemporal(
        politica_id="M_TEMP_EXP",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo="M_TEMP",
        criterios=(_ATEND,),
    )


def _regra_documental(criterio: CriterioTemporal):
    return regra().model_copy(update={"criterios_temporais": (criterio,)})


def test_sem_politica_da_execucao_a_selecao_se_abstem() -> None:
    linha = registro_producao("201801", "201801")
    registro = _registro(observar(PF, "201801", "A", 1))
    (sel,) = select_snapshots(linha, regra(), _config(), registro=registro).selecoes
    assert sel.estado is EstadoSelecao.NAO_RESOLVIDA
    assert sel.motivo == "politica_da_execucao_ausente"
    assert sel.base is None


def test_politica_da_regra_nunca_escolhe_a_da_execucao() -> None:
    linha = registro_producao("201801", "201801")
    registro = _registro(observar(PF, "201801", "A", 1))
    (sel,) = select_snapshots(linha, regra(), _config("B_PROC"), registro=registro).selecoes
    assert sel.base is BaseTemporal.PROCESSAMENTO


def test_m_temp_so_vale_com_criterio_documental_coincidente() -> None:
    assert criterio_da_regra(_m_temp(), regra(), PF) is None
    assert criterio_da_regra(_m_temp(), _regra_documental(_ATEND), PF) == _ATEND
    deslocado = CriterioTemporal(fonte=PF, base=BaseTemporal.ATENDIMENTO, deslocamento_meses=-1)
    assert criterio_da_regra(_m_temp(), _regra_documental(deslocado), PF) is None


def test_m_temp_sem_coincidencia_e_nao_resolvida_por_registro_e_em_lote() -> None:
    linha = registro_producao("201801", "201801")
    registro = _registro(observar(PF, "201801", "A", 1))
    (sel,) = select_snapshots(
        linha, regra(), _config(), registro=registro, politica=_m_temp()
    ).selecoes
    assert (sel.estado, sel.motivo) == (EstadoSelecao.NAO_RESOLVIDA, _SEM_CRITERIO)
    ((estado, motivo),) = _lote(registro, _m_temp(), _config()).fetchall()
    assert (estado, motivo) == ("NAO_RESOLVIDA", _SEM_CRITERIO)


def _lote(
    registro: RegistroTemporal, politica: PoliticaTemporal, config: RunConfig
) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE registros (row_id VARCHAR, competencia_atendimento VARCHAR, "
        "competencia_processamento VARCHAR)"
    )
    linha = registro_producao("201801", "201801")
    con.execute("INSERT INTO registros VALUES (?, '201801', '201801')", [linha.row_id])
    selecionar_lote(con, "registros", [regra()], politica, registro, run_id="r", config=config)
    return con.execute("SELECT estado, motivo FROM selecao_versoes")


def test_lote_le_uf_e_corte_da_config() -> None:
    registro = _registro(observar(PF, "201801", "A", 30))
    ((estado, _motivo),) = _lote(registro, _politica_atend(), _config()).fetchall()
    assert estado == "SELECIONADA"
    com_corte = _config(corte="2026-01-20T00:00:00+00:00")
    ((estado, _motivo),) = _lote(registro, _politica_atend(), com_corte).fetchall()
    assert estado == "FORA_DO_CORTE"


def _politica_atend() -> PoliticaTemporal:
    return PoliticaTemporal(
        politica_id="EXP",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo="B_ATEND",
        criterios=(_ATEND,),
    )


def test_transferencia_interrompida_com_bytes_nao_e_ausencia() -> None:
    obs, _ = observar(PF, "201801", "A", 1, resultado=ResultadoTentativa.INTERROMPIDO)
    parcial = obs.model_copy(update={"bytes_recebidos": 5})
    sel = selecionar_versao(_registro((parcial, None)), _ATEND, _JAN, uf="SP")
    assert sel.estado is EstadoSelecao.EM_QUARENTENA
    assert sel.motivo.startswith("falha_de_coleta_com_bytes")


def test_conteudo_invalido_recusado_antes_do_hash_nao_e_ausencia() -> None:
    obs, _ = observar(
        PF,
        "201801",
        "A",
        1,
        resultado=ResultadoTentativa.CONTEUDO_INVALIDO,
        integridade=EstadoIntegridade.QUARENTENA_TRUNCADO,
    )
    sem_hash = obs.model_copy(update={"sha256_obtido": None, "artifact_id": None})
    sel = selecionar_versao(_registro((sem_hash, None)), _ATEND, _JAN, uf="SP")
    assert sel.estado is EstadoSelecao.EM_QUARENTENA
    assert sel.motivo.startswith("falha_de_coleta_com_bytes")


def test_nao_encontrado_quebra_o_intervalo_do_mesmo_conteudo() -> None:
    a1 = observar(PF, "201801", "A", 1)
    falta = observar(PF, "201801", "A", 2, resultado=ResultadoTentativa.NAO_ENCONTRADO)
    a2 = observar(PF, "201801", "A", 3)
    intervalos = _registro(a1, falta, a2).intervalos(PF, "SP", _JAN)
    assert [i.observation_ids for i in intervalos] == [
        (a1[0].observation_id,),
        (a2[0].observation_id,),
    ]
