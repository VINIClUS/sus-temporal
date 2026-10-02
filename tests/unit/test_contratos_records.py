import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import ValidationError

from sustemporal.contracts.base import (
    Confirmacao,
    FamiliaFonte,
    OrigemDados,
    Proveniencia,
    ValorNormalizado,
)
from sustemporal.contracts.records import (
    CampoLeiaute,
    ColunaCanonica,
    DatasetRef,
    EsquemaCanonico,
    FormatoLeiaute,
    LayoutSpec,
    PapelColuna,
    ProductionRecord,
    Reconciliacao,
    RowLocator,
    TipoCanonico,
    calcular_dataset_id,
)
from sustemporal.contracts.temporal import CompetenciaAtendimento, CompetenciaProcessamento

_A = f"art_{'a' * 64}"
_B = f"art_{'b' * 64}"
_C = f"art_{'c' * 64}"
_HASH = f"lh1:{'d' * 64}"
_COLUNAS_POR_PAPEL = {
    PapelColuna.CHAVE: "row_id",
    PapelColuna.LINHAGEM: "artifact_id",
    PapelColuna.ATRIBUTO: "idade",
    PapelColuna.ROTULO: "pa_indica",
    PapelColuna.DIAGNOSTICO: "motivo_glosa",
    PapelColuna.BRUTO: "idade_bruta",
    PapelColuna.MOTIVO: "idade_motivo",
}
_NOMES = [*_COLUNAS_POR_PAPEL.values(), "coluna_desconhecida"]
_MOTIVOS_EXCLUSAO = st.dictionaries(
    st.sampled_from(["deletado", "fora_do_recorte", "leiaute"]), st.integers(0, 50)
)


def _campo(**campos: object) -> CampoLeiaute:
    base = {
        "nome_fisico": "PA_CODUNI",
        "tipo_fisico": "C",
        "largura": 7,
        "nome_canonico": "cnes",
        "tipo_canonico": TipoCanonico.TEXTO,
        "papel": PapelColuna.CHAVE,
    }
    return CampoLeiaute.model_validate(base | campos)


def _leiaute(**campos: object) -> LayoutSpec:
    procedimento = _campo(
        nome_fisico="PA_PROC_ID", largura=10, nome_canonico="procedimento", papel="ATRIBUTO"
    )
    base = {
        "layout_id": "sia_pa_2018",
        "fonte": FamiliaFonte.SIA_PA,
        "versao": "1",
        "codificacao": "latin-1",
        "formato": FormatoLeiaute.DBF,
        "campos": (_campo(), procedimento),
        "proveniencia": Proveniencia.INFERIDA_PILOTO,
    }
    return LayoutSpec.model_validate(base | campos)


def _coluna(
    nome: str, papel: PapelColuna = PapelColuna.ATRIBUTO, **campos: object
) -> ColunaCanonica:
    base = {"nome": nome, "tipo": TipoCanonico.TEXTO, "papel": papel}
    return ColunaCanonica.model_validate(base | campos)


def _esquema(**campos: object) -> EsquemaCanonico:
    colunas = tuple(
        _coluna(nome, papel, anulavel=papel is not PapelColuna.CHAVE)
        for papel, nome in _COLUNAS_POR_PAPEL.items()
    )
    base = {"schema_id": "sia_pa.v1", "descricao": "producao", "chave": ("row_id",)}
    return EsquemaCanonico.model_validate(base | {"colunas": colunas} | campos)


def _dataset(artefatos: tuple[str, ...] = (_A, _B), **campos: object) -> DatasetRef:
    base = {
        "dataset_id": calcular_dataset_id("sia_pa.v1", _HASH, artefatos),
        "schema_id": "sia_pa.v1",
        "caminho": "data/canonical/sia_pa.parquet",
        "hash_logico": _HASH,
        "linhas": 10,
        "artifact_ids": artefatos,
        "origem_dados": OrigemDados.SINTETICO,
        "produzido_por": "run_ingestao",
    }
    return DatasetRef.model_validate(base | campos)


def _valor(texto: str) -> ValorNormalizado:
    return ValorNormalizado(bruto=texto, valor=texto)


def _registro(origem: RowLocator | None = None, **campos: object) -> ProductionRecord:
    origem = origem or RowLocator(artifact_id=_A, indice=0)
    base = {"row_id": origem.row_id(), "origem": origem, "instrumento": _valor("BPA_I")}
    return ProductionRecord.model_validate(base | campos)


def _reconciliacao(diferenca: int, **campos: object) -> Reconciliacao:
    explicadas = (
        campos["canonicas"] + campos["quarentena"] + sum(campos["excluidas_por_motivo"].values())
    )
    return Reconciliacao.model_validate({"fisicos": explicadas + diferenca} | campos)


def test_leiaute_rejeita_nome_fisico_repetido() -> None:
    campos = (_campo(), _campo(nome_canonico="cnes_executante"))
    with pytest.raises(ValidationError, match="leiaute_campos_vazios_ou_repetidos"):
        _leiaute(campos=campos)


def test_leiaute_rejeita_nome_canonico_repetido() -> None:
    campos = (_campo(), _campo(nome_fisico="PA_CODUNI2"))
    with pytest.raises(ValidationError, match="leiaute_nome_canonico_repetido"):
        _leiaute(campos=campos)


def test_leiaute_rejeita_lista_de_campos_vazia() -> None:
    with pytest.raises(ValidationError, match="leiaute_campos_vazios_ou_repetidos"):
        _leiaute(campos=())


def test_leiaute_rejeita_vigencia_invertida_e_aceita_um_mes() -> None:
    with pytest.raises(ValidationError, match="leiaute_vigencia_invertida"):
        _leiaute(valido_de="201902", valido_ate="201901")
    um_mes = _leiaute(valido_de="201901", valido_ate="201901")
    assert um_mes.valido_de == um_mes.valido_ate


def test_vigencia_do_leiaute_e_competencia_de_arquivo() -> None:
    with pytest.raises(ValidationError, match="tempo_incompativel"):
        _leiaute(valido_de=CompetenciaProcessamento("201801"))


def test_leiaute_nasce_a_confirmar() -> None:
    assert _leiaute().confirmacao is Confirmacao.A_CONFIRMAR


@pytest.mark.parametrize("papel", [PapelColuna.CHAVE, PapelColuna.LINHAGEM])
@pytest.mark.parametrize("tipo", [t for t in TipoCanonico if t is not TipoCanonico.TEXTO])
def test_campo_chave_ou_linhagem_deve_ser_texto(papel: PapelColuna, tipo: TipoCanonico) -> None:
    with pytest.raises(ValidationError, match="campo_codigo_deve_ser_texto"):
        _campo(papel=papel, tipo_canonico=tipo)


@pytest.mark.parametrize("tipo", list(TipoCanonico))
def test_campo_atributo_aceita_qualquer_tipo_canonico(tipo: TipoCanonico) -> None:
    assert _campo(papel=PapelColuna.ATRIBUTO, tipo_canonico=tipo).tipo_canonico is tipo


def test_campo_rejeita_largura_zero() -> None:
    with pytest.raises(ValidationError, match="campo_largura_invalida"):
        _campo(largura=0)


@pytest.mark.parametrize("chave", [("nao_existe",), ()])
def test_esquema_rejeita_chave_inexistente_ou_vazia(chave: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="esquema_chave_invalida"):
        _esquema(chave=chave)


def test_esquema_rejeita_chave_anulavel() -> None:
    colunas = (_coluna("row_id", PapelColuna.CHAVE, anulavel=True), _coluna("idade"))
    with pytest.raises(ValidationError, match="esquema_chave_anulavel"):
        _esquema(colunas=colunas)


def test_esquema_rejeita_coluna_repetida() -> None:
    colunas = (_coluna("row_id", PapelColuna.CHAVE, anulavel=False), _coluna("idade"))
    with pytest.raises(ValidationError, match="esquema_coluna_repetida"):
        _esquema(colunas=(*colunas, _coluna("idade", PapelColuna.ROTULO)))


@pytest.mark.parametrize("papel", list(PapelColuna))
def test_papel_de_coluna_conhecida_e_o_declarado(papel: PapelColuna) -> None:
    assert _esquema().papel_de(_COLUNAS_POR_PAPEL[papel]) is papel


@pytest.mark.parametrize("nome", ["coluna_desconhecida", "IDADE", ""])
def test_papel_de_coluna_desconhecida_e_diagnostico(nome: str) -> None:
    assert _esquema().papel_de(nome) is PapelColuna.DIAGNOSTICO


def test_colunas_com_papel_lista_apenas_o_papel_pedido() -> None:
    assert _esquema().colunas_com_papel(PapelColuna.ATRIBUTO) == ("idade",)
    assert _esquema().colunas_com_papel(PapelColuna.ROTULO) == ("pa_indica",)


@pytest.mark.parametrize("canonicas", [9, 11])
def test_reconciliacao_rejeita_linha_perdida_ou_inventada(canonicas: int) -> None:
    with pytest.raises(ValidationError, match="perda_inexplicada"):
        Reconciliacao(fisicos=10, canonicas=canonicas)


@pytest.mark.parametrize(
    "campos",
    [
        {"canonicas": 9, "quarentena": 1},
        {"canonicas": 8, "excluidas_por_motivo": {"deletado": 1, "fora_do_recorte": 1}},
        {"canonicas": 10, "deletados": 2},
    ],
)
def test_reconciliacao_aceita_perda_explicada(campos: dict[str, object]) -> None:
    assert Reconciliacao.model_validate({"fisicos": 10} | campos).fisicos == 10


def test_reconciliacao_rejeita_deletados_acima_dos_fisicos() -> None:
    with pytest.raises(ValidationError, match="deletados_maior_que_fisicos"):
        Reconciliacao(fisicos=1, canonicas=1, deletados=2)


@given(canonicas=st.integers(0, 50), quarentena=st.integers(0, 50), excluidas=_MOTIVOS_EXCLUSAO)
def test_reconciliacao_aceita_quando_toda_linha_e_explicada(
    canonicas: int, quarentena: int, excluidas: dict[str, int]
) -> None:
    campos = {"canonicas": canonicas, "quarentena": quarentena, "excluidas_por_motivo": excluidas}
    assert _reconciliacao(0, **campos).canonicas == canonicas


@given(
    canonicas=st.integers(0, 50),
    quarentena=st.integers(0, 50),
    excluidas=_MOTIVOS_EXCLUSAO,
    diferenca=st.integers(-3, 3).filter(bool),
)
def test_reconciliacao_rejeita_qualquer_diferenca_nao_explicada(
    canonicas: int, quarentena: int, excluidas: dict[str, int], diferenca: int
) -> None:
    assume(canonicas + quarentena + sum(excluidas.values()) + diferenca >= 0)
    campos = {"canonicas": canonicas, "quarentena": quarentena, "excluidas_por_motivo": excluidas}
    with pytest.raises(ValidationError, match="perda_inexplicada"):
        _reconciliacao(diferenca, **campos)


def test_dataset_id_e_derivado_do_conteudo() -> None:
    assert _dataset().dataset_id == calcular_dataset_id("sia_pa.v1", _HASH, (_A, _B))
    assert _dataset().dataset_id.startswith("ds_")


def test_dataset_rejeita_id_que_nao_corresponde() -> None:
    with pytest.raises(ValidationError, match="dataset_id_nao_corresponde"):
        _dataset(dataset_id=calcular_dataset_id("sia_pa.v1", _HASH, (_A,)))


@given(st.permutations([_A, _B, _C]))
def test_dataset_id_independe_da_ordem_dos_artefatos(ordem: list[str]) -> None:
    referencia = calcular_dataset_id("sia_pa.v1", _HASH, (_A, _B, _C))
    assert calcular_dataset_id("sia_pa.v1", _HASH, tuple(ordem)) == referencia
    assert _dataset(tuple(ordem)).dataset_id == referencia


@pytest.mark.parametrize(
    ("schema_id", "hash_logico"), [("sia_pa.v2", _HASH), ("sia_pa.v1", f"lh1:{'e' * 64}")]
)
def test_dataset_id_muda_com_esquema_ou_hash_logico(schema_id: str, hash_logico: str) -> None:
    assert calcular_dataset_id(schema_id, hash_logico, (_A,)) != calcular_dataset_id(
        "sia_pa.v1", _HASH, (_A,)
    )


def test_row_id_identifica_artefato_membro_e_posicao() -> None:
    assert RowLocator(artifact_id=_A, indice=7).row_id() == f"{_A}#7"
    com_membro = RowLocator(artifact_id=_A, membro="PASP1801.dbf", indice=7)
    assert com_membro.row_id() == f"{_A}/PASP1801.dbf#7"


@pytest.mark.parametrize("membro", ["PA#1.dbf", "PA SP.dbf", "dir/PASP.dbf", ""])
def test_membro_rejeita_separadores_do_row_id(membro: str) -> None:
    with pytest.raises(ValidationError):
        RowLocator(artifact_id=_A, membro=membro, indice=0)


@pytest.mark.parametrize("row_id", [f"{_A}#1", f"{_B}#0", f"{_A}/PASP1801.dbf#0", f"{_A}#00"])
def test_registro_rejeita_row_id_incoerente_com_origem(row_id: str) -> None:
    with pytest.raises(ValidationError, match="row_id_incoerente_com_origem"):
        _registro(row_id=row_id)


def test_registro_com_membro_exige_membro_no_row_id() -> None:
    origem = RowLocator(artifact_id=_A, membro="PASP1801.dbf", indice=3)
    assert _registro(origem).row_id == f"{_A}/PASP1801.dbf#3"
    with pytest.raises(ValidationError, match="row_id_incoerente_com_origem"):
        _registro(origem, row_id=f"{_A}#3")


def test_linhas_repetidas_preservam_multiplicidade() -> None:
    registros = [
        _registro(RowLocator(artifact_id=_A, indice=indice), procedimento="0301010072")
        for indice in range(3)
    ]
    conteudo = registros[0].model_dump(exclude={"row_id", "origem"})
    assert len({registro.row_id for registro in registros}) == 3
    assert all(r.model_dump(exclude={"row_id", "origem"}) == conteudo for r in registros)


def test_registro_mantem_competencias_de_tipos_distintos() -> None:
    registro = _registro(competencia_atendimento="201712", competencia_processamento="201801")
    assert type(registro.competencia_atendimento) is CompetenciaAtendimento
    assert type(registro.competencia_processamento) is CompetenciaProcessamento
    with pytest.raises(ValidationError, match="tempo_incompativel"):
        _registro(competencia_atendimento=CompetenciaProcessamento("201801"))


def test_registro_mantem_codigos_como_texto() -> None:
    registro = _registro(cnes="0012345", procedimento="0301010072", cbo="2231F9")
    assert (registro.cnes, registro.procedimento) == ("0012345", "0301010072")
    for campo, valor in (("cnes", 12345), ("procedimento", 301010072), ("cbo", 225125)):
        with pytest.raises(ValidationError):
            _registro(**{campo: valor})


def test_filtrar_atributos_mantem_apenas_colunas_atributo() -> None:
    valores = {nome: _valor("x") for nome in _NOMES}
    assert set(ProductionRecord.filtrar_atributos(valores, _esquema())) == {"idade"}


@given(st.sets(st.sampled_from(_NOMES)))
def test_filtrar_atributos_nunca_repassa_rotulo_diagnostico_ou_desconhecida(
    nomes: set[str],
) -> None:
    filtrados = ProductionRecord.filtrar_atributos({n: _valor("x") for n in nomes}, _esquema())
    assert set(filtrados) == nomes & {"idade"}
