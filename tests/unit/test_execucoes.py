"""Lugar único das execuções do `validate` e leitor comum do `run_result.json` (SINTETICO)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import (
    Ambiente,
    CodeVersion,
    EstadoExecucao,
    ModoExecucao,
    RunResult,
    TipoExecucao,
)
from sustemporal.execucoes import (
    DIRETORIO_EXECUCOES,
    ExecucaoNaoResolvida,
    ler_execucao,
    raiz_execucoes,
    validar_run_id,
)

RUN_ID = "val_" + "a" * 40
OUTRA = "val_" + "b" * 40


def _run(run_id: str = RUN_ID) -> RunResult:
    return RunResult(
        run_id=run_id,
        tipo=TipoExecucao.VALIDACAO,
        modo=ModoExecucao.EXPLORATORIO,
        config_hash="a" * 64,
        codigo=CodeVersion(commit="abc", sujo=False, versao_pacote="0.1"),
        ambiente=Ambiente(python="3.12", plataforma="linux"),
        estado=EstadoExecucao.CONCLUIDA,
        iniciado_em=datetime(2026, 1, 1, tzinfo=UTC),
        origem_dados=OrigemDados.SINTETICO,
    )


def _gravar(raiz: Path, pasta: str, conteudo: bytes | None = None) -> Path:
    """`<raiz>/<pasta>/run_result.json`: o `RunResult` da pasta, ou os bytes dados."""
    destino = raiz / pasta
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / "run_result.json"
    arquivo.write_bytes(_run(pasta).model_dump_json().encode() if conteudo is None else conteudo)
    return arquivo


def test_diretorio_das_execucoes_e_runs() -> None:
    assert DIRETORIO_EXECUCOES == "runs"


def test_raiz_das_execucoes_e_runs_sob_a_raiz_de_saidas(tmp_path: Path) -> None:
    config = RunConfig(versao="1", runtime=RuntimeConfig(raiz_saidas=str(tmp_path / "saidas")))
    assert raiz_execucoes(config) == tmp_path / "saidas" / "runs"


def test_raiz_das_execucoes_com_a_raiz_de_saidas_padrao() -> None:
    assert raiz_execucoes(RunConfig(versao="1")) == Path("outputs") / "runs"


def test_le_a_execucao_gravada_na_pasta_do_run_id(tmp_path: Path) -> None:
    _gravar(tmp_path, RUN_ID)
    assert ler_execucao(tmp_path, RUN_ID) == _run()


def test_le_so_a_execucao_pedida_entre_varias(tmp_path: Path) -> None:
    _gravar(tmp_path, OUTRA)
    _gravar(tmp_path, RUN_ID)
    assert ler_execucao(tmp_path, OUTRA).run_id == OUTRA
    assert ler_execucao(tmp_path, RUN_ID).run_id == RUN_ID


def test_execucao_inexistente_e_recusada_sem_escolher_a_mais_recente(tmp_path: Path) -> None:
    _gravar(tmp_path, OUTRA)
    with pytest.raises(ExecucaoNaoResolvida, match=f"execucao_inexistente run={RUN_ID}"):
        ler_execucao(tmp_path, RUN_ID)


@pytest.mark.parametrize("pasta", ["ausente", "arquivo"])
def test_raiz_sem_a_pasta_do_run_id_e_execucao_inexistente(tmp_path: Path, pasta: str) -> None:
    raiz = tmp_path / "runs"
    if pasta == "arquivo":
        raiz.write_bytes(b"nao_e_pasta")
    with pytest.raises(ExecucaoNaoResolvida, match=f"execucao_inexistente run={RUN_ID}"):
        ler_execucao(raiz, RUN_ID)


def test_pasta_do_run_id_sem_run_result_e_execucao_inexistente(tmp_path: Path) -> None:
    (tmp_path / RUN_ID).mkdir()
    with pytest.raises(ExecucaoNaoResolvida, match=f"execucao_inexistente run={RUN_ID}"):
        ler_execucao(tmp_path, RUN_ID)


@pytest.mark.parametrize(
    "conteudo",
    [
        b"\xff\xfe\x00nao_utf8",
        b'{"run_id": "val_\xe9"}',
        b'{"run_id": "val_',
        b"{}",
        b'{"run_id": "val_x"}',
    ],
    ids=["binario", "latin1", "json_truncado", "sem_campos", "contrato_incompleto"],
)
def test_run_result_ilegivel_e_recusado(tmp_path: Path, conteudo: bytes) -> None:
    _gravar(tmp_path, RUN_ID, conteudo)
    with pytest.raises(ExecucaoNaoResolvida, match=f"execucao_ilegivel run={RUN_ID}"):
        ler_execucao(tmp_path, RUN_ID)


def test_run_result_que_e_pasta_e_execucao_ilegivel(tmp_path: Path) -> None:
    (tmp_path / RUN_ID / "run_result.json").mkdir(parents=True)
    with pytest.raises(ExecucaoNaoResolvida, match=f"execucao_ilegivel run={RUN_ID}"):
        ler_execucao(tmp_path, RUN_ID)


def test_run_id_gravado_diferente_e_execucao_incoerente(tmp_path: Path) -> None:
    _gravar(tmp_path, RUN_ID, _run(OUTRA).model_dump_json().encode())
    with pytest.raises(
        ExecucaoNaoResolvida, match=f"execucao_incoerente run={RUN_ID} gravada={OUTRA}"
    ):
        ler_execucao(tmp_path, RUN_ID)


@pytest.mark.parametrize(
    "run_id", ["", ".", "..", "...", "../x", "a/b", "/etc", "val x", "val_é", "a" * 129]
)
def test_run_id_fora_do_formato_e_recusado(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ExecucaoNaoResolvida, match="argumento_invalido run="):
        validar_run_id(run_id)
    with pytest.raises(ExecucaoNaoResolvida, match="argumento_invalido run="):
        ler_execucao(tmp_path, run_id)


def test_run_id_relativo_nao_le_fora_da_pasta_da_execucao(tmp_path: Path) -> None:
    raiz = tmp_path / "runs"
    raiz.mkdir()
    for relativo in (".", ".."):
        (raiz / relativo / "run_result.json").write_bytes(_run(relativo).model_dump_json().encode())
        with pytest.raises(ExecucaoNaoResolvida, match="argumento_invalido"):
            ler_execucao(raiz, relativo)


def test_run_id_valido_e_devolvido_como_esta() -> None:
    assert validar_run_id(RUN_ID) == RUN_ID
    assert validar_run_id("val_x.1:2-3") == "val_x.1:2-3"
