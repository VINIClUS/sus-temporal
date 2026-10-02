"""Catálogo: chave da cobertura por base temporal e descrição da abstenção no agregado."""

from pathlib import Path

from sustemporal.contracts import EsquemaCanonico, PapelColuna, TipoCanonico

ESQUEMAS = Path(__file__).resolve().parents[2] / "catalog" / "schemas"


def test_cobertura_distingue_a_base_temporal_na_chave() -> None:
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / "cobertura.yaml")
    assert esquema.chave == ("familia_regra", "instrumento", "competencia", "base_temporal")
    coluna = next(coluna for coluna in esquema.colunas if coluna.nome == "base_temporal")
    assert (coluna.papel, coluna.tipo, coluna.anulavel) == (
        PapelColuna.CHAVE,
        TipoCanonico.TEXTO,
        False,
    )
    assert "ATENDIMENTO" in coluna.descricao
    assert "PROCESSAMENTO" in coluna.descricao


def test_agregado_descreve_abstencao_como_o_contrato() -> None:
    descricao = " ".join(
        EsquemaCanonico.de_yaml(ESQUEMAS / "agregados_registro.yaml").descricao.split()
    )
    assert "ABSTENCAO é ausência de violação com ao menos uma inconclusiva ou nenhuma conforme" in (
        descricao
    )
