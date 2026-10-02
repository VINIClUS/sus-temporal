# Revisão e integração

## Quem revisa
Para cada PR pronto com CI verde, o orquestrador abre um agente revisor novo (sem contexto da
sessão autora). PRs de risco alto (T01, T06, T07, T09, T11) recebem dois revisores: um semântico
e um de mutações.

## Roteiro do revisor
1. Ler corpo e diff; conferir o cartão da tarefa e as seções do plano citadas.
2. Conferir propriedade de arquivos e mudanças de contrato (só aditivas, salvo PR do orquestrador).
3. Em worktree no head do PR: `uv sync --locked` e
   `PROPRIEDADE_BRANCH=<branch do PR> bash scripts/ci.sh` (o worktree fica em HEAD destacado).
4. Reexecutar o commit de testes: os testes nomeados falham de forma pertinente.
5. Para cada critério de aceite e linha do Foco de revisão: o teste distingue o certo do errado?
6. Aplicar 3–5 mutações dirigidas; os testes devem falhar. Exemplos:
   `VIOLACAO` com insumo faltante; escolha do mês vizinho; duplicata contada uma vez;
   `NOT EXISTS` sem cobertura suficiente; rótulo usado como atributo; float em valor monetário;
   observação repetida criando nova versão; competência de coleta usada como referência.
7. Linguagem: nada de causa oficial, garantia de aprovação, perda financeira ou resultado
   empírico; proveniência rotulada.
8. Limites de código, SQL parametrizado, Decimal, códigos como texto, sem rede nos testes.

Saída do revisor: veredito; achados `BLOQUEANTE | IMPORTANTE | SUGESTÃO` com arquivo:linha,
evidência e correção sugerida; tabela de mutações (mutação → teste que falhou).

## Critérios de merge (todos)
1. CI verde no head contra o `main` atual (se `main` avançou, atualizar o branch e rodar de novo).
2. Checagem de propriedade aprovada.
3. Nenhum achado BLOQUEANTE aberto; IMPORTANTE corrigido ou registrado em `docs/pendencias/`.
4. Corpo do PR completo: evidência vermelho/verde para cada teste nomeado, tabelas de aceite e
   Foco, pendências e seção "O que este PR não afirma".
5. Contratos: só mudanças aditivas, ou PR do orquestrador.
6. Sem dados reais, saídas volumosas ou fixtures acima de 200 KB.
7. Nada em `experiments/decisions/`, `docs/spec/` ou `docs/plan/` sem o pesquisador.
8. PR de sessão-filha que toque `.github/`, `.claude/`, `.githooks/` ou `scripts/` é recusado,
   mesmo com CI verde: workflow, hooks e scripts do próprio PR rodam no CI dele e poderiam
   afrouxar as checagens que o julgam. Esses caminhos mudam só em PR do orquestrador.

SonarCloud: o quality gate está vermelho por uma linha de base invisível neste ambiente (issue
#5). Até a linha de base ser tratada, a nota do SonarCloud não bloqueia merge; os demais critérios
seguem valendo.

Merge por squash, título `<tipo>(<escopo>): …`. Depois do merge, o orquestrador avisa as sessões
afetadas ("MAIN ATUALIZADO"). CI vermelho em `main` congela novos merges até a correção.
