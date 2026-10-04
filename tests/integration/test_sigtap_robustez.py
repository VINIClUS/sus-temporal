"""T04: robustez da leitura do SIGTAP (zip corrompido, leiaute, competência; SINTETICO)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tests.fixtures.sigtap_apoio import (
    leiautes,
    ler_linhas,
    normalizar,
    pacote,
    quarentena,
    runtime,
)
from tests.fixtures.sigtap_zip import (
    COLUNAS,
    artefato_sigtap,
    colunas_com_valor,
    corromper,
    membros_tabela,
    pacote_padrao,
    registro_procedimento,
    zip_sigtap,
)

from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.ingest.sigtap import TABELAS, normalize_sigtap

_ESPERADAS = (QuarentenaLeitura, ArquivoAusente)


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(posicao=st.integers(min_value=0, max_value=10_000), mascara=st.integers(1, 255))
def test_zip_corrompido_so_vira_quarentena_ou_ausencia(
    tmp_path_factory: pytest.TempPathFactory, posicao: int, mascara: int
) -> None:
    pasta = tmp_path_factory.mktemp("corrompido")
    original = zip_sigtap(pacote_padrao())
    artefato = artefato_sigtap(pasta, corromper(original, posicao, mascara), declarado=original)
    for tabela in TABELAS:
        try:
            normalizar(pasta, artefato, tabela)
        except _ESPERADAS:
            continue


def test_membro_deflate_corrompido_vai_para_quarentena(tmp_path: Path) -> None:
    original = zip_sigtap(pacote_padrao())
    inicio = original.index(b"tb_procedimento.txt") + len("tb_procedimento.txt")
    corrompido = original[:inicio] + bytes(b ^ 0x5A for b in original[inicio : inicio + 40])
    corrompido += original[inicio + 40 :]
    artefato = artefato_sigtap(tmp_path, corrompido, declarado=original)
    with pytest.raises(QuarentenaLeitura):
        normalizar(tmp_path, artefato, "tb_procedimento")


def test_artefato_sem_competencia_vai_para_quarentena(tmp_path: Path) -> None:
    artefato = artefato_sigtap(tmp_path, zip_sigtap(pacote_padrao()), competencia=None)
    with pytest.raises(QuarentenaLeitura, match="competencia_divergente"):
        normalizar(tmp_path, artefato, "tb_registro")


def test_largura_uma_acima_da_maxima_vai_para_quarentena(tmp_path: Path) -> None:
    procedimento = registro_procedimento("0101010010", "201801")
    membros = membros_tabela("tb_procedimento", [procedimento], colunas_com_valor(13))
    assert "largura_acima_da_maxima" in quarentena(tmp_path, membros, "tb_procedimento").motivo


@pytest.mark.parametrize("campo", ["QT_PONTOS", "VL_SH"])
def test_numero_com_sinal_vai_para_quarentena(tmp_path: Path, campo: str) -> None:
    procedimento = registro_procedimento("0101010010", "201801", **{campo: "-001"})
    erro = quarentena(
        tmp_path, membros_tabela("tb_procedimento", [procedimento]), "tb_procedimento"
    )
    assert "numero_invalido" in erro.motivo


def test_idade_com_sinal_vira_codificacao_invalida(tmp_path: Path) -> None:
    procedimento = registro_procedimento("0101010010", "201801", VL_IDADE_MINIMA="-001")
    membros = membros_tabela("tb_procedimento", [procedimento])
    linhas = ler_linhas(normalizar(tmp_path, pacote(tmp_path, membros), "tb_procedimento"))
    assert linhas[0]["vl_idade_minima_motivo"] == "CODIFICACAO_INVALIDA"


def test_campo_opcional_ausente_do_zip_vira_nulo(tmp_path: Path) -> None:
    layout = leiautes()["tb_registro"]
    campos = tuple(
        c.model_copy(update={"obrigatorio": False}) if c.nome_fisico == "NO_REGISTRO" else c
        for c in layout.campos
    )
    opcional = layout.model_copy(update={"campos": campos})
    colunas = tuple(c for c in COLUNAS["tb_registro"] if c.nome != "NO_REGISTRO")
    registro = {"CO_REGISTRO": "01", "DT_COMPETENCIA": "201801"}
    artefato = pacote(tmp_path, membros_tabela("tb_registro", [registro], colunas))
    saida = tmp_path / "saida"
    dataset = normalize_sigtap(artefato, opcional, saida, runtime=runtime(tmp_path))
    assert [(x["co_registro"], x["no_registro"]) for x in ler_linhas(dataset)] == [("01", None)]


def test_caminho_relativo_a_raiz_de_dados_e_aceito(tmp_path: Path) -> None:
    artefato = pacote(tmp_path, pacote_padrao())
    relativo = Path(artefato.caminho_conteudo).relative_to(tmp_path)
    copia = artefato.model_copy(update={"caminho_conteudo": str(relativo)})
    assert normalizar(tmp_path, copia, "tb_registro").linhas == 3
