from pathlib import Path

import pytest
from scripts.snapshot_contratos import DESTINO, MODULOS, texto_do_snapshot


@pytest.mark.parametrize("modulo", MODULOS)
def test_snapshot_do_contrato_esta_atualizado(modulo: str) -> None:
    arquivo = Path(DESTINO) / f"contratos_{modulo}.json"
    atual = texto_do_snapshot(modulo)
    assert arquivo.exists(), "rode: uv run python -m scripts.snapshot_contratos"
    assert arquivo.read_text(encoding="utf-8") == atual, (
        f"snapshot_desatualizado modulo={modulo}: rode "
        "`uv run python -m scripts.snapshot_contratos` e liste a mudança (aditiva) no PR"
    )
