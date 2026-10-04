# Contrafactuais com limites explícitos (T09)

Estado: pré-G0, exploratório. Tudo o que este documento descreve foi exercitado só com dados
`SINTETICO`; nenhum teste sintético valida a hipótese empírica. O catálogo de operações não tem
documento oficial lido: autoridades, governança e custos são provisórios e ficam `A_CONFIRMAR`
(pendências em `docs/pendencias/T09.md`).

Um contrafactual responde a uma pergunta estreita: **que alteração hipotética, dentro de um
catálogo fechado de operações cadastrais do CNES, faria as regras violadas por um registro ficarem
`CONFORME` sem criar violação nova, segundo o mesmo motor de regras?** A resposta é uma hipótese
sobre o cadastro, não uma recomendação, não uma afirmação sobre o que aconteceu e não uma previsão
de processamento pelo SIA.

## 1. Três coisas que nunca são sinônimos

| Conceito | Onde aparece | O que significa | O que não significa |
|---|---|---|---|
| Alteração hipotética | `Candidato.operacoes` | Mudança simulada numa cópia isolada dos cadastros | Que o cadastro estava errado, que a mudança deveria ter sido feita ou que pode ser feita |
| Executabilidade | `Candidato.executabilidade` | Se a operação poderia, em tese, ser feita hoje no CNES, e sob quais condições | Que alguém tem obrigação ou permissão comprovada de fazê-la |
| Aprovação | `CounterfactualSearchResult.aprovacao_garantida` (sempre `false`) | — | O resultado nunca afirma que o registro seria aprovado: `CONFORME` é satisfação das regras modeladas, e o SIA aplica regras que o catálogo não modela |

## 2. Catálogo fechado (`catalog/operations.yaml`)

Cada operação é um `OperationSpec` (contrato `contracts/counterfactual.py`) com autoridade,
governança, verdade factual exigida, competências permitidas, alcance, custo, precondições,
dependências e `DocRef` com proveniência. O contrato recusa: alterar conjunto que não seja
cadastro CNES (`cnes_*`), alterar fatos do atendimento (`sia_pa*`) ou colunas de diagnóstico,
idade, sexo e data do atendimento, alterar vínculo individual (`altera_vinculo_individual` é
sempre falso) e declarar governança `MUNICIPAL_DOCUMENTADA` sem documento oficial confirmado.

Cada `op_id` tem efeito, gerador de parâmetros e precondições escritos no código
(`explanation/counterfactual_operacoes.py`); operação sem efeito conhecido, precondição
desconhecida ou dependência circular invalida o catálogo.

| Operação | Conjunto | Parâmetros | Efeito | Precondições | Custo provisório |
|---|---|---|---|---|---|
| `INCLUIR_CBO_NO_ESTABELECIMENTO` | `cnes_estab_cbo.v1` | CNES e CBO do registro | +1 na contagem do par estabelecimento–CBO | `ESTABELECIMENTO_NO_CNES_ST` | 1 |
| `RECLASSIFICAR_CBO_NO_ESTABELECIMENTO` | `cnes_estab_cbo.v1` | CNES, CBO do registro e `cbo_origem` | −1 no CBO de origem, +1 no CBO do registro | `ESTABELECIMENTO_NO_CNES_ST`, `CBO_ORIGEM_COM_VINCULO` | 2 |
| `CADASTRAR_ESTABELECIMENTO_NO_CNES` | `cnes_estabelecimento.v1` | CNES do registro | linha do estabelecimento sem atributos | `ESTABELECIMENTO_AUSENTE_NO_CNES_ST` | 3 |

`INCLUIR_CBO_NO_ESTABELECIMENTO` depende de `CADASTRAR_ESTABELECIMENTO_NO_CNES`: numa combinação
com as duas, o cadastro do estabelecimento vem antes. As operações atuam no nível
estabelecimento–CBO do CNES PF reduzido: nenhuma cria, identifica ou infere o vínculo de um
profissional específico; a contagem é de vínculos, não de pessoas. As três têm autoridade e
governança `DESCONHECIDA` até a revisão com especialista; nenhuma habilitação é tratada como
governança municipal.

Custos são ordinais de desenvolvimento (inteiros ≥ 1): a inclusão de um par é a alteração mais
local; a reclassificação mexe em dois pares e pode afetar outros registros; o cadastro de um
estabelecimento é a mais ampla. Não medem esforço, prazo nem custo financeiro.

## 3. Sobreposição isolada

`search_counterfactuals(bundle, config, *, contexto, operacoes=None)` recebe o
`ExplanationBundle` do registro e, em `ContextoContrafactual`, os insumos com que o motor o avaliou
(conjunto SIA-PA, `SnapshotSet`, regras, `InsumosAvaliacao`, conjuntos cadastrais extras como o
CNES ST e a competência que evidência atual mostra aberta no CNES). Sem contexto a busca recusa
(`contrafactual_sem_contexto`): revalidar é obrigatório e não há como fazê-lo sem os insumos.

1. Todos os arquivos dos insumos são copiados para um diretório temporário; os originais só são
   lidos (cópia e conferência de conteúdo) e nunca mudam.
2. Cada conjunto cadastral editável (`cnes_estab_cbo.v1`, `cnes_estabelecimento.v1`) tem o conteúdo
   conferido contra o `DatasetRef` (linhas e hash lógico) e o tipo físico de todas as colunas do
   esquema conferido contra o esquema canônico; divergência de conteúdo é falha operacional,
   leiaute incompatível torna o conjunto não editável (operações sobre ele ficam inadmissíveis).
3. A competência da busca é a `competencia_requerida` das seleções `SELECIONADA` das regras-alvo;
   mais de uma competência, ou nenhuma, deixa a busca sem operação admissível. A versão alterada é
   a selecionada para a fonte (CNES PF) ou, sem seleção, a única versão daquela competência no
   conjunto (CNES ST); sem versão única, o conjunto não é editável. Nunca se usa o mês vizinho.
4. Cada candidato parte do estado observado, aplica as operações na ordem das dependências e
   grava os conjuntos alterados como novos parquet na cópia, com todas as colunas do esquema na
   ordem do esquema, mesmas versões (`artifact_id`) e `DatasetRef` novo (`hash_logico_relacao`
   lh1, `dataset_id` recalculado, `produzido_por: contrafactual_sobreposicao`). O motor confere
   esse conteúdo como confere qualquer insumo (`schema_id`, tipo físico, domínio dos códigos,
   linhagem, hash).

## 4. Revalidação

As regras revalidadas são as regras-alvo (as `VIOLACAO` do bundle) e toda regra do contexto que lê
algum conjunto que uma operação do catálogo altera. Elas são reavaliadas pelo mesmo motor
(`evaluate_rules`) em **todos** os registros do conjunto SIA-PA, primeiro sobre o estado observado
(linha de base) e depois sobre cada candidato. A linha de base precisa reproduzir a violação do
bundle; senão a busca recusa (`contrafactual_baseline_incoerente`). Execução do motor com falha
operacional interrompe a busca (`RevalidacaoFalhou`), nunca vira "sem solução".

Um candidato é solução quando todas as regras-alvo do registro ficam `CONFORME` e nenhum par
(registro, regra) revalidado passa a `VIOLACAO` sem estar em `VIOLACAO` na linha de base. Ficar
`INCONCLUSIVO` não resolve. Uma reclassificação que tira o último vínculo de outro CBO, por
exemplo, viola os registros que dependiam dele e é descartada.

## 5. Busca e minimalidade

Instâncias: cada operação admissível com cada conjunto de parâmetros gerado do registro (e, na
reclassificação, de cada CBO de origem com vínculo no estado observado). Candidatos: combinações
sem repetição de até `max_operacoes` instâncias, com custo igual à soma dos custos. A busca é de
custo uniforme (fila de prioridade por custo, tamanho e índices), então todo candidato de custo `c`
é examinado antes de qualquer um de custo maior. Candidato com precondição falsa (avaliada no
estado da sobreposição depois das operações anteriores) é inadmissível e não conta no orçamento;
`max_candidatos` limita os candidatos simulados e revalidados. Operação com
`competencias_permitidas: ABERTAS` só é admissível quando a competência da busca está aberta.

| Parada (`motivo_parada`) | Soluções | `minimalidade` |
|---|---|---|
| `MINIMO_ENCONTRADO`: todo o nível do menor custo com solução foi examinado | todas as de menor custo | `MINIMO_NO_CATALOGO` se esse custo ≤ (`max_operacoes` + 1) × menor custo de instância; senão `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE` |
| `ORCAMENTO_ESGOTADO` | as encontradas | `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE`; sem solução, `BUSCA_INCONCLUSIVA` |
| `ESPACO_ESGOTADO` (sem solução) | nenhuma | `BUSCA_INCONCLUSIVA` |
| `SEM_OPERACAO_ADMISSIVEL` (nenhum candidato simulado) | nenhuma | `BUSCA_INCONCLUSIVA` |

`custo_max_explorado_completo` é o maior custo cujos candidatos foram todos examinados. Busca
interrompida pelo orçamento nunca declara mínimo, mesmo quando o custo da solução já seria o menor
possível. O limite de operações também limita a prova: uma combinação mais longa que
`max_operacoes` poderia custar menos que a solução encontrada quando esse custo passa de
(`max_operacoes` + 1) × menor custo; aí o resultado é `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE`.
`BUSCA_INCONCLUSIVA` não prova que nenhuma alteração resolveria a violação: só que nenhuma
combinação do catálogo, dentro dos limites, resolveu.

Os testes comparam a busca com uma enumeração completa de referência escrita sem importar o código
de produção (`tests/fixtures/contrafactual_oraculo.py`) em mundos sintéticos pequenos (Hypothesis).

## 6. Executabilidade

A executabilidade de um candidato é decidida nesta ordem:

1. Competência da busca encerrada → `HIPOTESE_PASSADA`. A documentação do CNES (W5,
   `OFICIAL_VISTO_EM_BUSCA`, paráfrase; `A_CONFIRMAR`) diz que o usuário não altera competência
   fechada. Com evidência atual da competência aberta (`competencia_aberta_cnes`), encerrada é a
   anterior a ela; sem essa evidência, toda competência anterior ao mês do relógio é tratada como
   encerrada (lado conservador: nada é declarado executável).
2. Sem evidência atual (competência do mês corrente sem `competencia_aberta_cnes`, ou posterior à
   aberta) → `INDETERMINADO`. Fonte só histórica nunca sustenta execução atual.
3. Competência aberta e alguma operação com governança `FORA_DA_GOVERNANCA_MUNICIPAL` →
   `FORA_DA_GOVERNANCA`.
4. Alguma operação com autoridade ou governança `DESCONHECIDA` → `INDETERMINADO`.
5. Caso contrário → `POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES`.

`condicoes_pendentes` lista, para toda solução, a verdade factual exigida e as precondições de cada
operação (`verdade_factual op=…`, `precondicao op=… nome=…`) e, quando potencialmente executável,
também a competência aberta e a autoridade de cada operação (`competencia_aberta competencia=…`,
`autoridade op=… autoridade=…`). Os textos são modelos fixos; nada é redigido por LLM. Com o
catálogo atual (governança `DESCONHECIDA`), nenhuma solução sai potencialmente executável.

## 7. O que o resultado não afirma

- Não afirma que o registro seria aprovado (`aprovacao_garantida` é sempre `false`), nem que a
  rejeição teve a causa que a regra modela.
- Não afirma que uma alteração feita hoje modificaria uma competência encerrada.
- Não afirma que a verdade factual exigida vale: a alteração é hipotética até que alguém com
  autoridade a confirme fora deste sistema.
- Não identifica nem infere vínculo de profissional específico; não altera diagnóstico, idade,
  sexo ou qualquer fato do atendimento.
- Não afirma que não existe outra alteração: só que, no catálogo fechado e nos limites declarados,
  a solução listada tem o menor custo (`MINIMO_NO_CATALOGO`) ou não tem prova de minimalidade.
