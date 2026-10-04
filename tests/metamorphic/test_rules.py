"""Metamórficos SINTETICOS do motor: ordem, reexecução, threads, irrelevância e dependência."""

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import RunResult
from tests.fixtures.regras_cenario import CenarioRegras, artefato
from tests.fixtures.regras_estrategias import cenarios
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import cenario_base, registro

_POUCOS = settings(max_examples=12, suppress_health_check=[HealthCheck.too_slow])
_SAIDAS_DETERMINISTICAS = ("avaliacoes.v1", "evidencias.v1", "agregados_registro.v1")


def _hashes(resultado: RunResult) -> dict[str, str]:
    return {ref.schema_id: ref.hash_logico for ref in resultado.saidas}


def _executar(cenario: CenarioRegras, *, threads: int = 4) -> RunResult:
    config = RunConfig(versao="1", runtime=RuntimeConfig(duckdb_threads=threads))
    with tempfile.TemporaryDirectory() as diretorio:
        return executar(Path(diretorio), cenario, config=config)


def _estados(cenario: CenarioRegras) -> dict[tuple[str, str], tuple[object, ...]]:
    with tempfile.TemporaryDirectory() as diretorio:
        resultado = executar(Path(diretorio), cenario)
        return {
            chave: (a["estado"], a["aplicabilidade"], a["motivos"])
            for chave, a in avaliacoes_por_chave(resultado).items()
        }


def _embaralhar(cenario: CenarioRegras, dados: st.DataObject) -> CenarioRegras:
    def misturar(linhas: tuple) -> tuple:
        return tuple(dados.draw(st.permutations(linhas)))

    return cenario.com(
        registros=misturar(cenario.registros),
        selecoes=misturar(cenario.selecoes),
        auxiliares={nome: misturar(linhas) for nome, linhas in cenario.auxiliares.items()},
    )


@_POUCOS
@given(cenario=cenarios(), dados=st.data())
def test_resultado_invariante_a_ordem_das_linhas(
    cenario: CenarioRegras, dados: st.DataObject
) -> None:
    original = _hashes(_executar(cenario))
    embaralhado = _hashes(_executar(_embaralhar(cenario, dados)))
    assert {s: original[s] for s in _SAIDAS_DETERMINISTICAS} == {
        s: embaralhado[s] for s in _SAIDAS_DETERMINISTICAS
    }


def test_reexecucao_produz_o_mesmo_run_id_e_os_mesmos_hashes() -> None:
    cenario = cenario_base(registro(0), registro(1, cbo="999999"), registro(2, instrumento=None))
    primeira, segunda = _executar(cenario), _executar(cenario)
    assert primeira.run_id == segunda.run_id
    assert _hashes(primeira) == _hashes(segunda)


def test_mesmo_hash_com_uma_e_quatro_threads() -> None:
    linhas = [registro(i, cbo="999999" if i % 3 == 0 else "225125") for i in range(40)]
    cenario = cenario_base(*linhas)
    um, quatro = _executar(cenario, threads=1), _executar(cenario, threads=4)
    assert um.run_id == quatro.run_id
    assert _hashes(um) == _hashes(quatro)


def _irrelevantes(cenario: CenarioRegras) -> CenarioRegras:
    fora = artefato(77)
    extras = {
        nome: linhas + tuple(dict(linha) | {"artifact_id": fora} for linha in linhas)
        for nome, linhas in cenario.auxiliares.items()
    }
    outro = registro(99, procedimento="0909090909", competencia_atendimento="201912")
    return cenario.com(registros=(*cenario.registros, outro), auxiliares=extras)


def test_linhas_irrelevantes_nao_mudam_resultados_existentes() -> None:
    cenario = cenario_base(registro(0), registro(1, cbo="999999"), registro(2, cnes="7654321"))
    antes = _estados(cenario)
    depois = _estados(_irrelevantes(cenario))
    assert {chave: depois[chave] for chave in antes} == antes


@_POUCOS
@given(cenario=cenarios())
def test_versoes_nao_selecionadas_nao_mudam_nenhuma_avaliacao(cenario: CenarioRegras) -> None:
    fora = artefato(77)
    extras = {
        nome: linhas + tuple(dict(linha) | {"artifact_id": fora} for linha in linhas)
        for nome, linhas in cenario.auxiliares.items()
    }
    assert _estados(cenario.com(auxiliares=extras)) == _estados(cenario)


def test_alteracao_na_fonte_muda_so_os_registros_dependentes() -> None:
    dependente = registro(0, cbo="223505")
    independente = registro(1)
    cenario = cenario_base(dependente, independente)
    ocupacoes = tuple(
        linha
        for linha in cenario.auxiliares["sigtap_proc_ocupacao.v1"]
        if linha["co_ocupacao"] != "223505"
    )
    alterado = cenario.com(auxiliares=cenario.auxiliares | {"sigtap_proc_ocupacao.v1": ocupacoes})
    antes, depois = _estados(cenario), _estados(alterado)
    mudaram = {chave for chave in antes if antes[chave] != depois[chave]}
    assert mudaram == {(dependente["row_id"], "PROC_CBO_SIGTAP")}
    assert depois[(dependente["row_id"], "PROC_CBO_SIGTAP")][0] == "VIOLACAO"
