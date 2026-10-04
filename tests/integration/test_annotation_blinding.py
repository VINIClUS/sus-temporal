"""Anotação humana cega (T12) sobre cenário SINTETICO."""

from __future__ import annotations

import argparse
import inspect
import json
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from tests.fixtures.anotacao_cenario import CenarioAnotacao, montar_cenario, registro
from tests.fixtures.regras_cenario import reemitir
from tests.fixtures.sintetico.contratos import features_sinteticas

from sustemporal.contracts import (
    Ambiente,
    AnnotationSample,
    AvaliacaoCaso,
    BootstrapSpec,
    CodeVersion,
    ConclusaoCaso,
    CorrecaoMultiplicidade,
    EstadoReferencia,
    FamiliaRegra,
    FreezeManifest,
    Particao,
    ReferenciaHumana,
    RuntimeConfig,
)
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro
from sustemporal.evaluation.annotation import (
    COLUNAS_PACOTE,
    DIMENSOES_OBSERVAVEIS,
    FORMULARIO_VERSAO,
    carregar_mapa,
    prepare_annotation_sample,
)
from sustemporal.evaluation.annotation_cli import executar_annotation_export
from sustemporal.evaluation.annotation_concordancia import (
    ReferenciaNaoFechada,
    comparar_com_motor,
    concordancia,
    estimar_horas,
    fechar_referencia,
    kappa_cohen,
)
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from pathlib import Path

ESQUEMAS_DO_MOTOR = ("avaliacoes.v1", "agregados_registro.v1", "evidencias.v1")
TERMOS_DO_MOTOR = ("VIOLACAO", "CONFORME", "INCONCLUSIVO", "NAO_APLICAVEL", "explicacao")
P = FamiliaRegra.PROCEDIMENTO_CBO
E = FamiliaRegra.ESTABELECIMENTO_CBO
IDENT = ConclusaoCaso.INCOMPATIBILIDADE_IDENTIFICADA
IND = ConclusaoCaso.CAUSA_INDETERMINADA
FORA = ConclusaoCaso.CAUSA_FORA_DE_ESCOPO_DOCUMENTADA


@pytest.fixture
def cenario(tmp_path: Path) -> CenarioAnotacao:
    return montar_cenario(tmp_path / "dados")


def _preparar(
    cenario: CenarioAnotacao,
    out: Path,
    *,
    tamanho: int = 400,
    tamanho_treino: int = 20,
    dimensoes: tuple[str, ...] = DIMENSOES_OBSERVAVEIS,
) -> AnnotationSample:
    return prepare_annotation_sample(
        cenario.labels,
        cenario.split,
        cenario.config,
        out,
        particoes=cenario.particoes,
        tamanho=tamanho,
        tamanho_treino=tamanho_treino,
        dimensoes=dimensoes,
    )


def _rejeicoes_teste(cenario: CenarioAnotacao) -> set[str]:
    rotulos = pq.read_table(cenario.labels.caminho).to_pylist()
    teste = {str(linha["row_id"]) for linha in cenario.linhas_teste}
    return {str(r["row_id"]) for r in rotulos if r["rotulo"] == "NAO_APROVADO"} & teste


def _textos_do_pacote(out: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((out / "pacote").iterdir())}


def _colunas_dos_casos(out: Path) -> set[str]:
    colunas: set[str] = set()
    for nome in ("casos.json", "treino.json"):
        dados = json.loads((out / "pacote" / nome).read_text(encoding="utf-8"))
        for caso in dados["casos"]:
            colunas |= set(caso)
    return colunas


def test_pacote_nao_contem_resultados_explicacoes_nem_identificadores(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out)
    colunas = _colunas_dos_casos(out)
    assert colunas <= {"caso_id", "rotulo", *COLUNAS_PACOTE}
    do_motor = {c.nome for s in ESQUEMAS_DO_MOTOR for c in carregar_esquema(s).colunas}
    assert not colunas & (do_motor - {"row_id"} - set(COLUNAS_PACOTE))
    for proibida in ("row_id", "artifact_id", "indice_registro", "membro", "pa_munpcn"):
        assert proibida not in colunas
        assert proibida in amostra.colunas_excluidas
    textos = "\n".join(_textos_do_pacote(out).values())
    for linha in cenario.linhas_teste:
        assert str(linha["row_id"]) not in textos
        assert str(linha["artifact_id"]) not in textos
    for termo in TERMOS_DO_MOTOR:
        assert termo not in textos


def test_coluna_do_motor_no_parquet_nao_chega_ao_pacote(tmp_path: Path) -> None:
    linhas = [
        registro(f"t{i:05d}", f"art_{'2' * 64}", i, competencia_processamento="202405")
        for i in range(40)
    ]
    cenario = montar_cenario(tmp_path / "dados", linhas_teste=linhas)

    caminho = cenario.particoes[Particao.TESTE].caminho
    tabela = pq.read_table(caminho)
    tabela = tabela.append_column("resultado", pa.array(["VIOLACAO"] * tabela.num_rows))
    tabela = tabela.append_column("explicacao", pa.array(["regra x"] * tabela.num_rows))
    pq.write_table(tabela, caminho)
    out = tmp_path / "anotacao"
    _preparar(cenario, out, tamanho=10, tamanho_treino=2, dimensoes=("instrumento",))
    textos = "\n".join(_textos_do_pacote(out).values())
    assert "VIOLACAO" not in textos
    assert "explicacao" not in textos
    assert "resultado" not in _colunas_dos_casos(out)


def test_formulario_versionado_admite_multiplas_e_indeterminacao(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out)
    formulario = json.loads((out / "pacote" / "formulario.json").read_text(encoding="utf-8"))
    assert formulario["versao"] == FORMULARIO_VERSAO == amostra.formulario_versao
    assert set(formulario["conclusoes"]) == {c.value for c in ConclusaoCaso}
    assert formulario["familias_multiplas"] is True
    assert set(formulario["familias"]) == {f.value for f in FamiliaRegra}
    multipla = AvaliacaoCaso(
        caso_id="caso_0001",
        avaliador="a",
        conclusao=ConclusaoCaso.INCOMPATIBILIDADE_IDENTIFICADA,
        familias=(P, E),
    )
    assert multipla.familias == (P, E)
    with pytest.raises(ValueError, match="avaliacao_familias_incoerentes"):
        AvaliacaoCaso(
            caso_id="caso_0001",
            avaliador="a",
            conclusao=ConclusaoCaso.CAUSA_INDETERMINADA,
            familias=(P,),
        )


def test_probabilidades_de_inclusao_coerentes(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out)
    rejeicoes = _rejeicoes_teste(cenario)
    assert sum(e.populacao for e in amostra.estratos) == len(rejeicoes)
    assert len(amostra.casos) == 400
    assert set(amostra.casos) <= rejeicoes
    estratos = json.loads((out / "privado" / "estratos.json").read_text(encoding="utf-8"))
    por_estrato = Counter(estratos[row_id] for row_id in amostra.casos)
    for estrato in amostra.estratos:
        assert estrato.amostra >= 1
        assert por_estrato[estrato.nome] == estrato.amostra
        assert estrato.prob_inclusao == (
            Decimal(estrato.amostra) / Decimal(estrato.populacao)
        ).quantize(estrato.prob_inclusao)
    populacao = Counter(estratos[r] for r in rejeicoes)
    assert {e.nome: e.populacao for e in amostra.estratos} == dict(populacao)
    assert amostra.dimensoes_estrato == DIMENSOES_OBSERVAVEIS


def test_estrato_pelo_resultado_do_metodo_e_recusado(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    for dimensao in ("resultado", "violacoes", "explicacao"):
        with pytest.raises(ValueError, match="dimensao_nao_observavel"):
            _preparar(cenario, tmp_path / dimensao, dimensoes=("instrumento", dimensao))


def test_censo_inclui_toda_rejeicao_sem_olhar_o_motor(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    amostra = _preparar(cenario, tmp_path / "anotacao", tamanho=5000)
    assert set(amostra.casos) == _rejeicoes_teste(cenario)
    assert all(e.prob_inclusao == 1 for e in amostra.estratos)
    nomes = set(inspect.signature(prepare_annotation_sample).parameters)
    assert not nomes & {"run", "avaliacoes", "explicacoes", "resultado"}


def test_semente_da_config_determina_a_amostra(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    primeira = _preparar(cenario, tmp_path / "a")
    segunda = _preparar(cenario, tmp_path / "b")
    assert primeira == segunda
    outra = cenario.config.model_copy(update={"semente": 7})
    terceira = prepare_annotation_sample(
        cenario.labels, cenario.split, outra, tmp_path / "c", particoes=cenario.particoes
    )
    assert terceira.semente == 7
    assert terceira.casos != primeira.casos


def test_treino_excluido_da_amostra_final(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out, tamanho=12, tamanho_treino=5, dimensoes=("instrumento",))
    assert len(amostra.casos_treino) == 5
    assert not set(amostra.casos) & set(amostra.casos_treino)
    assert all(row_id.startswith("d") for row_id in amostra.casos_treino)
    mapa = carregar_mapa(out)
    treino = [c for c, r in mapa.items() if r in amostra.casos_treino]
    assert treino
    assert all(c.startswith("treino_") for c in treino)
    finais = sorted(c for c in mapa if c.startswith("caso_"))
    a = [_avaliacao(c, "a", ConclusaoCaso.CAUSA_INDETERMINADA) for c in finais]
    b = [_avaliacao(c, "b", ConclusaoCaso.CAUSA_INDETERMINADA) for c in finais]
    a.append(_avaliacao(treino[0], "a", ConclusaoCaso.CAUSA_INDETERMINADA))
    with pytest.raises(ValueError, match="caso_de_treino_na_avaliacao_final"):
        concordancia(amostra, mapa, a, b)


def _avaliacao(
    caso: str, avaliador: str, conclusao: ConclusaoCaso, *familias: FamiliaRegra
) -> AvaliacaoCaso:
    return AvaliacaoCaso(
        caso_id=caso, avaliador=avaliador, conclusao=conclusao, familias=tuple(familias)
    )


def test_kappa_conferido_a_mao() -> None:
    pares = [("S", "S")] * 4 + [("S", "N")] + [("N", "S")] * 2 + [("N", "N")] * 3
    # po = 7/10; pe = (5/10)(6/10) + (5/10)(4/10) = 1/2; κ = (7/10 - 1/2) / (1/2) = 2/5
    assert kappa_cohen(pares) == Fraction(2, 5)
    assert kappa_cohen([("S", "S")] * 3) is None
    assert kappa_cohen([("S", "N"), ("N", "S")]) == Fraction(-1)


def _anotacoes(out: Path, amostra: AnnotationSample) -> tuple[list[str], dict[str, str]]:
    mapa = carregar_mapa(out)
    finais = sorted(c for c, r in mapa.items() if r in amostra.casos)
    return finais, mapa


def test_concordancia_global_e_por_familia_preserva_indeterminados(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out, tamanho=10, tamanho_treino=2, dimensoes=("instrumento",))
    casos, mapa = _anotacoes(out, amostra)
    a = [_avaliacao(c, "a", IDENT, P) for c in casos[:4]] + [_avaliacao(casos[4], "a", IDENT, P, E)]
    a += [_avaliacao(c, "a", IND) for c in casos[5:8]]
    a += [_avaliacao(c, "a", FORA) for c in casos[8:]]
    b = [_avaliacao(c, "b", IDENT, P) for c in casos[:3]] + [_avaliacao(casos[3], "b", IND)]
    b += [_avaliacao(casos[4], "b", IDENT, P, E)] + [_avaliacao(c, "b", IND) for c in casos[5:8]]
    b += [_avaliacao(casos[8], "b", FORA), _avaliacao(casos[9], "b", IDENT, E)]
    relatorio = concordancia(amostra, mapa, a, b)
    assert relatorio.casos == 10
    # conclusões: I/I x4, I/IND x1, IND/IND x3, FORA/FORA x1, FORA/I x1 -> po = 8/10
    # (conclusão, famílias): A: I:P=4, I:PE=1, IND=3, FORA=2; B: I:P=3, I:PE=1, IND=4, FORA=1,
    # I:E=1 -> pe = (12 + 1 + 12 + 2)/100 = 27/100
    assert relatorio.bruta == Fraction(8, 10)
    assert relatorio.kappa == (Fraction(8, 10) - Fraction(27, 100)) / (1 - Fraction(27, 100))
    bruta_p, _ = relatorio.por_familia[P.value]
    # P: PRESENTE/PRESENTE x4, PRESENTE/NAO_DETERMINADO x1, ND/ND x3, AUSENTE/AUSENTE x1,
    # AUSENTE/AUSENTE (FORA vs I com E) x1 -> po = 9/10
    assert bruta_p == Fraction(9, 10)
    assert set(relatorio.por_familia) == {P.value, E.value}


def test_comparacao_bloqueada_antes_do_fechamento(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out, tamanho=4, tamanho_treino=1, dimensoes=("instrumento",))
    casos, mapa = _anotacoes(out, amostra)
    a = [_avaliacao(casos[0], "a", IDENT, P), _avaliacao(casos[1], "a", IND)]
    a += [_avaliacao(casos[2], "a", FORA), _avaliacao(casos[3], "a", IDENT, P)]
    b = [_avaliacao(casos[0], "b", IDENT, P), _avaliacao(casos[1], "b", IND)]
    b += [_avaliacao(casos[2], "b", FORA), _avaliacao(casos[3], "b", IDENT, E)]
    aberta = fechar_referencia(amostra, mapa, a, b)
    assert aberta.estado is EstadoReferencia.ABERTA
    assert aberta.pendentes == (casos[3],)
    motor = {mapa[c]: frozenset({P}) for c in casos}
    with pytest.raises(ReferenciaNaoFechada):
        comparar_com_motor(aberta, motor)
    adjudicada = _avaliacao(casos[3], "adj", IDENT, P, E)
    fechada = fechar_referencia(amostra, mapa, a, b, [adjudicada])
    assert fechada.estado is EstadoReferencia.FECHADA
    assert fechada.casos[mapa[casos[1]]].conclusao is IND
    contagens = comparar_com_motor(fechada, motor)
    assert contagens["IGUAL"] == 1
    assert contagens["PARCIAL"] == 1
    assert contagens["CAUSA_INDETERMINADA"] == 1
    assert contagens["MOTOR_ATRIBUI_FAMILIA_FORA_DE_ESCOPO"] == 1
    assert sum(contagens.values()) == 4
    nomes = set(inspect.signature(fechar_referencia).parameters)
    assert not nomes & {"explicacoes", "familias_motor", "run"}


def test_estimativa_de_esforco_e_planejamento() -> None:
    assert estimar_horas(Fraction(5)) == Fraction(2 * 400 * 5, 60)
    assert estimar_horas(Fraction(10), casos=12) == Fraction(2 * 12 * 10, 60)


def test_particao_divergente_do_split_e_recusada(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    trocadas = dict(cenario.particoes)
    trocadas[Particao.TESTE] = cenario.particoes[Particao.DESENVOLVIMENTO]
    with pytest.raises(ValueError, match="particao_diverge_do_split"):
        prepare_annotation_sample(
            cenario.labels, cenario.split, cenario.config, tmp_path / "x", particoes=trocadas
        )


def test_parquet_alterado_e_falha_operacional(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    caminho = cenario.particoes[Particao.TESTE].caminho
    tabela = pq.read_table(caminho)
    pq.write_table(tabela.slice(1), caminho)
    with pytest.raises(FalhaOperacionalErro, match="anotacao_entrada_ilegivel_ou_divergente"):
        _preparar(cenario, tmp_path / "x")


def test_sem_particoes_materializadas_e_config_invalida(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    with pytest.raises(ConfigInvalida, match="anotacao_sem_particao"):
        prepare_annotation_sample(cenario.labels, cenario.split, cenario.config, tmp_path / "x")


def _congelar(cenario: CenarioAnotacao, diretorio: Path) -> FreezeManifest:
    sha = "e" * 64
    manifesto = FreezeManifest.criar(
        criado_em=datetime(2026, 1, 1, tzinfo=UTC),
        config_hash=sha,
        codigo=CodeVersion(commit="abc", sujo=False, versao_pacote="0.1"),
        ambiente=Ambiente(python="3.12", plataforma="linux"),
        catalogos_sha256={"regras": sha},
        datasets=(cenario.completo, cenario.labels, *cenario.particoes.values()),
        split=cenario.split,
        features=features_sinteticas(),
        bootstrap=BootstrapSpec(correcao=CorrecaoMultiplicidade.HOLM),
        metricas=("cobertura_rejeicoes",),
        comparacoes_primarias=("M_TEMP_x_B_ATEND",),
        decisao_g0="experiments/decisions/G0.yaml",
    )
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / f"{manifesto.freeze_id}.json").write_text(
        manifesto.model_dump_json(), encoding="utf-8"
    )
    return manifesto


def test_annotation_export_resolve_artefatos_exatos_do_congelamento(
    cenario: CenarioAnotacao, tmp_path: Path
) -> None:
    congelamentos = tmp_path / "frozen"
    manifesto = _congelar(cenario, congelamentos)
    runtime = RuntimeConfig(
        dir_congelamentos=str(congelamentos), raiz_saidas=str(tmp_path / "saidas")
    )
    config = cenario.config.model_copy(update={"runtime": runtime})
    args = argparse.Namespace(comando="annotation-export", freeze=manifesto.freeze_id)
    assert executar_annotation_export(args, config) == 0
    destino = tmp_path / "saidas" / "anotacao" / manifesto.freeze_id
    amostra = AnnotationSample.model_validate_json(
        (destino / "amostra.json").read_text(encoding="utf-8")
    )
    assert amostra.freeze_id == manifesto.freeze_id
    assert len(amostra.casos) == 400
    ausente = argparse.Namespace(comando="annotation-export", freeze=f"frz_{'0' * 64}")
    with pytest.raises(ConfigInvalida, match="congelamento_ausente"):
        executar_annotation_export(ausente, config)


def test_particao_sem_rejeicoes_falha_em_vez_de_amostra_vazia(tmp_path: Path) -> None:
    linhas = [registro(f"t{i:05d}", f"art_{'2' * 64}", i) for i in range(4)]
    cenario = montar_cenario(tmp_path / "dados", linhas_teste=linhas)
    tabela = pq.read_table(cenario.labels.caminho)
    teste = {str(linha["row_id"]) for linha in linhas}
    novos = [
        {**r, "rotulo": "APROVADO_TOTAL"} if r["row_id"] in teste else r for r in tabela.to_pylist()
    ]
    pq.write_table(pa.Table.from_pylist(novos, tabela.schema), cenario.labels.caminho)
    cenario = replace(cenario, labels=reemitir(cenario.labels))
    with pytest.raises(ValueError, match="anotacao_sem_rejeicoes"):
        _preparar(cenario, tmp_path / "x", dimensoes=("instrumento",))
    assert not (tmp_path / "x" / "amostra.json").exists()


def test_concordancia_global_considera_familias(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out, tamanho=4, tamanho_treino=1, dimensoes=("instrumento",))
    casos, mapa = _anotacoes(out, amostra)
    a = [_avaliacao(c, "a", IDENT, P) for c in casos]
    b = [_avaliacao(c, "b", IDENT, E) for c in casos]
    assert concordancia(amostra, mapa, a, b).bruta == 0


def test_adjudicador_nao_pode_ser_avaliador(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    amostra = _preparar(cenario, out, tamanho=4, tamanho_treino=1, dimensoes=("instrumento",))
    casos, mapa = _anotacoes(out, amostra)
    a = [_avaliacao(c, "a", IDENT, P) for c in casos]
    b = [_avaliacao(c, "b", IDENT, E) for c in casos]
    with pytest.raises(ValueError, match="adjudicador_nao_independente"):
        fechar_referencia(amostra, mapa, a, b, [_avaliacao(casos[0], "a", IDENT, P)])


def test_referencia_fechada_exige_todos_os_casos_da_amostra() -> None:
    caso = _avaliacao("caso_0001", "a", IND)
    with pytest.raises(ValueError, match="referencia_fechada_incompleta"):
        ReferenciaHumana(
            sample_id="ann_x",
            estado=EstadoReferencia.FECHADA,
            casos={"r1": caso},
            casos_amostra=("r1", "r2"),
        )


def test_reexportacao_divergente_nao_sobrescreve(cenario: CenarioAnotacao, tmp_path: Path) -> None:
    out = tmp_path / "anotacao"
    primeira = _preparar(cenario, out)
    assert _preparar(cenario, out) == primeira
    outra = cenario.config.model_copy(update={"semente": 7})
    with pytest.raises(ConfigInvalida, match="pacote_ja_exportado"):
        prepare_annotation_sample(
            cenario.labels, cenario.split, outra, out, particoes=cenario.particoes
        )
    assert AnnotationSample.model_validate_json((out / "amostra.json").read_text()) == primeira
