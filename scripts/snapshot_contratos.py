"""Gera o snapshot JSON Schema dos contratos, um arquivo por módulo de domínio."""

from __future__ import annotations

import importlib
import inspect
import json
import logging
import sys
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "tests" / "unit" / "snapshots"
MODULOS = (
    "annotation",
    "artifacts",
    "base",
    "config",
    "counterfactual",
    "evaluation",
    "experiment",
    "explanation",
    "records",
    "rules",
    "temporal",
)


def esquema_do_modulo(nome: str) -> dict[str, object]:
    modulo = importlib.import_module(f"sustemporal.contracts.{nome}")
    modelos = {
        simbolo: objeto
        for simbolo in getattr(modulo, "__all__", [])
        if inspect.isclass(objeto := getattr(modulo, simbolo))
        and issubclass(objeto, BaseModel)
        and objeto.__module__ == modulo.__name__
    }
    return {simbolo: modelos[simbolo].model_json_schema() for simbolo in sorted(modelos)}


def texto_do_snapshot(nome: str) -> str:
    return json.dumps(esquema_do_modulo(nome), sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nome in MODULOS:
        (DESTINO / f"contratos_{nome}.json").write_text(texto_do_snapshot(nome), encoding="utf-8")
        logger.info("snapshot_gravado modulo=%s", nome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
