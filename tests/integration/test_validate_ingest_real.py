"""`sustemporal ingest` real, `validate --ingest` e `counterfactual` sobre a pasta (SINTETICO).

Os normalizadores são os reais; só os arquivos de entrada (SIA-PA, SIGTAP, CNES PF e ST) são
fictícios. Nada aqui é resultado empírico.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pyarrow.parquet as pq
from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf, registro_st
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal import cli
from sustemporal.contracts import FamiliaFonte, RunResult
from sustemporal.contracts.counterfactual import CounterfactualSearchResult, MotivoParada
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.errors import ExitCode
from sustemporal.rules.entrada import EntradaValidacao

if TYPE_CHECKING:
    from pathlib import Path

_FORA_DO_DRS_XI = "355030"
_ST = "cnes_estabelecimento.v1"
_PROCEDIMENTO_DO_SIGTAP = "0101010010"
_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"


def _preparar(
    pasta: Path, *, cbo_do_cnes: str = "225125", com_cnes_st: bool = False, avaliavel: bool = False
) -> Path:
    """`avaliavel`: partes do SIA-PA declaradas e procedimento presente no SIGTAP sintético."""
    store = pasta / "dados" / "raw"
    extras = {"PA_PROC_ID": _PROCEDIMENTO_DO_SIGTAP} if avaliavel else {}
    registros = [
        registro("C", "201801", "201801", **extras),
        registro("C", "201801", "201801", PA_UFMUN=_FORA_DO_DRS_XI, **extras),
    ]
    pf = [registro_pf("0012345", cbo_do_cnes)]
    versoes = [
        artefato_pa(store, dbc_pa(registros)),
        artefato_sigtap(store, zip_sigtap(pacote_padrao())),
        artefato_cnes(store, dbc_cnes(FamiliaFonte.CNES_PF, pf), FamiliaFonte.CNES_PF),
    ]
    familias = "SIA_PA, CNES_PF, SIGTAP"
    if com_cnes_st:
        st = [registro_st("0012345"), registro_st("0099999")]
        dados = dbc_cnes(FamiliaFonte.CNES_ST, st)
        versoes.append(artefato_cnes(store, dados, FamiliaFonte.CNES_ST))
        familias = "SIA_PA, CNES_PF, CNES_ST, SIGTAP"
    (pasta / "manifestos").mkdir(parents=True)
    registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)
    partes = ["a"] if avaliavel else None
    return config_ingest(pasta, fontes_ingest(pasta, partes), familias=familias)


def _ingerir_e_validar(config: Path, pasta: Path) -> tuple[RunResult, Path]:
    """`ingest` e `validate --ingest` sem `--saida`: a execução fica em `<raiz_saidas>/runs`."""
    assert cli.main(["ingest", "--config", str(config)]) == ExitCode.OK
    (execucao,) = sorted((pasta / "saidas" / "ingest").iterdir())
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    assert cli.main([*argumentos, "--ingest", str(execucao)]) == ExitCode.OK
    (gravado,) = sorted((pasta / "saidas" / "runs").glob("*/run_result.json"))
    return RunResult.model_validate_json(gravado.read_text(encoding="utf-8")), gravado.parent


def _contrafactual(config: Path, pasta: Path, resultado: RunResult) -> CounterfactualSearchResult:
    """`counterfactual` sobre a única linha em `VIOLACAO` da execução e o resultado publicado."""
    ref = next(s for s in resultado.saidas if s.schema_id == "avaliacoes.v1")
    linhas = pq.read_table(ref.caminho).to_pylist()
    (row,) = {a["row_id"] for a in linhas if a["estado"] == "VIOLACAO"}
    argumentos = ["counterfactual", "--config", str(config), "--run", resultado.run_id]
    assert cli.main([*argumentos, "--row", row]) == ExitCode.OK
    (publicado,) = (pasta / "saidas" / "contrafactuais").rglob("contrafactual.json")
    return CounterfactualSearchResult.model_validate_json(publicado.read_text(encoding="utf-8"))


def test_validate_sobre_a_pasta_do_ingest_real(tmp_path: Path) -> None:
    config = _preparar(tmp_path)
    resultado, pasta = _ingerir_e_validar(config, tmp_path)
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    recorte = json.loads((pasta / "recorte_territorial.json").read_text("utf-8"))
    assert recorte["exclusoes"] == {"fora_do_territorio": 1}
    avaliacoes_ref = next(s for s in resultado.saidas if s.schema_id == "avaliacoes.v1")
    avaliacoes = pq.read_table(avaliacoes_ref.caminho).to_pylist()
    assert avaliacoes
    assert len({a["row_id"] for a in avaliacoes}) == 1


def test_validate_sobre_o_ingest_real_registra_o_cnes_st_no_contexto(tmp_path: Path) -> None:
    config = _preparar(tmp_path, com_cnes_st=True)
    resultado, pasta = _ingerir_e_validar(config, tmp_path)
    assert resultado.estado is EstadoExecucao.CONCLUIDA
    entrada = EntradaValidacao.model_validate_json(
        (pasta / "entrada_validacao.json").read_text(encoding="utf-8")
    )
    derivados = [d for d in entrada.auxiliares if d.schema_id == _ST]
    assert len(derivados) == 1
    assert derivados[0].linhas == 2
    assert derivados[0].dataset_id in {e.dataset_id for e in resultado.entradas}


def test_counterfactual_sobre_o_ingest_real_com_cnes_st_encontra_a_operacao(tmp_path: Path) -> None:
    config = _preparar(tmp_path, cbo_do_cnes="223505", com_cnes_st=True, avaliavel=True)
    resultado, _ = _ingerir_e_validar(config, tmp_path)

    busca = _contrafactual(config, tmp_path, resultado)

    assert busca.motivo_parada is MotivoParada.MINIMO_ENCONTRADO
    assert [[o.op_id for o in s.operacoes] for s in busca.solucoes] == [[_INCLUIR]]
    assert busca.aprovacao_garantida is False


def test_counterfactual_sobre_o_ingest_real_sem_cnes_st_nao_tem_operacao_admissivel(
    tmp_path: Path,
) -> None:
    config = _preparar(tmp_path, cbo_do_cnes="223505", avaliavel=True)
    resultado, _ = _ingerir_e_validar(config, tmp_path)

    busca = _contrafactual(config, tmp_path, resultado)

    assert busca.solucoes == ()
    assert busca.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL
    assert busca.aprovacao_garantida is False
