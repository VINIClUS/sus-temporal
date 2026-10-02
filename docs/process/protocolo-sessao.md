# Protocolo das sessões-filhas

O projeto é implementado por um orquestrador e por sessões-filhas do Claude Code, cada uma com um
pacote de tarefas do plano (§8). Este documento é o contrato operacional de cada sessão-filha.

## Regras invioláveis (repetidas no prompt de sistema da sessão)
1. Comunicação com o orquestrador só por commits, corpo do PR e comentários no próprio PR com
   prefixo `BLOQUEIO:`. O orquestrador não recebe mensagens diretas.
2. Seguir `AGENTS.md`. Trabalhar só no próprio branch e só nos caminhos da sessão em
   `docs/process/propriedade.yaml` (arquivos sem dono listado são compartilhados).
3. Nunca force-push, rebase de commits publicados, commit em `main` ou merge de PR.
4. Testes sem rede externa e sem dados reais. Nada de LLM para causas, rótulos ou texto de
   explicação.
5. Não criar decisões G0/G1/G2 nem alterar `docs/spec`, `docs/plan`, `pyproject.toml`, `uv.lock`,
   `.github`, `.claude` ou `src/sustemporal/cli.py`.
6. Nenhuma afirmação empírica; o que é sintético é marcado `SINTETICO`.
7. Não usar `subscribe_pr_activity` (o orquestrador acompanha os PRs).

## Sessões e tarefas
| Sessão | Branch | Tarefas (em ordem de PR) |
|---|---|---|
| S1 | `claude/s1-bitemporal` | T02 → T06 → T13 (observação de republicações) |
| S2 | `claude/s2-dbc-sia-pa` | fixtures DBC/DBF → adaptador DBC/DBF → T03 |
| S3 | `claude/s3-referencias-piloto` | T04 SIGTAP → T04 CNES e cobertura → T05 |
| S4 | `claude/s4-motor-regras` | T07 |
| S5 | `claude/s5-protocolo` | T10 → T11 |
| S6 | `claude/s6-explicacoes` | T08 |
| S7 | `claude/s7-contrafactuais` | T09 |
| S8 | `claude/s8-anotacao-valores` | T12 → T13 (valores e desempenho) |
| S9 | `claude/s9-reproducao` | T14 |

O branch é fixado pelo orquestrador ao criar a sessão (`outcome_branch`) e repetido no cartão.

## Leitura obrigatória (nesta ordem)
`AGENTS.md` → este protocolo → plano (Restrições globais, Foco de revisão, seções da tarefa,
tarefa em §8) → `docs/process/propriedade.yaml` → contratos e esquemas citados no cartão →
ADRs citados → `docs/references/` pertinentes.

## Cartão da tarefa (enviado no prompt)
Objetivo · arquivos a criar · interfaces com assinatura exata (parâmetros extras só keyword-only
com default) · testes obrigatórios (nomes do plano + adicionais) · critérios de aceite · linhas do
Foco de revisão sob responsabilidade da sessão · fora de escopo · pendências a registrar em
`docs/pendencias/TNN.md` · dependências ainda não mescladas e como contorná-las (fábricas
sintéticas, stubs, fixtures).

## Método
1. **Projetista de testes (subagente):** cartão + plano + contratos → matriz critério/linha do
   Foco → casos de teste, casos-limite e propriedades Hypothesis. A matriz vai para o PR.
2. **TDD por grupo:** commit `test(...)` com vermelho pertinente (asserção ou
   `NotImplementedError`; nunca ImportError ou sintaxe) → commit `feat(...)` mínimo → verde →
   refatorar. O revisor reexecuta o commit de testes para ver o vermelho.
3. **Independência:** quando o plano exige referência independente (ex.: avaliador de referência
   de regras, leitor DBC independente), um subagente em worktree isolado escreve o componente a
   partir de `docs/method`, catálogo e contratos, proibido de ler o código de produção
   correspondente; o teste diferencial compara os dois.
4. **Revisor adversarial (subagente):** antes de marcar pronto, confronta o diff com aceite,
   Restrições globais e Foco; aplica 3–5 mutações dirigidas; corrigir ou justificar no PR.
5. No máximo 3 subagentes simultâneos (limite de uso compartilhado).
6. `bash scripts/ci.sh` verde antes de marcar pronto.

## Git, PR e CI
- Commits pequenos `<tipo>(<escopo>): <descrição>`, enviados a cada passo verde
  (`git push -u origin <branch>`).
- Abrir cedo um PR **rascunho** para `main` pelas ferramentas MCP do GitHub
  (`create_pull_request` com `draft: true`); rascunho não roda CI. Corpo conforme
  `.github/pull_request_template.md`.
- Ao concluir: `bash scripts/ci.sh` verde → marcar pronto (`update_pull_request` com
  `draft: false`). O orquestrador acompanha o CI e repassa falhas.
- `main` avançou: `git fetch origin && git merge --no-edit origin/main` → resolver → `uv sync
  --locked` → `bash scripts/ci.sh` → push. Após squash merge de um PR, continuar no MESMO branch
  depois de mesclar `origin/main`.

## Guardas automáticas
- Git: o hook PreToolUse do Bash (`.claude/hooks/bloquear_push_perigoso.py`) e o `pre-push` do
  git (`.githooks/pre-push`, ativado pelo SessionStart com `git config core.hooksPath .githooks`)
  recusam push forçado ou não fast-forward, remoção de ref e push para `main`. O hook do Bash
  recusa também `git push --no-verify`, troca de `core.hooksPath` por `-c`/`--config-env`,
  `git send-pack`, `gh pr merge` e `gh api` com `DELETE` ou caminho com `/merge`, `/merges` ou
  `/git/refs`.
- MCP do GitHub: o hook PreToolUse `.claude/hooks/bloquear_mcp_github.py` (matcher
  `mcp__github__.*`) recusa `merge_pull_request`, `enable_pr_auto_merge` e `delete_file`, e
  qualquer ferramenta cujo `tool_input` tenha `branch`, `ref` ou `head` igual a `main` ou
  `refs/heads/main` (ex.: `create_or_update_file`, `push_files`, `create_branch`). `from_branch` e
  `base` não contam: `create_pull_request` com `base: main` segue permitido. Recusa: saída 2 com
  `mcp_bloqueado motivo=…` no stderr.
- Exceção: só o orquestrador, com `SUSTEMPORAL_PAPEL=orquestrador` no ambiente do processo do
  Claude Code (o hook herda esse ambiente), pode `merge_pull_request`. Sessões-filhas não definem
  essa variável. Escrita direta em `main` continua recusada para todos.
- Guarda que recusa uma ação legítima: comentário `BLOQUEIO:` no PR; nunca contornar.

## Contratos
- Mudança aditiva (campo opcional com default, tipo novo no `__all__`) só no módulo de contrato que
  a sessão possui. Em contrato cuja identidade deriva do conteúdo (`artifact_id`, cadeia do
  manifesto, `snapshot_id`, `freeze_id`, `config_hash`, `dataset_id`), campo novo tem default
  `None`: ids já emitidos precisam continuar válidos. `sustemporal.contracts` reexporta o `__all__` de cada módulo automaticamente.
  Regenerar o snapshot com `uv run python -m scripts.snapshot_contratos` (só o arquivo
  `tests/unit/snapshots/contratos_<modulo>.json` do seu módulo deve mudar) e listar a mudança na
  seção "Contratos e esquemas" do PR.
- Qualquer outra mudança: comentário `BLOQUEIO: contrato …` no PR, seguir com contorno
  conservador (abstenção/`INCONCLUSIVO`) e documentar.

## Fixtures e pendências
- Fábricas e geradores sintéticos da sessão ficam em `tests/fixtures/<area>_*.py` (prefixos no mapa
  de propriedade); `tests/fixtures/sintetico/` é do orquestrador.
- Pendências: `docs/pendencias/TNN.md` (T13 usa `T13a.md` para S1 e `T13b.md` para S8).

## Revisões automáticas
O repositório tem o revisor Codex: ao marcar o PR como pronto, ele comenta achados (P0–P3). O
orquestrador repassa os achados; corrija os válidos na mesma rodada e responda os demais no PR.

## Proibições
Rede em testes; dados reais, `data/` ou `outputs/` no Git; leiautes, códigos ou trechos
normativos apresentados como oficiais sem rótulo de proveniência; resultados empíricos; LLM para
causas, rótulos ou texto; SQL interpolado; float para dinheiro; `int()` em códigos; `print`; mock
fora de fronteiras; pular ou enfraquecer testes; `type: ignore` sem justificativa; dependência
nova silenciosa; arquivos de outros donos; fallback para mês vizinho.

## Fim de cada turno
Mensagem final: `PR #n | estado (RASCUNHO/PRONTO_PARA_REVISAO) | CI | pendências | bloqueios |
próximo passo`. Depois aguardar o orquestrador.
