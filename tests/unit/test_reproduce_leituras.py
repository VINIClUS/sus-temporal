"""Arquivos que a cadeia do `reproduce` abre e o que acontece quando um deles não abre (T14).

A tabela `LEITURAS` é a da seção 5.5 do runbook, linha a linha: cada arquivo (ou grupo de arquivos
do mesmo leitor) diz quem o lê, de onde vem o que ele traz, o que o confere e o resultado de cada
dano. Quem se estraga tem os três danos, ou diz por que um não se aplica; quem não se estraga (o
destino da reprodução, o código, os temporários) diz por quê. A varredura que estraga os arquivos
de verdade e a auditoria das aberturas estão em `tests/integration/test_reproduce_leituras.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sustemporal.reporting.reproduce_leituras import (
    LEITURAS,
    Dano,
    Estrago,
    Leitura,
    Origem,
    Raiz,
    Resultado,
)
from sustemporal.reporting.reproduce_varredura import LEITURAS as REEXPORTADAS

RUNBOOK = Path(__file__).resolve().parents[2] / "docs" / "runbooks" / "reproducao.md"
SE_ESTRAGAM = {Origem.CONFIG, Origem.CATALOGO, Origem.ORIGINAL}
COM_ITENS = {Resultado.INCONCLUSIVO, Resultado.IGUAL_PELO_DECLARADO}


def _linha_do_arquivo(leitura: Leitura) -> str:
    colunas = (leitura.arquivo, leitura.quem_le, leitura.fonte, leitura.confere)
    return "| " + " | ".join(colunas) + " |"


def _celula(leitura: Leitura, dano: Dano) -> str:
    estrago = leitura.estragos.get(dano)
    return "—" if estrago is None else _texto_do_estrago(estrago)


def _texto_do_estrago(estrago: Estrago) -> str:
    texto = estrago.texto
    return f"{texto}, observação `{estrago.observacao}`" if estrago.observacao else texto


def _linha_do_dano(leitura: Leitura) -> str:
    celulas = (_celula(leitura, dano) for dano in Dano)
    return "| " + " | ".join((leitura.arquivo, *celulas)) + " |"


def _linha_do_motivo(leitura: Leitura) -> str:
    return f"- {leitura.arquivo}: {leitura.sem_estrago}"


def test_a_tabela_e_a_mesma_que_a_varredura_reexporta() -> None:
    assert REEXPORTADAS is LEITURAS


@pytest.mark.parametrize("chave", list(LEITURAS))
def test_toda_leitura_diz_quem_le_a_fonte_e_o_que_confere(chave: str) -> None:
    leitura = LEITURAS[chave]
    assert leitura.quem_le.strip()
    assert leitura.fonte.strip()
    assert leitura.confere.strip()
    assert leitura.padroes


@pytest.mark.parametrize("chave", list(LEITURAS))
def test_leitura_sem_um_dano_diz_por_que_e_a_que_tem_os_tres_nao_diz(chave: str) -> None:
    leitura = LEITURAS[chave]
    assert bool(leitura.sem_estrago) == (len(leitura.estragos) < len(Dano))


@pytest.mark.parametrize("chave", list(LEITURAS))
def test_so_o_que_a_cadeia_le_de_fora_se_estraga(chave: str) -> None:
    leitura = LEITURAS[chave]
    assert bool(leitura.estragos) == (leitura.origem in SE_ESTRAGAM)


@pytest.mark.parametrize("chave", list(LEITURAS))
def test_resultado_inconclusivo_ou_igual_pelo_declarado_diz_os_itens_e_o_outro_nao(
    chave: str,
) -> None:
    for estrago in LEITURAS[chave].estragos.values():
        assert bool(estrago.itens) == (estrago.resultado in COM_ITENS), chave


def test_so_o_registro_ilegivel_e_o_bruto_sem_permissao_trazem_observacao() -> None:
    com_observacao = {
        chave
        for chave, leitura in LEITURAS.items()
        if any(estrago.observacao for estrago in leitura.estragos.values())
    }
    assert com_observacao == {"registro", "brutos_dbc", "brutos_zip"}


def test_nenhuma_raiz_tem_o_mesmo_padrao_em_duas_leituras() -> None:
    vistos: dict[tuple[Raiz, str], str] = {}
    for chave, leitura in LEITURAS.items():
        for padrao in leitura.padroes:
            assert (leitura.raiz, padrao) not in vistos, (chave, vistos[(leitura.raiz, padrao)])
            vistos[(leitura.raiz, padrao)] = chave


def test_casa_pela_raiz_e_pelo_padrao_relativo_a_ela() -> None:
    leitura = LEITURAS["relatorio"]
    assert leitura.casa(Raiz.SAIDAS, "avaliacao/frz_a/rep_b.json")
    assert not leitura.casa(Raiz.SAIDAS, "avaliacao/frz_a/outro.json")
    assert not leitura.casa(Raiz.DESTINO, "avaliacao/frz_a/rep_b.json")


def test_o_ponto_e_a_propria_raiz_quando_ela_e_um_arquivo() -> None:
    assert LEITURAS["config"].casa(Raiz.CONFIG, ".")
    assert not LEITURAS["config"].casa(Raiz.CONFIG, "config.yaml")


def test_o_asterisco_atravessa_pastas_e_o_nome_literal_nao_casa_com_outro() -> None:
    assert LEITURAS["destino"].casa(Raiz.DESTINO, "runs/val_1/run_result.json")
    assert LEITURAS["esquemas_da_comparacao"].casa(Raiz.CATALOGO, "schemas/avaliacoes.yaml")
    assert not LEITURAS["esquemas_da_comparacao"].casa(Raiz.CATALOGO, "schemas/sia_pa.yaml")


@pytest.mark.parametrize(
    ("estrago", "texto"),
    [
        (Estrago(Resultado.CONFIG_INVALIDA), "saída 2"),
        (Estrago(Resultado.FALHA), "falha operacional (saída 5)"),
        (Estrago(Resultado.INCONCLUSIVO, ("a", "b:*")), "`INCONCLUSIVO` (`a`, `b:*`)"),
        (
            Estrago(Resultado.IGUAL_PELO_DECLARADO, ("c",)),
            "`IGUAL` pelo hash declarado (`c`)",
        ),
    ],
)
def test_o_texto_de_cada_resultado_e_o_do_runbook(estrago: Estrago, texto: str) -> None:
    assert estrago.texto == texto


def test_o_arquivo_se_escreve_com_a_raiz_e_o_padrao_e_so_a_raiz_quando_ela_e_o_arquivo() -> None:
    assert LEITURAS["config"].arquivo == "`<config>`"
    assert LEITURAS["relatorio"].arquivo == "`<raiz_saidas>/avaliacao/*/rep_*.json`"
    assert LEITURAS["rotulos"].arquivo == (
        "`catalog/labels/sia_pa.yaml` e `catalog/schemas/sia_pa_rotulos.yaml`"
    )


def test_o_runbook_traz_a_linha_de_cada_arquivo_que_a_cadeia_abre() -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    faltando = [c for c, leitura in LEITURAS.items() if _linha_do_arquivo(leitura) not in linhas]
    assert faltando == []


def test_o_runbook_traz_a_linha_dos_danos_de_cada_arquivo_que_se_estraga() -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    faltando = [
        c
        for c, leitura in LEITURAS.items()
        if leitura.estragos and _linha_do_dano(leitura) not in linhas
    ]
    assert faltando == []


def test_o_runbook_traz_por_que_cada_arquivo_nao_se_estraga() -> None:
    linhas = set(RUNBOOK.read_text(encoding="utf-8").splitlines())
    faltando = [
        c
        for c, leitura in LEITURAS.items()
        if leitura.sem_estrago and _linha_do_motivo(leitura) not in linhas
    ]
    assert faltando == []
