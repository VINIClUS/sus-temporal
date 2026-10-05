"""Execução imutável: o motor recusa regravar `out/<run_id>` com outro código (SINTETICO).

O `run_id` não inclui a versão do código; `versao_codigo` é a fronteira com o git e é simulada.
"""

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sustemporal import cli
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import CodeVersion, RunResult
from sustemporal.contracts.records import DatasetRef
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.engine import evaluate_rules
from sustemporal.rules.insumos import InsumosAvaliacao
from tests.fixtures.regras_cenario import materializar, snapshot_vazio
from tests.fixtures.regras_exemplos import cenario_base, registro
from tests.fixtures.regras_ingest import montar_ingest
from tests.unit.test_regras_cli import _entrada

LIMPO = CodeVersion(commit="a" * 40, sujo=False, versao_pacote="0.1.0")
OUTRO_COMMIT = LIMPO.model_copy(update={"commit": "b" * 40})
SUJO = LIMPO.model_copy(update={"sujo": True, "diff_sha256": "1" * 64})
PARES_DE_CODIGO = {
    "outro_commit": (LIMPO, OUTRO_COMMIT),
    "arvore_suja_no_mesmo_commit": (LIMPO, SUJO),
    "arvore_suja_de_diff_desconhecido": (LIMPO, LIMPO.model_copy(update={"sujo": True})),
    "mesmo_commit_outro_diff_sha256": (SUJO, SUJO.model_copy(update={"diff_sha256": "2" * 64})),
    "outra_versao_do_pacote": (LIMPO, LIMPO.model_copy(update={"versao_pacote": "9.9.9"})),
}
RESULTADOS_ILEGIVEIS = {
    "diretorio_no_lugar_do_arquivo": None,
    "bytes_que_nao_sao_utf8": b"\xff\xfe\x00{",
    "json_invalido": b'{"run_id": "val_',
    "fora_do_contrato": b'{"run_id": "val_x"}',
}
INSTANTE_ANTIGO_S = 1_000_000_000

Mundo = tuple[DatasetRef, InsumosAvaliacao]


def _relogio() -> datetime:
    return datetime(2026, 1, 15, tzinfo=UTC)


def _mundo(tmp_path: Path) -> Mundo:
    return materializar(cenario_base(registro(0), registro(1, cbo="999999")), tmp_path / "entrada")


def _com_codigo(monkeypatch: pytest.MonkeyPatch, codigo: CodeVersion) -> None:
    monkeypatch.setattr("sustemporal.rules.engine.versao_codigo", lambda _raiz: codigo)


def _executar(mundo: Mundo, saida: Path, *, anexos: dict[str, str] | None = None) -> RunResult:
    dataset, insumos = mundo
    return evaluate_rules(
        dataset,
        snapshot_vazio(),
        carregar_regras(),
        RunConfig(versao="1"),
        saida,
        insumos=insumos,
        relogio=_relogio,
        anexos=anexos,
    )


def _envelhecer(raiz: Path) -> None:
    """Fixa o instante de modificação no passado: qualquer regravação o move."""
    for arquivo in raiz.rglob("*"):
        if arquivo.is_file():
            os.utime(arquivo, (INSTANTE_ANTIGO_S, INSTANTE_ANTIGO_S))


def _retrato(raiz: Path) -> dict[str, tuple[str, int]]:
    """Caminho relativo → (SHA-256, instante de modificação em ns) de cada arquivo sob `raiz`."""
    return {
        str(arquivo.relative_to(raiz)): (
            hashlib.sha256(arquivo.read_bytes()).hexdigest(),
            arquivo.stat().st_mtime_ns,
        )
        for arquivo in sorted(raiz.rglob("*"))
        if arquivo.is_file()
    }


def test_mesma_execucao_com_o_mesmo_codigo_regrava_o_mesmo_conteudo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _com_codigo(monkeypatch, LIMPO)
    mundo, saida = _mundo(tmp_path), tmp_path / "saida"
    anexos = {"nota.json": '{"v": 1}'}
    primeira = _executar(mundo, saida, anexos=anexos)
    destino = saida / primeira.run_id
    antes = {nome: (destino / nome).read_bytes() for nome in ("run_result.json", "nota.json")}
    segunda = _executar(mundo, saida, anexos=anexos)
    assert segunda == primeira
    assert {nome: (destino / nome).read_bytes() for nome in antes} == antes
    assert RunResult.model_validate_json(antes["run_result.json"]).codigo == LIMPO


@pytest.mark.parametrize(("gravado", "atual"), PARES_DE_CODIGO.values(), ids=PARES_DE_CODIGO)
def test_outro_codigo_recusa_e_deixa_intactos_os_arquivos_da_execucao_anterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gravado: CodeVersion, atual: CodeVersion
) -> None:
    mundo, saida = _mundo(tmp_path), tmp_path / "saida"
    _com_codigo(monkeypatch, gravado)
    primeira = _executar(mundo, saida, anexos={"nota.json": '{"v": 1}'})
    destino = saida / primeira.run_id
    _envelhecer(destino)
    antes = _retrato(destino)
    _com_codigo(monkeypatch, atual)
    with pytest.raises(ConfigInvalida) as recusa:
        _executar(mundo, saida, anexos={"nota.json": '{"v": 2}'})
    assert str(recusa.value) == f"execucao_existente_com_outro_codigo run={primeira.run_id}"
    assert recusa.value.codigo_saida is ExitCode.CONFIG_INVALIDA
    assert _retrato(destino) == antes
    gravada = RunResult.model_validate_json((destino / "run_result.json").read_text("utf-8"))
    assert gravada.codigo == gravado


@pytest.mark.parametrize("conteudo", RESULTADOS_ILEGIVEIS.values(), ids=RESULTADOS_ILEGIVEIS)
def test_run_result_ilegivel_recusa_e_deixa_intacta_a_execucao_anterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conteudo: bytes | None
) -> None:
    _com_codigo(monkeypatch, LIMPO)
    mundo, saida = _mundo(tmp_path), tmp_path / "saida"
    primeira = _executar(mundo, saida, anexos={"nota.json": '{"v": 1}'})
    destino = saida / primeira.run_id
    resultado = destino / "run_result.json"
    resultado.unlink()
    if conteudo is None:
        resultado.mkdir()
    else:
        resultado.write_bytes(conteudo)
    _envelhecer(destino)
    antes = _retrato(destino)
    with pytest.raises(ConfigInvalida) as recusa:
        _executar(mundo, saida, anexos={"nota.json": '{"v": 2}'})
    assert str(recusa.value) == f"execucao_existente_ilegivel run={primeira.run_id}"
    assert recusa.value.codigo_saida is ExitCode.CONFIG_INVALIDA
    assert _retrato(destino) == antes


def test_versao_do_codigo_e_calculada_uma_so_vez_por_execucao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chamadas: list[Path] = []

    def versao(raiz: Path) -> CodeVersion:
        chamadas.append(raiz)
        return SUJO

    monkeypatch.setattr("sustemporal.rules.engine.versao_codigo", versao)
    resultado = _executar(_mundo(tmp_path), tmp_path / "saida")
    assert len(chamadas) == 1
    assert resultado.codigo == SUJO


def _recusa_pela_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argumentos: list[str],
    saida: Path,
) -> None:
    _com_codigo(monkeypatch, LIMPO)
    assert cli.main(argumentos) == ExitCode.OK
    (gravado,) = saida.glob("*/run_result.json")
    _envelhecer(gravado.parent)
    antes = _retrato(gravado.parent)
    capsys.readouterr()
    _com_codigo(monkeypatch, OUTRO_COMMIT)
    assert cli.main(argumentos) == ExitCode.CONFIG_INVALIDA
    esperado = f"execucao_existente_com_outro_codigo run={gravado.parent.name}"
    assert esperado in capsys.readouterr().err
    assert _retrato(gravado.parent) == antes


def test_validate_com_entrada_recusa_regravar_com_outro_codigo_com_saida_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text('versao: "1"\n', encoding="utf-8")
    saida = tmp_path / "saida"
    argumentos = ["validate", "--config", str(config), "--policy", "atendimento"]
    argumentos += ["--entrada", str(_entrada(tmp_path / "in")), "--saida", str(saida)]
    _recusa_pela_cli(monkeypatch, capsys, argumentos, saida)


def test_validate_ingest_recusa_regravar_com_outro_codigo_com_saida_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mundo = montar_ingest(tmp_path)
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    argumentos += ["--ingest", str(mundo.pasta), "--saida", str(mundo.saida)]
    _recusa_pela_cli(monkeypatch, capsys, argumentos, mundo.saida)
