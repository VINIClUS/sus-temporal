"""O registro de execuções serializa a releitura, a checagem e o append entre processos (T11).

Dois `evaluate` do mesmo congelamento podiam reler o registro com N linhas, passar pela
checagem de rodada única e gravar os dois a linha N: `seq` repetido, `anterior` apontando para a
mesma entrada e o registro recusado por `registro_adulterado`, ou duas rodadas confirmatórias do
mesmo teste. A trava (`fcntl.flock` em `arquivo_de_trava(registro)`, ao lado do registro) cobre
a releitura final, a checagem de unicidade e o append. Cenário SINTETICO; nenhum resultado
empírico.
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.contracts import EvaluationReport
from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation import freeze_registro
from sustemporal.evaluation.freeze_registro import (
    arquivo_de_trava,
    ler_registro,
    registrar_execucao,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

FREEZE = f"frz_{'1' * 64}"
ESPERA = 1.0
FILHO = """
import sys
from pathlib import Path

from sustemporal.contracts import EvaluationReport
from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.freeze_registro import registrar_execucao

registro, arquivo = Path(sys.argv[1]), Path(sys.argv[2])
relatorio = EvaluationReport.model_validate_json(arquivo.read_text(encoding="utf-8"))
print("pronto", flush=True)
try:
    registrar_execucao(registro, relatorio)
except PortaoRecusado:
    print("recusado", flush=True)
else:
    print("registrado", flush=True)
"""


def _relatorio(report_id: str, **campos: Any) -> EvaluationReport:
    base: dict[str, Any] = {
        "report_id": report_id,
        "modo": "EXPLORATORIO",
        "origem_dados": "SINTETICO",
        "criado_em": "2026-01-01T00:00:00Z",
    }
    return EvaluationReport.model_validate({**base, **campos})


def _confirmatorio(report_id: str) -> EvaluationReport:
    return _relatorio(
        report_id,
        modo="CONFIRMATORIO",
        origem_dados="REAL",
        freeze_id=FREEZE,
        decisao_g2="experiments/decisions/g2_teste.yaml",
    )


def _linhas(registro: Path) -> int:
    return len(registro.read_text(encoding="utf-8").splitlines()) if registro.exists() else 0


def _flock_registrando(
    registro: Path, eventos: list[tuple[str, int]]
) -> Callable[[int, int], None]:
    """`fcntl.flock` que anota a operação e as linhas do registro naquele instante."""
    original = fcntl.flock

    def flock(descritor: int, operacao: int) -> None:
        nome = {fcntl.LOCK_EX: "EX", fcntl.LOCK_SH: "SH"}.get(operacao, "UN")
        eventos.append((nome, _linhas(registro)))
        original(descritor, operacao)

    return flock


def test_registrar_toma_a_trava_antes_de_reler_e_a_solta_depois_do_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registro = tmp_path / "frozen" / "registro_execucoes.jsonl"
    eventos: list[tuple[str, int]] = []
    ler = freeze_registro.ler_registro

    def ler_anotando(caminho: Path) -> list[dict[str, Any]]:
        eventos.append(("ler", _linhas(registro)))
        return ler(caminho)

    def relogio() -> datetime:
        eventos.append(("relogio", _linhas(registro)))
        return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(fcntl, "flock", _flock_registrando(registro, eventos))
    monkeypatch.setattr(freeze_registro, "ler_registro", ler_anotando)
    registrar_execucao(registro, _relatorio("rep_a"), relogio=relogio)
    assert eventos == [("EX", 0), ("ler", 0), ("relogio", 0), ("UN", 1)]


def test_recusa_de_segunda_rodada_solta_a_trava_e_nao_grava(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registro = tmp_path / "frozen" / "registro_execucoes.jsonl"
    registrar_execucao(registro, _confirmatorio("rep_a1"))
    eventos: list[tuple[str, int]] = []
    monkeypatch.setattr(fcntl, "flock", _flock_registrando(registro, eventos))
    with pytest.raises(PortaoRecusado, match="reabertura_do_teste_sem_correcao_declarada"):
        registrar_execucao(registro, _confirmatorio("rep_a2"))
    assert eventos == [("EX", 1), ("UN", 1)]


def test_a_trava_fica_ao_lado_do_registro(tmp_path: Path) -> None:
    registro = tmp_path / "frozen" / "registro_execucoes.jsonl"
    assert arquivo_de_trava(registro) == tmp_path / "frozen" / "registro_execucoes.jsonl.trava"
    registrar_execucao(registro, _relatorio("rep_a"))
    assert arquivo_de_trava(registro).is_file()


def _iniciar(registro: Path, relatorio: EvaluationReport) -> subprocess.Popen[str]:
    """Processo que vai registrar `relatorio`; devolve depois de ele avisar que está pronto."""
    arquivo = registro.parent / f"{relatorio.report_id}.json"
    arquivo.write_text(relatorio.model_dump_json(), encoding="utf-8")
    comando = [sys.executable, "-c", FILHO, str(registro), str(arquivo)]
    processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert processo.stdout is not None
    assert processo.stdout.readline().strip() == "pronto"
    return processo


def _concluir(processo: subprocess.Popen[str]) -> str:
    saida, erro = processo.communicate(timeout=120)
    assert processo.returncode == 0, erro
    return saida.strip().splitlines()[-1]


def _registrar_com_a_trava_tomada(registro: Path, relatorios: list[EvaluationReport]) -> list[str]:
    """Registra cada relatório em um processo, todos esperando enquanto este teste segura a
    trava; devolve o resultado de cada um depois de soltá-la."""
    registro.parent.mkdir(parents=True, exist_ok=True)
    with arquivo_de_trava(registro).open("a") as trava:
        fcntl.flock(trava.fileno(), fcntl.LOCK_EX)
        processos = [_iniciar(registro, relatorio) for relatorio in relatorios]
        time.sleep(ESPERA)
        assert [processo.poll() for processo in processos] == [None] * len(processos)
        assert not registro.exists()
    return [_concluir(processo) for processo in processos]


def test_dois_processos_registram_em_sequencia_com_a_cadeia_valida(tmp_path: Path) -> None:
    registro = tmp_path / "frozen" / "registro_execucoes.jsonl"
    resultados = _registrar_com_a_trava_tomada(registro, [_relatorio("rep_a"), _relatorio("rep_b")])
    assert resultados == ["registrado", "registrado"]
    entradas = ler_registro(registro)
    assert sorted(entrada["seq"] for entrada in entradas) == [0, 1]
    assert {entrada["report_id"] for entrada in entradas} == {"rep_a", "rep_b"}


def test_dois_processos_com_a_mesma_rodada_confirmatoria_so_um_registra(tmp_path: Path) -> None:
    registro = tmp_path / "frozen" / "registro_execucoes.jsonl"
    resultados = _registrar_com_a_trava_tomada(
        registro, [_confirmatorio("rep_a1"), _confirmatorio("rep_a2")]
    )
    assert sorted(resultados) == ["recusado", "registrado"]
    assert len(ler_registro(registro)) == 1
