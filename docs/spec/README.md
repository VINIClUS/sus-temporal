# Especificação-base

- `esboco_original.pdf`: esboço do projeto (§§1–8). Prevalece sobre o plano quanto ao escopo
  científico. Estado atual: **PENDENTE** — o arquivo não foi anexado na sessão de implementação.
- `manifest.yaml`: estado, SHA-256 e tamanho de cada documento-base preservado.

Para preservar o PDF: copiar o arquivo original sem alterações para `docs/spec/esboco_original.pdf`,
registrar `estado: PRESERVADO`, `sha256` e `tamanho_bytes` no manifesto e rodar
`uv run pytest tests/unit/test_contracts.py -q`.
