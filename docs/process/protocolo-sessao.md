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

## Contratos
- Mudança aditiva (campo opcional com default, tipo novo) só no módulo de contrato que a sessão
  possui, com o snapshot de esquema atualizado e listado na seção "Contratos e esquemas" do PR.
- Qualquer outra mudança: comentário `BLOQUEIO: contrato …` no PR, seguir com contorno
  conservador (abstenção/`INCONCLUSIVO`) e documentar.

## Proibições
Rede em testes; dados reais, `data/` ou `outputs/` no Git; leiautes, códigos ou trechos
normativos apresentados como oficiais sem rótulo de proveniência; resultados empíricos; LLM para
causas, rótulos ou texto; SQL interpolado; float para dinheiro; `int()` em códigos; `print`; mock
fora de fronteiras; pular ou enfraquecer testes; `type: ignore` sem justificativa; dependência
nova silenciosa; arquivos de outros donos; fallback para mês vizinho.

## Fim de cada turno
Mensagem final: `PR #n | estado (RASCUNHO/PRONTO_PARA_REVISAO) | CI | pendências | bloqueios |
próximo passo`. Depois aguardar o orquestrador.
