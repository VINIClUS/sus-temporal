"""Nenhuma comparação do `reproduce` perde diferença por interseção, padrão ou colapso (T14).

Varredura da família do P1 da rodada 6 (coluna de identidade projetada fora do hash): toda
comparação que projeta, filtra ou ignora colunas ou campos confere antes o conjunto completo.
Métrica repetida, campo só do congelamento, partição que só um lado traz, conjunto refeito que o
manifesto não tem, saída repetida e linhagem diferente com o mesmo conteúdo são diferença, nunca
igualdade. O que depende de caminho ou de instante fica de fora, e os testes dizem qual.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.evaluation import EvaluationReport, ValorMetrica
from sustemporal.contracts.experiment import (
    Ambiente,
    CodeVersion,
    EstadoExecucao,
    ModoExecucao,
    Particao,
    RunResult,
    SplitManifest,
    TipoExecucao,
)
from sustemporal.contracts.records import calcular_dataset_id
from sustemporal.contracts.temporal import MetodoId
from sustemporal.evaluation.freeze_entrada import identidades_da_entrada
from sustemporal.reporting.reproduce_comparacao import (
    Comparacao,
    Situacao,
    campos_que_diferem,
    comparar_conjuntos,
    comparar_insumos,
    comparar_metricas,
    comparar_referencia,
    comparar_relatorio,
    comparar_saida,
    comparar_saidas,
    comparar_split,
    saidas_por_esquema,
    saidas_por_metodo,
)
from sustemporal.reporting.reproduce_etapas import conferir_entradas
from tests.fixtures.protocolo_dados import cenario_baseline
from tests.fixtures.protocolo_insumos import conjunto_sintetico, entrada_da_politica
from tests.fixtures.reproducao_parquet import ARTEFATO, SCHEMA, gravar, linha

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.rules.entrada import EntradaValidacao

LINHAS = [linha("run_a", f"art_{i}#0") for i in range(4)]
OUTRO_ARTEFATO = "art_" + "b" * 64
HASH_OUTRO = "lh1:" + "0" * 64


def _metrica(nome: str, numerador: int, denominador: int) -> ValorMetrica:
    valor = (Decimal(numerador) / Decimal(denominador)).quantize(Decimal("0.000001"))
    return ValorMetrica(nome=nome, numerador=numerador, denominador=denominador, valor=valor)


def test_metrica_repetida_so_no_original_e_divergente_e_nao_some_no_dicionario() -> None:
    resultado = comparar_metricas(
        "metricas", [_metrica("m1", 1, 2), _metrica("m1", 1, 2)], [_metrica("m1", 1, 2)]
    )
    assert resultado.situacao is Situacao.DIVERGENTE
    assert (resultado.esperado, resultado.obtido) == ("2", "1")
    assert "faltando=1 sobrando=0" in resultado.detalhe


def test_metrica_repetida_so_no_refeito_e_divergente() -> None:
    resultado = comparar_metricas(
        "metricas", [_metrica("m1", 1, 2)], [_metrica("m1", 1, 2), _metrica("m1", 1, 2)]
    )
    assert resultado.situacao is Situacao.DIVERGENTE
    assert (resultado.esperado, resultado.obtido) == ("1", "2")
    assert "faltando=0 sobrando=1" in resultado.detalhe


def test_metricas_repetidas_com_valores_diferentes_nao_se_confundem() -> None:
    antigas = [_metrica("m1", 1, 4), _metrica("m1", 1, 2)]
    novas = [_metrica("m1", 1, 2), _metrica("m1", 1, 2)]
    resultado = comparar_metricas("metricas", antigas, novas)
    assert resultado.situacao is Situacao.DIVERGENTE
    assert "diferentes=1 faltando=0 sobrando=0" in resultado.detalhe


def test_metricas_repetidas_iguais_nos_dois_lados_sao_iguais_e_contam_cada_uma() -> None:
    antigas = [_metrica("m1", 1, 2), _metrica("m1", 1, 2), _metrica("m2", 3, 4)]
    resultado = comparar_metricas("metricas", antigas, list(reversed(antigas)))
    assert resultado.situacao is Situacao.IGUAL
    assert (resultado.esperado, resultado.obtido) == ("3", "3")


ITEM_RELATORIO = "relatorio:campos"
FREEZE = "frz_" + "a" * 64
OUTRO_FREEZE = "frz_" + "b" * 64
G2 = "experiments/decisions/g2.yaml"
INSTANTE = datetime(2026, 1, 1, tzinfo=UTC)


def _relatorio(**trocas: Any) -> EvaluationReport:
    campos: dict[str, Any] = {
        "report_id": "rep_" + "c" * 64,
        "modo": ModoExecucao.EXPLORATORIO,
        "origem_dados": OrigemDados.SINTETICO,
        "freeze_id": FREEZE,
        "runs": ("run_a", "run_b", "run_c"),
        "metricas": (_metrica("m1", 1, 2),),
        "notas": ("particao=CALIBRACAO",),
        "criado_em": INSTANTE,
        **trocas,
    }
    return EvaluationReport(**campos)


def test_relatorio_igual_e_igual_e_conta_os_campos_comparados() -> None:
    item = comparar_relatorio(ITEM_RELATORIO, _relatorio(), _relatorio())
    assert (item.item, item.situacao, item.detalhe) == (ITEM_RELATORIO, Situacao.IGUAL, "")
    assert item.esperado == item.obtido == "6 campos"


def test_relatorio_com_outro_id_outras_execucoes_e_outro_instante_e_igual() -> None:
    refeito = _relatorio(
        report_id="rep_" + "d" * 64,
        runs=("run_x", "run_y", "run_z"),
        criado_em=datetime(2027, 6, 1, tzinfo=UTC),
    )
    assert comparar_relatorio(ITEM_RELATORIO, _relatorio(), refeito).situacao is Situacao.IGUAL


def test_metricas_e_notas_ficam_para_os_itens_delas() -> None:
    refeito = _relatorio(metricas=(_metrica("m2", 1, 4),), notas=("outra",))
    assert comparar_relatorio(ITEM_RELATORIO, _relatorio(), refeito).situacao is Situacao.IGUAL


def test_relatorio_sem_o_original_e_inconclusivo() -> None:
    item = comparar_relatorio(ITEM_RELATORIO, None, _relatorio())
    assert (item.situacao, item.detalhe) == (Situacao.INCONCLUSIVO, "original_ausente")


@pytest.mark.parametrize(
    ("campo", "trocas"),
    [
        ("origem_dados", {"origem_dados": OrigemDados.REAL}),
        ("freeze_id", {"freeze_id": OUTRO_FREEZE}),
        ("decisao_g2", {"decisao_g2": G2}),
        ("runs", {"runs": ("run_a", "run_b")}),
    ],
)
def test_campo_do_relatorio_que_difere_e_divergente_e_nomeado(
    campo: str, trocas: dict[str, Any]
) -> None:
    item = comparar_relatorio(ITEM_RELATORIO, _relatorio(), _relatorio(**trocas))
    assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, f"campos={campo}")


def test_modo_do_relatorio_que_difere_e_divergente() -> None:
    confirmatorio = _relatorio(
        modo=ModoExecucao.CONFIRMATORIO, origem_dados=OrigemDados.REAL, decisao_g2=G2
    )
    exploratorio = _relatorio(origem_dados=OrigemDados.REAL)
    item = comparar_relatorio(ITEM_RELATORIO, confirmatorio, exploratorio)
    assert item.situacao is Situacao.DIVERGENTE
    assert item.detalhe == "campos=modo,decisao_g2"


def test_tabela_que_so_um_dos_relatorios_traz_e_divergente(tmp_path: Path) -> None:
    tabela = gravar(LINHAS, tmp_path / "t.parquet")
    com_tabela = _relatorio(tabelas=(tabela,))
    for esperado, obtido in ((com_tabela, _relatorio()), (_relatorio(), com_tabela)):
        item = comparar_relatorio(ITEM_RELATORIO, esperado, obtido)
        assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, "campos=tabelas")


def test_tabelas_se_comparam_por_esquema_linhas_e_hash_e_nao_por_caminho(tmp_path: Path) -> None:
    antiga = gravar(LINHAS, tmp_path / "original" / "t.parquet")
    nova = gravar(LINHAS, tmp_path / "refeito" / "t.parquet")
    item = comparar_relatorio(
        ITEM_RELATORIO, _relatorio(tabelas=(antiga,)), _relatorio(tabelas=(nova,))
    )
    assert item.situacao is Situacao.IGUAL
    outra = gravar(LINHAS[:-1], tmp_path / "outra" / "t.parquet")
    item = comparar_relatorio(
        ITEM_RELATORIO, _relatorio(tabelas=(antiga,)), _relatorio(tabelas=(outra,))
    )
    assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, "campos=tabelas")


def test_varios_campos_diferentes_saem_na_ordem_do_relatorio() -> None:
    refeito = _relatorio(freeze_id=OUTRO_FREEZE, runs=("run_a",), origem_dados=OrigemDados.REAL)
    item = comparar_relatorio(ITEM_RELATORIO, _relatorio(), refeito)
    assert item.detalhe == "campos=origem_dados,freeze_id,runs"


def test_campo_que_so_um_lado_tem_difere_mesmo_com_valor_nulo() -> None:
    assert campos_que_diferem({"a": None}, {}) == ["a"]
    assert campos_que_diferem({}, {"a": None}) == ["a"]


def test_campos_que_diferem_saem_na_ordem_do_primeiro_e_depois_os_so_do_segundo() -> None:
    assert campos_que_diferem({"a": 1, "b": 2, "z": 0}, {"c": 3, "b": 9, "a": 0, "y": 1}) == [
        "a",
        "b",
        "z",
        "c",
        "y",
    ]


def test_mapas_iguais_ou_vazios_nao_diferem() -> None:
    assert campos_que_diferem({"a": 1, "b": [2]}, {"b": [2], "a": 1}) == []
    assert campos_que_diferem({}, {}) == []


POLITICA = "B_ATEND"
AUSENTE_DA_ENTRADA = "campo_que_o_codigo_atual_nao_tem"


def _entrada() -> EntradaValidacao:
    return entrada_da_politica(conjunto_sintetico("sia_pa.v1", "teste"), POLITICA)


def test_insumos_com_campo_so_congelado_sao_divergentes_e_nomeiam_o_campo() -> None:
    entrada = _entrada()
    congeladas = {**identidades_da_entrada(entrada), AUSENTE_DA_ENTRADA: "h" * 64}
    item = comparar_insumos(f"insumos:{POLITICA}", congeladas, entrada)
    assert item.situacao is Situacao.DIVERGENTE
    assert item.detalhe == f"campos={AUSENTE_DA_ENTRADA}"


def test_insumos_com_campo_da_entrada_que_o_congelamento_nao_tem_seguem_divergentes() -> None:
    entrada = _entrada()
    congeladas = {k: v for k, v in identidades_da_entrada(entrada).items() if k != "cobertura"}
    item = comparar_insumos(f"insumos:{POLITICA}", congeladas, entrada)
    assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, "campos=cobertura")


def test_insumos_listam_primeiro_os_campos_da_entrada_e_depois_os_so_congelados() -> None:
    entrada = _entrada()
    identidades = identidades_da_entrada(entrada)
    congeladas = {**identidades, "selecoes": "h" * 64, AUSENTE_DA_ENTRADA: "h" * 64}
    item = comparar_insumos(f"insumos:{POLITICA}", congeladas, entrada)
    assert item.detalhe == f"campos=selecoes,{AUSENTE_DA_ENTRADA}"


def test_entrada_original_com_campo_so_congelado_nao_confere_e_e_alterada(tmp_path: Path) -> None:
    entrada = _entrada()
    pasta = tmp_path / "insumos"
    pasta.mkdir()
    (pasta / f"{POLITICA}.json").write_text(entrada.model_dump_json(), encoding="utf-8")
    congeladas = {POLITICA: {**identidades_da_entrada(entrada), AUSENTE_DA_ENTRADA: "h" * 64}}
    resultado = conferir_entradas(pasta, congeladas)
    assert resultado.conferidas == {}
    assert resultado.problemas == {POLITICA: "entrada_original_alterada"}


@pytest.fixture(scope="module")
def split(tmp_path_factory: pytest.TempPathFactory) -> SplitManifest:
    return cenario_baseline(tmp_path_factory.mktemp("split")).split


def _sem_particoes(split: SplitManifest) -> SplitManifest:
    return split.model_copy(update={"particoes": None, "rotulos_por_particao": None})


def _itens(esperado: SplitManifest, obtido: SplitManifest) -> dict[str, Comparacao]:
    return {c.item: c for c in comparar_split(esperado, obtido)}


def _do(itens: dict[str, Comparacao], nome: str) -> Comparacao:
    assert nome in itens, f"item={nome} itens={sorted(itens)}"
    return itens[nome]


def test_split_igual_traz_o_item_dos_campos_alem_do_id_das_particoes_e_dos_rotulos(
    split: SplitManifest,
) -> None:
    itens = _itens(split, split)
    assert set(itens) == {
        "split:split_id",
        "split:campos",
        *(f"split:particao:{p.value}" for p in Particao),
        *(f"split:rotulos:{p.value}" for p in Particao),
    }
    campos = _do(itens, "split:campos")
    assert campos.situacao is Situacao.IGUAL
    assert campos.esperado == campos.obtido == "9 campos"


def test_split_congelado_sem_particoes_deixa_as_refeitas_inconclusivas(
    split: SplitManifest,
) -> None:
    itens = _itens(_sem_particoes(split), split)
    for nome in ("particao", "rotulos"):
        for particao in Particao:
            item = _do(itens, f"split:{nome}:{particao.value}")
            assert (item.situacao, item.detalhe) == (
                Situacao.INCONCLUSIVO,
                "particao_nao_congelada",
            )
            assert (item.esperado, item.obtido) == (None, None)


def test_split_sem_particoes_dos_dois_lados_so_compara_o_id_e_os_campos(
    split: SplitManifest,
) -> None:
    sem = _sem_particoes(split)
    assert [c.item for c in comparar_split(sem, sem)] == ["split:split_id", "split:campos"]


def test_split_refeito_com_particao_que_o_congelado_nao_traz_e_divergente(
    split: SplitManifest,
) -> None:
    for campo, nome in (("particoes", "particao"), ("rotulos_por_particao", "rotulos")):
        refs = {p: r for p, r in (getattr(split, campo) or {}).items() if p is not Particao.TESTE}
        itens = _itens(split.model_copy(update={campo: refs}), split)
        a_mais = _do(itens, f"split:{nome}:TESTE")
        assert (a_mais.situacao, a_mais.detalhe) == (Situacao.DIVERGENTE, "particao_sem_original")
        assert (a_mais.esperado, a_mais.obtido) == (None, None)
        outras = [i for k, i in itens.items() if k.startswith(f"split:{nome}:") and i is not a_mais]
        assert {i.situacao for i in outras} == {Situacao.IGUAL}


def test_particao_so_do_refeito_vem_depois_das_congeladas(split: SplitManifest) -> None:
    refs = {p: r for p, r in (split.particoes or {}).items() if p is not Particao.CALIBRACAO}
    esperado = split.model_copy(update={"particoes": refs})
    nomes = [c.item for c in comparar_split(esperado, split) if c.item.startswith("split:particao")]
    assert nomes == [
        "split:particao:DESENVOLVIMENTO",
        "split:particao:TESTE",
        "split:particao:CALIBRACAO",
    ]


def _alterados(split: SplitManifest) -> dict[str, object]:
    primeiro, *demais = split.spec.intervalos
    adiantado = primeiro.model_copy(update={"inicio": "201001"})
    spec = split.spec.model_copy(update={"intervalos": (adiantado, *demais)})
    return {
        "spec": spec,
        "dataset_hash": HASH_OUTRO,
        "linhas_por_particao": {**split.linhas_por_particao, Particao.TESTE: 999},
        "hash_por_particao": {**split.hash_por_particao, Particao.TESTE: HASH_OUTRO},
        "artefatos_inspecionados": (*split.artefatos_inspecionados, OUTRO_ARTEFATO),
        "artefatos_teste": (OUTRO_ARTEFATO,),
        "cohort_id": "outra_coorte",
        "exclusoes": {"motivo_novo": 3},
        "limites": (*(split.limites or ()), "limite novo"),
    }


CAMPOS_DO_SPLIT = (
    "spec",
    "dataset_hash",
    "linhas_por_particao",
    "hash_por_particao",
    "artefatos_inspecionados",
    "artefatos_teste",
    "cohort_id",
    "exclusoes",
    "limites",
)


@pytest.mark.parametrize("campo", CAMPOS_DO_SPLIT)
def test_campo_do_split_que_difere_e_divergente_e_nomeado(split: SplitManifest, campo: str) -> None:
    outro = split.model_copy(update={campo: _alterados(split)[campo]})
    item = _do(_itens(split, outro), "split:campos")
    assert (item.situacao, item.detalhe) == (Situacao.DIVERGENTE, f"campos={campo}")
    assert item.esperado == item.obtido == "9 campos"


def test_todo_campo_do_split_fora_o_id_e_as_referencias_esta_entre_os_comparados() -> None:
    fora = {"split_id", "particoes", "rotulos_por_particao"}
    assert set(SplitManifest.model_fields) - fora == set(CAMPOS_DO_SPLIT)


def test_varios_campos_do_split_saem_na_ordem_do_contrato(split: SplitManifest) -> None:
    alterados = _alterados(split)
    outro = split.model_copy(update={c: alterados[c] for c in ("limites", "cohort_id", "spec")})
    assert _do(_itens(split, outro), "split:campos").detalhe == "campos=spec,cohort_id,limites"


def test_campo_do_split_so_do_refeito_nao_muda_o_id_nem_as_particoes(split: SplitManifest) -> None:
    outro = split.model_copy(update={"exclusoes": {"motivo_novo": 3}})
    itens = _itens(split, outro)
    assert _do(itens, "split:campos").situacao is Situacao.DIVERGENTE
    situacoes = {i: c.situacao for i, c in itens.items() if i != "split:campos"}
    assert set(situacoes.values()) == {Situacao.IGUAL}


def _conjunto(tmp_path: Path, nome: str) -> DatasetRef:
    return gravar(LINHAS, tmp_path / nome / "a.parquet")


def test_conjunto_refeito_que_o_manifesto_nao_traz_e_inconclusivo_e_nao_some(
    tmp_path: Path,
) -> None:
    congelado, refeito = _conjunto(tmp_path, "original"), _conjunto(tmp_path, "refeito")
    a_mais = refeito.model_copy(update={"schema_id": "sia_pa_rotulos.v1"})
    refeitos = {congelado.schema_id: refeito, "sia_pa_rotulos.v1": a_mais}
    itens = comparar_conjuntos([congelado], refeitos)
    assert [(i.item, i.situacao, i.detalhe) for i in itens] == [
        (f"conjunto:{congelado.schema_id}", Situacao.IGUAL, ""),
        ("conjunto:sia_pa_rotulos.v1", Situacao.INCONCLUSIVO, "conjunto_nao_congelado"),
    ]
    assert (itens[1].esperado, itens[1].obtido) == (None, None)


def test_manifesto_sem_nenhum_conjunto_deixa_todos_os_refeitos_inconclusivos(
    tmp_path: Path,
) -> None:
    refeito = _conjunto(tmp_path, "refeito")
    itens = comparar_conjuntos([], {"sia_pa.v1": refeito, "sia_pa_rotulos.v1": refeito})
    assert [(i.item, i.detalhe) for i in itens] == [
        ("conjunto:sia_pa.v1", "conjunto_nao_congelado"),
        ("conjunto:sia_pa_rotulos.v1", "conjunto_nao_congelado"),
    ]


def _execucao(metodo: MetodoId, saidas: Sequence[DatasetRef]) -> RunResult:
    return RunResult(
        run_id=f"val_{metodo.value.lower()}",
        tipo=TipoExecucao.VALIDACAO,
        metodo=metodo,
        modo=ModoExecucao.EXPLORATORIO,
        config_hash="a" * 64,
        codigo=CodeVersion(commit="abc", sujo=False, versao_pacote="0.1"),
        ambiente=Ambiente(python="3.12", plataforma="linux"),
        saidas=tuple(saidas),
        estado=EstadoExecucao.CONCLUIDA,
        iniciado_em=INSTANTE,
        origem_dados=OrigemDados.SINTETICO,
    )


def _saida(tmp_path: Path, pasta: str, run_id: str) -> DatasetRef:
    linhas = [{**item, "run_id": run_id} for item in LINHAS]
    return gravar(linhas, tmp_path / pasta / "s.parquet")


def test_saidas_do_mesmo_esquema_nao_se_colapsam_e_a_repeticao_ganha_sufixo(
    tmp_path: Path,
) -> None:
    a, b, c = (_saida(tmp_path, pasta, "run_a") for pasta in "abc")
    por_esquema = saidas_por_esquema([a, b, c])
    assert list(por_esquema) == [SCHEMA, f"{SCHEMA}#2", f"{SCHEMA}#3"]
    assert list(por_esquema.values()) == [a, b, c]


def test_saidas_de_esquemas_diferentes_ficam_pelo_proprio_esquema(tmp_path: Path) -> None:
    a = _saida(tmp_path, "a", "run_a")
    b = a.model_copy(update={"schema_id": "falhas.v1"})
    assert saidas_por_esquema([a, b]) == {SCHEMA: a, "falhas.v1": b}
    assert saidas_por_esquema([]) == {}


def test_saidas_por_metodo_indexa_pelo_valor_do_metodo_e_nao_colapsa_a_repeticao(
    tmp_path: Path,
) -> None:
    a, b = _saida(tmp_path, "a", "run_a"), _saida(tmp_path, "b", "run_a")
    execucoes = {
        MetodoId.M_TEMP: _execucao(MetodoId.M_TEMP, [a]),
        MetodoId.B_PROC: _execucao(MetodoId.B_PROC, [b, a]),
    }
    assert saidas_por_metodo(execucoes) == {
        "M_TEMP": {SCHEMA: a},
        "B_PROC": {SCHEMA: b, f"{SCHEMA}#2": a},
    }


def test_saida_repetida_so_no_original_diverge_como_ausente_no_refeito(tmp_path: Path) -> None:
    primeira, repetida = _saida(tmp_path, "o1", "run_a"), _saida(tmp_path, "o2", "run_a")
    refeita = _saida(tmp_path, "r1", "run_b")
    itens = comparar_saidas(
        "M_TEMP", saidas_por_esquema([primeira, repetida]), saidas_por_esquema([refeita])
    )
    assert {i.item: (i.situacao, i.detalhe) for i in itens} == {
        f"saida:M_TEMP:{SCHEMA}": (Situacao.IGUAL, "sem_colunas=run_id"),
        f"saida:M_TEMP:{SCHEMA}#2": (Situacao.DIVERGENTE, "saida_ausente_no_refeito"),
    }


def test_saida_repetida_so_no_refeito_diverge_como_sem_original(tmp_path: Path) -> None:
    original = _saida(tmp_path, "o1", "run_a")
    primeira, repetida = _saida(tmp_path, "r1", "run_b"), _saida(tmp_path, "r2", "run_b")
    itens = comparar_saidas(
        "M_TEMP", saidas_por_esquema([original]), saidas_por_esquema([primeira, repetida])
    )
    assert {i.item: (i.situacao, i.detalhe) for i in itens} == {
        f"saida:M_TEMP:{SCHEMA}": (Situacao.IGUAL, "sem_colunas=run_id"),
        f"saida:M_TEMP:{SCHEMA}#2": (Situacao.DIVERGENTE, "saida_sem_original"),
    }


def test_saida_repetida_com_conteudo_diferente_na_segunda_diverge(tmp_path: Path) -> None:
    iguais = [_saida(tmp_path, "o1", "run_a"), _saida(tmp_path, "o2", "run_a")]
    outra = gravar([linha("run_b", f"art_{i}#9") for i in range(4)], tmp_path / "r2" / "s.parquet")
    refeitas = [_saida(tmp_path, "r1", "run_b"), outra]
    itens = comparar_saidas("B_PROC", saidas_por_esquema(iguais), saidas_por_esquema(refeitas))
    assert [i.situacao for i in itens] == [Situacao.IGUAL, Situacao.DIVERGENTE]


def _com_artefatos(ref: DatasetRef, *artefatos: str) -> DatasetRef:
    ids = tuple(artefatos)
    novo = calcular_dataset_id(ref.schema_id, ref.hash_logico, ids)
    return ref.model_copy(update={"artifact_ids": ids, "dataset_id": novo})


def test_conjunto_refeito_com_o_mesmo_conteudo_e_outra_linhagem_e_divergente(
    tmp_path: Path,
) -> None:
    esperada = _conjunto(tmp_path, "original")
    obtida = _com_artefatos(_conjunto(tmp_path, "refeito"), ARTEFATO, OUTRO_ARTEFATO)
    item = comparar_referencia("conjunto:x", esperada, obtida)
    assert item.situacao is Situacao.DIVERGENTE
    assert item.detalhe == f"linhagem_diverge diferentes=1 primeiros={OUTRO_ARTEFATO}"
    assert (item.esperado, item.obtido) == ("artefatos=1", "artefatos=2")


def test_linhagem_so_do_original_tambem_diverge(tmp_path: Path) -> None:
    esperada = _com_artefatos(_conjunto(tmp_path, "original"), ARTEFATO, OUTRO_ARTEFATO)
    item = comparar_referencia("conjunto:x", esperada, _conjunto(tmp_path, "refeito"))
    assert item.detalhe == f"linhagem_diverge diferentes=1 primeiros={OUTRO_ARTEFATO}"


def test_linhagem_na_mesma_ordem_ou_em_outra_e_a_mesma(tmp_path: Path) -> None:
    esperada = _com_artefatos(_conjunto(tmp_path, "original"), ARTEFATO, OUTRO_ARTEFATO)
    obtida = _com_artefatos(_conjunto(tmp_path, "refeito"), OUTRO_ARTEFATO, ARTEFATO)
    assert comparar_referencia("conjunto:x", esperada, obtida).situacao is Situacao.IGUAL


def test_linhagem_repetida_de_um_lado_conta_como_diferenca(tmp_path: Path) -> None:
    esperada = _com_artefatos(_conjunto(tmp_path, "original"), ARTEFATO, ARTEFATO)
    obtida = _com_artefatos(_conjunto(tmp_path, "refeito"), ARTEFATO)
    item = comparar_referencia("conjunto:x", esperada, obtida)
    assert item.detalhe == f"linhagem_diverge diferentes=1 primeiros={ARTEFATO}"


def test_o_conteudo_diferente_vem_antes_da_linhagem(tmp_path: Path) -> None:
    esperada = _conjunto(tmp_path, "original")
    outro = gravar(LINHAS[:-1], tmp_path / "refeito" / "a.parquet")
    obtida = _com_artefatos(outro, ARTEFATO, OUTRO_ARTEFATO)
    assert comparar_referencia("conjunto:x", esperada, obtida).detalhe == "refeito_diverge"


def test_a_lista_de_artefatos_diferentes_sai_ordenada_e_truncada_em_cinco(tmp_path: Path) -> None:
    muitos = tuple("art_" + str(i) * 64 for i in range(7))
    esperada = _com_artefatos(_conjunto(tmp_path, "original"), ARTEFATO)
    obtida = _com_artefatos(_conjunto(tmp_path, "refeito"), ARTEFATO, *muitos)
    item = comparar_referencia("conjunto:x", esperada, obtida)
    assert item.detalhe == f"linhagem_diverge diferentes=7 primeiros={','.join(muitos[:5])}"


def test_saida_refeita_com_o_mesmo_conteudo_e_outra_linhagem_e_divergente(tmp_path: Path) -> None:
    original = _saida(tmp_path, "original", "run_a")
    refeita = _com_artefatos(_saida(tmp_path, "refeito", "run_b"), OUTRO_ARTEFATO)
    item = comparar_saida("saida:M_TEMP:x", original, refeita)
    assert item.situacao is Situacao.DIVERGENTE
    expected = f"linhagem_diverge diferentes=2 primeiros={ARTEFATO},{OUTRO_ARTEFATO}"
    assert item.detalhe == expected
    assert (item.esperado, item.obtido) == ("artefatos=1", "artefatos=1")


def test_saida_com_a_mesma_linhagem_segue_igual(tmp_path: Path) -> None:
    original = _saida(tmp_path, "original", "run_a")
    refeita = _saida(tmp_path, "refeito", "run_b")
    assert comparar_saida("saida:M_TEMP:x", original, refeita).situacao is Situacao.IGUAL
