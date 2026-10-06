"""Política de cada método como a execução congelada a usou (T14); SINTETICO.

O `validate` resolve a política por `config.politica_id` (a do catálogo, só do método dela) ou pela
padrão do método. A reprodução refaz cada método com a política da entrada de validação original,
conferida contra o manifesto e contra a execução registrada; o que não se resolve ou não se confere
é problema da política congelada (inconclusão), nunca erro de configuração nem divergência.
"""

from __future__ import annotations

import shutil
from functools import cache
from typing import TYPE_CHECKING

import pytest

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.evaluation.freeze_entrada import identidades_da_entrada
from sustemporal.reporting.reproduce_politicas import politicas_congeladas
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.insumos import politica_padrao
from sustemporal.temporal.politicas import DIRETORIO_POLITICAS, carregar_politica
from tests.fixtures.protocolo_insumos import conjunto_sintetico, entrada_da_politica

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.contracts.rules import RuleSpec
    from sustemporal.reporting.reproduce_politicas import PoliticasCongeladas
    from sustemporal.rules.entrada import EntradaValidacao

M_TEMP, B_ATEND, B_PROC = MetodoId.M_TEMP, MetodoId.B_ATEND, MetodoId.B_PROC
INDISPONIVEL = "politica_congelada_indisponivel"


@cache
def _regras() -> list[RuleSpec]:
    return carregar_regras()


def _teste() -> DatasetRef:
    return conjunto_sintetico("sia_pa.v1", "teste")


def _padrao(metodo: MetodoId) -> PoliticaTemporal:
    return politica_padrao(metodo, _regras())


def _entrada(chave: str, politica: PoliticaTemporal | None) -> EntradaValidacao:
    return entrada_da_politica(_teste(), chave).model_copy(update={"politica": politica})


def _resolver(
    *politicas: PoliticaTemporal,
    registradas: dict[MetodoId, str | None] | None = None,
    diretorio: Path | None = None,
) -> PoliticasCongeladas:
    entradas = {p.politica_id: _entrada(p.politica_id, p) for p in politicas}
    identidades = {chave: identidades_da_entrada(entrada) for chave, entrada in entradas.items()}
    return politicas_congeladas(entradas, identidades, registradas or {}, _regras(), diretorio)


def _fora_do_catalogo(metodo: MetodoId, politica_id: str) -> PoliticaTemporal:
    """Política que não é a padrão nem está no catálogo; B_ML não tem seleção temporal."""
    if metodo is MetodoId.B_ML:
        return PoliticaTemporal(
            politica_id=politica_id, tipo=TipoPolitica.NAO_RESOLVIDA, metodo=metodo, criterios=()
        )
    criterio = CriterioTemporal(fonte=FamiliaFonte.CNES_ST, base=BaseTemporal.ATENDIMENTO)
    return PoliticaTemporal(
        politica_id=politica_id,
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo=metodo,
        criterios=(criterio,),
    )


def _catalogo_com(tmp_path: Path, nome: str, texto: str | None) -> Path:
    """Cópia de `catalog/policies` em que a política `nome` tem o `texto` (ou não existe)."""
    pasta = tmp_path / "policies"
    shutil.copytree(DIRETORIO_POLITICAS, pasta)
    arquivo = pasta / f"{nome}.yaml"
    if texto is None:
        arquivo.unlink()
    else:
        arquivo.write_text(texto, encoding="utf-8")
    return pasta


def test_cada_metodo_se_refaz_com_a_politica_que_a_execucao_congelada_usou() -> None:
    resolvido = _resolver(carregar_politica("M_TEMP_PADRAO"), _padrao(B_ATEND), _padrao(B_PROC))
    assert resolvido.por_metodo == {M_TEMP: "M_TEMP_PADRAO", B_ATEND: None, B_PROC: None}
    assert resolvido.problemas == {}


def test_politicas_do_catalogo_nos_tres_metodos_viram_a_politica_id_de_cada_um() -> None:
    politicas = [carregar_politica(nome) for nome in ("M_TEMP_PADRAO", "B_ATEND", "B_PROC")]
    resolvido = _resolver(*politicas)
    assert resolvido.por_metodo == {M_TEMP: "M_TEMP_PADRAO", B_ATEND: "B_ATEND", B_PROC: "B_PROC"}
    assert resolvido.problemas == {}


def test_politica_padrao_dos_tres_metodos_se_refaz_pela_padrao() -> None:
    resolvido = _resolver(_padrao(M_TEMP), _padrao(B_ATEND), _padrao(B_PROC))
    assert resolvido.por_metodo == {M_TEMP: None, B_ATEND: None, B_PROC: None}
    assert resolvido.problemas == {}


def test_metodo_sem_politica_congelada_segue_pela_padrao() -> None:
    resolvido = _resolver(carregar_politica("B_ATEND"))
    assert resolvido.por_metodo == {M_TEMP: None, B_ATEND: "B_ATEND", B_PROC: None}
    assert resolvido.problemas == {}


def test_sem_nenhuma_politica_congelada_nada_a_resolver() -> None:
    resolvido = politicas_congeladas({}, {}, {}, _regras())
    assert resolvido.por_metodo == {M_TEMP: None, B_ATEND: None, B_PROC: None}
    assert resolvido.problemas == {}


def test_politica_que_nao_e_a_padrao_nem_esta_no_catalogo_e_indisponivel() -> None:
    desconhecida = _fora_do_catalogo(B_ATEND, "B_ATEND_DOCUMENTADA")
    resolvido = _resolver(desconhecida, _padrao(B_PROC))
    assert resolvido.problemas == {"B_ATEND_DOCUMENTADA": INDISPONIVEL}
    assert resolvido.por_metodo[B_PROC] is None


def test_politica_do_catalogo_que_mudou_depois_do_congelamento_e_indisponivel(
    tmp_path: Path,
) -> None:
    texto = (DIRETORIO_POLITICAS / "B_ATEND.yaml").read_text(encoding="utf-8")
    sigtap = '  - fonte: SIGTAP\n    base: ATENDIMENTO\n    deslocamento_meses: "0"\n'
    mudada = texto.replace(sigtap, "")
    assert mudada != texto
    diretorio = _catalogo_com(tmp_path, "B_ATEND", mudada)
    resolvido = _resolver(carregar_politica("B_ATEND"), diretorio=diretorio)
    assert resolvido.problemas == {"B_ATEND": INDISPONIVEL}


def test_politica_do_catalogo_que_sumiu_e_indisponivel(tmp_path: Path) -> None:
    diretorio = _catalogo_com(tmp_path, "M_TEMP_PADRAO", None)
    resolvido = _resolver(carregar_politica("M_TEMP_PADRAO"), diretorio=diretorio)
    assert resolvido.problemas == {"M_TEMP_PADRAO": INDISPONIVEL}


def test_politica_padrao_que_mudou_com_o_catalogo_de_regras_e_indisponivel() -> None:
    padrao = _padrao(B_ATEND)
    mudada = padrao.model_copy(update={"criterios": padrao.criterios[:-1]})
    assert mudada != padrao
    assert _resolver(mudada).problemas == {"b_atend_exploratoria": INDISPONIVEL}


def test_duas_politicas_congeladas_do_mesmo_metodo_sao_ambiguas() -> None:
    resolvido = _resolver(carregar_politica("M_TEMP_PADRAO"), _padrao(M_TEMP), _padrao(B_ATEND))
    motivo = "politica_congelada_ambigua metodo=M_TEMP"
    assert resolvido.problemas == {"M_TEMP_PADRAO": motivo, "m_temp_nao_resolvida": motivo}


def test_politica_de_metodo_sem_validacao_por_regras_nao_se_refaz() -> None:
    politica = _fora_do_catalogo(MetodoId.B_ML, "B_ML_EXPLORATORIA")
    assert _resolver(politica).problemas == {"B_ML_EXPLORATORIA": INDISPONIVEL}


def test_politica_cujo_id_difere_da_chave_da_entrada_nao_se_refaz() -> None:
    politica = carregar_politica("B_ATEND")
    entradas = {"outra": _entrada("outra", politica)}
    identidades = {"outra": identidades_da_entrada(entradas["outra"])}
    resolvido = politicas_congeladas(entradas, identidades, {}, _regras())
    assert resolvido.problemas == {"outra": "politica_congelada_com_outro_id id=B_ATEND"}


def test_politica_que_nao_tem_a_identidade_congelada_esta_alterada() -> None:
    politica = carregar_politica("B_ATEND")
    entrada = _entrada("B_ATEND", politica)
    congelada = identidades_da_entrada(_entrada("B_ATEND", carregar_politica("B_PROC")))
    resolvido = politicas_congeladas({"B_ATEND": entrada}, {"B_ATEND": congelada}, {}, _regras())
    assert resolvido.problemas == {"B_ATEND": "politica_congelada_alterada"}


def test_entrada_sem_a_politica_resolvida_vale_a_do_catalogo_com_a_identidade_congelada() -> None:
    entrada = _entrada("B_ATEND", None)
    congelada = {**identidades_da_entrada(entrada), "politica": _hash("B_ATEND")}
    resolvido = politicas_congeladas({"B_ATEND": entrada}, {"B_ATEND": congelada}, {}, _regras())
    assert resolvido.por_metodo[B_ATEND] == "B_ATEND"
    assert resolvido.problemas == {}


def test_entrada_sem_a_politica_resolvida_e_sem_politica_no_catalogo_e_indisponivel() -> None:
    entrada = _entrada("b_atend_exploratoria", None)
    congelada = identidades_da_entrada(entrada)
    resolvido = politicas_congeladas(
        {"b_atend_exploratoria": entrada}, {"b_atend_exploratoria": congelada}, {}, _regras()
    )
    assert resolvido.problemas == {"b_atend_exploratoria": INDISPONIVEL}


def test_entrada_sem_a_politica_resolvida_com_outra_identidade_esta_alterada() -> None:
    entrada = _entrada("B_ATEND", None)
    congelada = {**identidades_da_entrada(entrada), "politica": _hash("B_PROC")}
    resolvido = politicas_congeladas({"B_ATEND": entrada}, {"B_ATEND": congelada}, {}, _regras())
    assert resolvido.problemas == {"B_ATEND": "politica_congelada_alterada"}


def test_politica_registrada_diferente_da_congelada_nao_se_refaz() -> None:
    resolvido = _resolver(carregar_politica("B_ATEND"), registradas={B_ATEND: "B_PROC"})
    assert resolvido.problemas == {"B_ATEND": "politica_registrada_diferente registrada=B_PROC"}


def test_execucao_registrada_sem_politica_tambem_nao_confere() -> None:
    resolvido = _resolver(carregar_politica("B_ATEND"), registradas={B_ATEND: None})
    assert resolvido.problemas == {"B_ATEND": "politica_registrada_diferente registrada=None"}


def test_politica_registrada_igual_a_congelada_confere() -> None:
    resolvido = _resolver(
        carregar_politica("B_ATEND"), registradas={B_ATEND: "B_ATEND", B_PROC: "B_PROC"}
    )
    assert resolvido.problemas == {}
    assert resolvido.por_metodo[B_ATEND] == "B_ATEND"


@pytest.mark.parametrize("metodo", [M_TEMP, B_PROC])
def test_politica_registrada_de_metodo_sem_politica_congelada_nao_conta(metodo: MetodoId) -> None:
    resolvido = _resolver(carregar_politica("B_ATEND"), registradas={metodo: "qualquer"})
    assert resolvido.problemas == {}


def _hash(nome: str) -> str:
    return identidades_da_entrada(_entrada(nome, carregar_politica(nome)))["politica"]
