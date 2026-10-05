"""`validate --ingest`: toda entrada confere com o esquema canônico antes de qualquer gravação."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from sustemporal import cli
from sustemporal.config import load_config
from sustemporal.errors import ExitCode
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.conteudo import ConteudoDivergente
from sustemporal.rules.ingest import carregar_registro, ler_datasets, preparar_insumos_ingest
from sustemporal.rules.validate_ingest import municipios_do_piloto
from tests.fixtures.regras_ingest import montar_ingest

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fixtures.regras_ingest import MundoIngest

_PRODUCAO = "sia_pa.v1"
# defeito injetado na produção → (coluna, motivo, linhas) do primeiro conjunto recusado
_DEFEITOS = {
    "deletado_nulo": ({"deletado_nulo": True}, ("deletado", "nulo", 1)),
    "sem_deletado": ({"sem_coluna_deletado": True}, ("deletado", "ausente", 3)),
}


def _mensagem_ao_preparar(mundo: MundoIngest, destino: Path) -> str:
    config = load_config(mundo.config)
    contexto = (config, carregar_registro(config), municipios_do_piloto(config))
    with duckdb.connect() as con, pytest.raises(ConteudoDivergente) as erro:
        preparar_insumos_ingest(
            con, ler_datasets(mundo.pasta), carregar_regras(), contexto, destino
        )
    return str(erro.value)


def _validar(mundo: MundoIngest) -> int:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    return cli.main([*argumentos, "--ingest", str(mundo.pasta), "--saida", str(mundo.saida)])


@pytest.mark.parametrize("caso", _DEFEITOS)
def test_producao_fora_do_esquema_e_recusada_antes_de_gravar(tmp_path: Path, caso: str) -> None:
    defeito, (coluna, motivo, linhas) = _DEFEITOS[caso]
    mundo = montar_ingest(tmp_path, **defeito)
    primeira = next(r for r in ler_datasets(mundo.pasta) if r.schema_id == _PRODUCAO)
    destino = tmp_path / "destino"
    assert _mensagem_ao_preparar(mundo, destino) == (
        f"entrada_fora_do_esquema schema={_PRODUCAO} dataset={primeira.dataset_id} "
        f"coluna={coluna} motivo={motivo} linhas={linhas}"
    )
    assert not destino.exists()


@pytest.mark.parametrize("caso", _DEFEITOS)
def test_validate_ingest_com_producao_fora_do_esquema_sai_sem_saidas(
    tmp_path: Path, caso: str
) -> None:
    defeito, _ = _DEFEITOS[caso]
    mundo = montar_ingest(tmp_path, **defeito)
    assert _validar(mundo) == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))
