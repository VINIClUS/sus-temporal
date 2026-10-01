import hashlib
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]
MANIFESTO_SPEC = RAIZ / "docs" / "spec" / "manifest.yaml"


def _documentos() -> list[dict[str, object]]:
    conteudo = yaml.safe_load(MANIFESTO_SPEC.read_text(encoding="utf-8"))
    return list(conteudo["documentos"])


def test_original_spec_hash_preserved() -> None:
    documentos = _documentos()
    assert {doc["id"] for doc in documentos} >= {"esboco_original", "plano_implementacao"}
    for doc in documentos:
        caminho = RAIZ / str(doc["caminho"])
        if doc["estado"] == "PENDENTE":
            assert doc["sha256"] is None
            assert not caminho.exists(), f"arquivo_sem_hash_registrado caminho={caminho}"
            continue
        assert doc["estado"] == "PRESERVADO"
        dados = caminho.read_bytes()
        assert hashlib.sha256(dados).hexdigest() == doc["sha256"]
        assert len(dados) == doc["tamanho_bytes"]
