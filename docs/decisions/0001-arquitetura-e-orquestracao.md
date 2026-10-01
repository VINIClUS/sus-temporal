# 0001 — Arquitetura, stack e orquestração da implementação

- Estado: aceita (2026-10-01)
- Contexto: plano de implementação (`docs/plan/`), §3 e §8; esboço pendente em `docs/spec/`.

## Contexto
O plano recomenda um monólito modular de pesquisa, orientado a lotes, com arquivos originais
imutáveis, observações de coleta separadas, Parquet canônico e DuckDB, coordenado por uma CLI e
funcionando sem rede no núcleo experimental. A implementação é feita por um orquestrador e várias
sessões do Claude Code em paralelo, o que exige interfaces fixadas cedo e regras de propriedade de
arquivos para evitar conflitos.

## Decisão
- **Stack:** Python 3.12 (wheels de `datasus-dbc` param em cp312; numpy 2.5 exige ≥ 3.12), uv com
  `uv.lock`, pydantic v2 estrito, DuckDB 1.5, PyArrow, PyYAML, `prov` (PROV-N/PROV-JSON),
  scikit-learn, argparse na CLI (sem dependência extra), pytest + Hypothesis, ruff, mypy estrito.
  Todas as dependências previsíveis são fixadas no primeiro PR; só o orquestrador as altera.
- **Execução offline por padrão:** rede só nos comandos `acquire` e `watch`; testes bloqueiam
  rede externa (pytest-socket, só loopback).
- **Desvios estruturais em relação à árvore do plano (§3):**
  - `src/sustemporal/contracts.py` vira o pacote `sustemporal/contracts/` (um módulo por domínio,
    reexportados por `sustemporal.contracts`), para respeitar o limite de 500 linhas por arquivo e
    reduzir conflitos entre sessões. A importação continua `from sustemporal.contracts import …`.
  - O comando `sustemporal watch` é acrescentado aos comandos do §9 para a observação semanal de
    republicações (T13).
  - Esquemas canônicos em `catalog/schemas/` e registro de manipuladores da CLI (`módulo:função`)
    são as interfaces entre sessões, além dos tipos Python.
- **Orquestração:** sessões-filhas com pacotes de tarefas e caminhos próprios
  (`docs/process/propriedade.yaml`, checado no CI), PRs pequenos para `main`, revisão
  independente por agentes e merge por squash feito pelo orquestrador
  (`docs/process/protocolo-sessao.md`, `docs/process/revisao.md`).

## Consequências
- Interfaces mudam só de forma aditiva pelo dono do módulo; mudanças incompatíveis passam pelo
  orquestrador e são anunciadas a todas as sessões.
- Os limites de código (função ≤ 50 linhas, aninhamento ≤ 3, arquivo ≤ 500 linhas) são testados.
- Quem roda dados reais precisa de Python 3.12 e acesso FTP ao DATASUS (runbook do piloto).
