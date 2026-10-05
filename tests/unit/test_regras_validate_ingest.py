"""`sustemporal validate --ingest`: pasta do ingest e registro temporal (SINTETICO)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow.parquet as pq
import pytest

from sustemporal import cli
from sustemporal.config import load_config
from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte, hash_canonico
from sustemporal.contracts.experiment import EstadoExecucao, RunResult
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.cli import EntradaValidacao
from sustemporal.rules.conteudo import ConteudoDivergente
from sustemporal.rules.ingest import (
    carregar_registro,
    incompletude_da_cobertura,
    integridade_do_registro,
    ler_datasets,
    preparar_insumos_ingest,
)
from sustemporal.rules.validate_ingest import municipios_do_piloto
from sustemporal.temporal.registry import registro_de
from tests.fixtures.regras_ingest import MUNICIPIO_FORA, gravar_territorio, montar_ingest
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.regras_ingest import MundoIngest

_POLITICAS = ("atendimento", "processamento", "documented")


def _validar(mundo: MundoIngest, politica: str) -> int:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", politica]
    return cli.main([*argumentos, "--ingest", str(mundo.pasta), "--saida", str(mundo.saida)])


def _resultados(mundo: MundoIngest) -> list[tuple[RunResult, Path]]:
    caminhos = sorted(mundo.saida.glob("*/run_result.json"))
    return [
        (RunResult.model_validate_json(c.read_text(encoding="utf-8")), c.parent) for c in caminhos
    ]


def _unico(mundo: MundoIngest) -> tuple[RunResult, Path]:
    (resultado,) = _resultados(mundo)
    return resultado


def _tabela(resultado: RunResult, schema_id: str) -> list[dict[str, Any]]:
    caminho = next(s.caminho for s in resultado.saidas if s.schema_id == schema_id)
    linhas: list[dict[str, Any]] = pq.read_table(caminho).to_pylist()
    return linhas


def _estados(resultado: RunResult) -> dict[tuple[str, str], str]:
    return {(a["row_id"], a["rule_id"]): a["estado"] for a in _tabela(resultado, "avaliacoes.v1")}


def test_tres_politicas_pela_cli_so_mudam_a_selecao(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    por_politica = {}
    for politica in _POLITICAS:
        antes = {r.run_id for r, _ in _resultados(mundo)}
        assert _validar(mundo, politica) == ExitCode.OK
        (novo,) = [r for r, _ in _resultados(mundo) if r.run_id not in antes]
        por_politica[politica] = novo
    for resultado in por_politica.values():
        assert resultado.estado is EstadoExecucao.CONCLUIDA
    fixas = {
        p: sorted(e.dataset_id for e in r.entradas if e.schema_id != "selecao_versoes.v1")
        for p, r in por_politica.items()
    }
    assert len({tuple(v) for v in fixas.values()}) == 1
    assert {r.catalogo_regras_sha256 for r in por_politica.values()} == {
        por_politica["atendimento"].catalogo_regras_sha256
    }
    selecoes = {
        next(e.dataset_id for e in r.entradas if e.schema_id == "selecao_versoes.v1")
        for r in por_politica.values()
    }
    assert len(selecoes) == len(_POLITICAS)
    atend = _estados(por_politica["atendimento"])
    proc = _estados(por_politica["processamento"])
    chaves_cnes = [k for k in atend if k[1] == "ESTAB_CBO_CNES" and k[0].endswith("#0")]
    assert chaves_cnes
    assert {atend[k] for k in chaves_cnes} == {"CONFORME"}
    assert {proc[k] for k in chaves_cnes} == {"VIOLACAO"}
    documentada = set(_estados(por_politica["documented"]).values())
    assert documentada <= {"INCONCLUSIVO", "NAO_APLICAVEL"}


def test_linha_fisica_repetida_entre_partes_conta_duas_vezes(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    repetidas = {k[0] for k in _estados(resultado) if k[0].endswith("#0")}
    assert len(repetidas) == 2


def test_territorio_exclui_e_conta_linhas_fora(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    avaliados = {k[0] for k in _estados(resultado)}
    assert not any(k.endswith("#2") for k in avaliados)
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1}
    assert MUNICIPIO_FORA not in recorte["municipios"]


def test_mes_vizinho_ausente_e_inconclusivo_nunca_o_vizinho(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sigtap_fev_ausente=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    selecoes = [s for s in _tabela(resultado, "selecao_versoes.v1") if s["fonte"] == "SIGTAP"]
    assert selecoes
    assert {s["competencia_requerida"] for s in selecoes} == {"202302"}
    assert {s["estado"] for s in selecoes} == {"AUSENTE"}
    estados = _estados(resultado)
    for selecao in selecoes:
        assert estados[(selecao["row_id"], selecao["rule_id"])] == "INCONCLUSIVO"


def test_versoes_concorrentes_da_producao_sao_recusadas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, concorrente=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_sem_cobertura_nenhuma_violacao_por_ausencia(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sem_cobertura=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, _ = _unico(mundo)
    assert "VIOLACAO" not in set(_estados(resultado).values())


def test_manifesto_ausente_sai_com_config_invalida_sem_saidas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sem_manifesto=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_entrada_e_ingest_sao_mutuamente_exclusivos(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    argumentos += ["--ingest", str(mundo.pasta), "--entrada", str(tmp_path / "e.json")]
    with pytest.raises(SystemExit) as erro:
        cli.main(argumentos)
    assert erro.value.code == 2


def test_producao_observada_so_depois_do_corte_e_recusada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, corte="2026-01-01T12:00:00+00:00")
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_row_id_repetido_na_producao_e_falha_operacional(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, producao_repetida=True)
    assert _validar(mundo, "processamento") == ExitCode.FALHA_OPERACIONAL


def test_integridade_do_registro_nunca_trata_quarentena_ou_falha_como_integra() -> None:
    itens = [
        observar(FamiliaFonte.CNES_PF, "202301", "ok", 1),
        observar(
            FamiliaFonte.CNES_PF,
            "202302",
            "quarentena",
            1,
            integridade_observada=EstadoIntegridade.QUARENTENA_CHECKSUM,
        ),
        observar(FamiliaFonte.SIGTAP, "202301", "falha", 1, uf=None),
    ]
    falha_obs, falha_versao = itens[2]
    assert falha_versao is not None
    interrompida = falha_obs.model_copy(
        update={"observation_id": "obs_" + "f" * 32, "resultado": ResultadoTentativa.INTERROMPIDO}
    )
    registro = registro_de(
        [o for o, _ in itens] + [interrompida], [v for _, v in itens if v is not None]
    )
    estados = integridade_do_registro(registro)
    ok, quarentena = (v.artifact_id for _, v in itens[:2] if v is not None)
    assert estados[ok] is EstadoIntegridade.OK
    assert estados[quarentena] is EstadoIntegridade.QUARENTENA_CHECKSUM
    assert estados[falha_versao.artifact_id] is EstadoIntegridade.NAO_VERIFICADO


def test_datasets_jsonl_com_utf8_invalido_sai_com_config_invalida(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    (mundo.pasta / "datasets.jsonl").write_bytes(b'{"dataset_id": "\xff"}\n')
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA


def test_auxiliar_divergente_nao_deixa_nenhum_arquivo_derivado(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, auxiliar_divergente=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_integridade_ignora_observacoes_posteriores_ao_corte() -> None:
    obs, versao = observar(FamiliaFonte.CNES_PF, "202301", "ok", 1)
    assert versao is not None
    posterior = obs.model_copy(
        update={
            "observation_id": "obs_" + "e" * 32,
            "observado_em": obs.observado_em + timedelta(days=30),
            "integridade": EstadoIntegridade.QUARENTENA_CHECKSUM,
        }
    )
    registro = registro_de([obs, posterior], [versao])
    corte = obs.observado_em + timedelta(days=1)
    assert (
        integridade_do_registro(registro, corte=corte)[versao.artifact_id] is EstadoIntegridade.OK
    )
    assert integridade_do_registro(registro)[versao.artifact_id] is (
        EstadoIntegridade.QUARENTENA_CHECKSUM
    )


def test_cobertura_com_tipo_fisico_invalido_sai_sem_saidas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, cobertura_com_tipo_invalido=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_territorio_diferente_sem_registros_muda_a_identidade_da_execucao(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    gravar_territorio(tmp_path / "territorio.yaml", "350030")
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultados = _resultados(mundo)
    assert len({r.run_id for r, _ in resultados}) == 2
    recortes = [json.loads((p / "recorte_territorial.json").read_text()) for _, p in resultados]
    assert sorted(len(r["municipios"]) for r in recortes) == [2, 3]


def test_producao_fora_das_competencias_do_piloto_e_recusada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, competencias_piloto=("202301",))
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_integridade_omite_versoes_observadas_so_depois_do_corte() -> None:
    obs, versao = observar(FamiliaFonte.CNES_PF, "202301", "tardia", 40)
    assert versao is not None
    registro = registro_de([obs], [versao])
    corte = obs.observado_em - timedelta(days=1)
    assert versao.artifact_id not in integridade_do_registro(registro, corte=corte)
    assert versao.artifact_id in integridade_do_registro(registro)


def test_territorio_com_digito_verificador_invalido_sai_com_config_invalida(
    tmp_path: Path,
) -> None:
    mundo = montar_ingest(tmp_path)
    caminho = tmp_path / "territorio.yaml"
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    ibge7 = conteudo["municipios"][0]["ibge7"]
    conteudo["municipios"][0]["ibge7"] = ibge7[:6] + str((int(ibge7[6]) + 1) % 10)
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA


def test_producao_sem_coluna_de_municipio_sai_com_config_invalida(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sem_coluna_municipio=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_municipio_nulo_e_contado_como_territorio_indeterminado(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, municipio_nulo=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    assert not any(k[0].endswith("#3") for k in _estados(resultado))
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1, "territorio_indeterminado": 1}


def test_recorte_que_esvazia_a_populacao_nao_conclui_em_silencio(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    caminho = tmp_path / "territorio.yaml"
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    conteudo["municipios"] = conteudo["municipios"][1:]
    caminho.write_text(json.dumps(conteudo), encoding="utf-8")
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_entrada_da_validacao_e_gravada_e_confere_com_o_run_result(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    entrada = EntradaValidacao.model_validate_json(
        (pasta / "entrada_validacao.json").read_text(encoding="utf-8")
    )
    refs = [entrada.dataset, *entrada.auxiliares, entrada.selecoes, entrada.cobertura]
    assert sorted(r.dataset_id for r in refs if r is not None) == sorted(
        e.dataset_id for e in resultado.entradas
    )
    assert entrada.snapshots.snapshot_id == resultado.snapshot_set_id
    assert entrada.politica is not None
    assert entrada.politica.politica_id == resultado.politica_id


def _celulas(caminho: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    return {
        (c["familia_regra"], c["instrumento"], c["competencia"], c["base_temporal"]): c
        for c in pq.read_table(caminho).to_pylist()
    }


def _cobertura_da_ingestao(mundo: MundoIngest) -> str:
    refs = ler_datasets(mundo.pasta)
    return next(r.caminho for r in refs if r.schema_id == "cobertura.v1")


def _cobertura_avaliada(pasta: Path) -> str:
    entrada = EntradaValidacao.model_validate_json(
        (pasta / "entrada_validacao.json").read_text(encoding="utf-8")
    )
    assert entrada.cobertura is not None
    return entrada.cobertura.caminho


def test_incompletude_da_cobertura_le_o_formato_do_build_coverage(tmp_path: Path) -> None:
    incompleto = {"202302": "parte_c_ausente"}
    mundo = montar_ingest(tmp_path, sia_pa_incompleto=incompleto)
    ref = next(r for r in ler_datasets(mundo.pasta) if r.schema_id == "cobertura.v1")
    with duckdb.connect() as con:
        assert incompletude_da_cobertura(con, ref) == incompleto


def test_registro_fora_do_territorio_nao_torna_a_celula_insuficiente(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, fora_com_atendimento_nulo=True)
    chave = ("ESTABELECIMENTO_CBO", "C", "202302", "ATENDIMENTO")
    assert _celulas(_cobertura_da_ingestao(mundo))[chave]["estado"] == "INSUFICIENTE"
    assert _validar(mundo, "atendimento") == ExitCode.OK
    _, pasta = _unico(mundo)
    assert _celulas(_cobertura_avaliada(pasta))[chave]["estado"] == "DISPONIVEL"


def test_competencia_incompleta_na_ingestao_continua_insuficiente(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, sia_pa_incompleto={"202302": "parte_c_ausente"})
    assert _validar(mundo, "processamento") == ExitCode.OK
    _, pasta = _unico(mundo)
    ingestao = _celulas(_cobertura_da_ingestao(mundo))
    avaliada = _celulas(_cobertura_avaliada(pasta))
    assert ingestao.keys() == avaliada.keys()
    for chave, celula in avaliada.items():
        if str(ingestao[chave]["motivo"] or "").startswith("sia_pa_incompleto "):
            assert celula["estado"] != "DISPONIVEL"
            assert str(celula["motivo"]).startswith("sia_pa_incompleto competencia=202302")
    assert any(c["competencia"] == "202302" for c in avaliada.values())


def test_registro_deletado_nao_e_avaliado_e_e_contado(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, deletado_no_territorio=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    assert not any(k[0].endswith("#4") for k in _estados(resultado))
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1, "registro_deletado": 1}


def test_auxiliares_com_linhagem_trocada_sao_recusados(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, auxiliares_trocados=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_registro_deletado_fora_do_territorio_conta_uma_vez(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, deletado_fora=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    _, pasta = _unico(mundo)
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1, "registro_deletado": 1}


def test_linhagem_trocada_e_conteudo_divergente_antes_de_gravar(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, auxiliares_trocados=True)
    config = load_config(mundo.config)
    contexto = (config, carregar_registro(config), municipios_do_piloto(config))
    destino = tmp_path / "destino"
    with duckdb.connect() as con, pytest.raises(ConteudoDivergente, match="linhagem_divergente"):
        preparar_insumos_ingest(
            con, ler_datasets(mundo.pasta), carregar_regras(), contexto, destino
        )
    assert not destino.exists()


def test_perda_de_linhas_do_auxiliar_mantem_a_celula_insuficiente(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, cnes_fev_com_perda=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    chave = ("ESTABELECIMENTO_CBO", "C", "202302", "PROCESSAMENTO")
    assert _celulas(_cobertura_avaliada(pasta))[chave]["estado"] == "INSUFICIENTE"
    estados = _estados(resultado)
    cnes = [k for k in estados if k[1] == "ESTAB_CBO_CNES" and k[0].endswith("#0")]
    assert cnes
    assert {estados[k] for k in cnes} == {"INCONCLUSIVO"}


def test_entrada_gravada_reproduz_o_run_id_pelo_caminho_direto(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    original, pasta = _unico(mundo)
    outra = tmp_path / "reexecucao"
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    argumentos += ["--entrada", str(pasta / "entrada_validacao.json"), "--saida", str(outra)]
    assert cli.main(argumentos) == ExitCode.OK
    (gravado,) = outra.glob("*/run_result.json")
    reexecutado = RunResult.model_validate_json(gravado.read_text(encoding="utf-8"))
    assert reexecutado.run_id == original.run_id
    assert [s.dataset_id for s in reexecutado.saidas] == [s.dataset_id for s in original.saidas]


def test_versao_concorrente_so_no_registro_e_recusada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, concorrente_so_no_registro=1)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_versao_concorrente_observada_depois_do_corte_nao_impede(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, concorrente_so_no_registro=2, corte="2026-01-02T12:00:00+00:00")
    assert _validar(mundo, "processamento") == ExitCode.OK


def test_linha_fora_das_competencias_do_piloto_nao_e_avaliada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, linha_fora_do_piloto=True)
    assert _validar(mundo, "processamento") == ExitCode.OK
    resultado, pasta = _unico(mundo)
    assert not any(k[0].endswith("#6") for k in _estados(resultado))
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    assert recorte["exclusoes"] == {
        "fora_das_competencias_do_piloto": 1,
        "fora_do_territorio": 1,
    }


def test_identidade_adicional_cobre_o_recorte_inteiro(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path)
    assert _validar(mundo, "processamento") == ExitCode.OK
    _, pasta = _unico(mundo)
    recorte = json.loads((pasta / "recorte_territorial.json").read_text(encoding="utf-8"))
    entrada = EntradaValidacao.model_validate_json(
        (pasta / "entrada_validacao.json").read_text(encoding="utf-8")
    )
    assert entrada.identidade_adicional == {"recorte_territorial": hash_canonico(recorte)}


def test_motivo_de_incompletude_malformado_recusa_sem_gravar(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, cobertura_motivo_malformado=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def test_producao_com_artefato_de_outra_fonte_e_recusada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, producao_com_artefato_cnes=True)
    config = load_config(mundo.config)
    contexto = (config, carregar_registro(config), municipios_do_piloto(config))
    with (
        duckdb.connect() as con,
        pytest.raises(ConfigInvalida, match="producao_com_fonte_invalida"),
    ):
        preparar_insumos_ingest(
            con, ler_datasets(mundo.pasta), carregar_regras(), contexto, tmp_path / "destino"
        )
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA


def test_parte_selecionada_ausente_da_pasta_e_recusada(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, parte_b_so_no_registro=True)
    assert _validar(mundo, "processamento") == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))
    config = load_config(mundo.config)
    registro = carregar_registro(config)
    (parte_b,) = (a for a, v in registro.versoes.items() if v.chave.parte == "b")
    contexto = (config, registro, municipios_do_piloto(config))
    destino = tmp_path / "destino"
    with duckdb.connect() as con, pytest.raises(ConfigInvalida) as erro:
        preparar_insumos_ingest(
            con, ler_datasets(mundo.pasta), carregar_regras(), contexto, destino
        )
    esperado = f"producao_com_partes_ausentes competencia=202302 ausentes=['{parte_b}']"
    assert str(erro.value) == esperado
    assert not destino.exists()
