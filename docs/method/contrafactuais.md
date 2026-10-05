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

Cada `op_id` tem efeito, gerador de parâmetros, precondições e dependências obrigatórias
escritos no código (`explanation/counterfactual_operacoes.py`). Invalida o catálogo, inclusive
o passado em `operacoes=` para substituir custos ou governança: operação repetida, sem efeito
conhecido ou com alvo diferente do efeito; precondição ou dependência desconhecida; falta de
precondição ou dependência obrigatória do `op_id`; precondição que o `op_id` não admite
(`precondicao_incompativel_com_operacao`; hoje cada operação admite exatamente as suas
obrigatórias); dependência circular.

| Operação | Conjunto | Parâmetros | Efeito | Precondições | Custo provisório |
|---|---|---|---|---|---|
| `INCLUIR_CBO_NO_ESTABELECIMENTO` | `cnes_estab_cbo.v1` | CNES e CBO do registro | +1 no total do par estabelecimento–CBO | `ESTABELECIMENTO_NO_CNES_ST` | 1 |
| `RECLASSIFICAR_CBO_NO_ESTABELECIMENTO` | `cnes_estab_cbo.v1` | CNES, CBO do registro e `cbo_origem` | −1 no total do CBO de origem, +1 no total do CBO do registro | `ESTABELECIMENTO_NO_CNES_ST`, `CBO_ORIGEM_COM_VINCULO` | 2 |
| `CADASTRAR_ESTABELECIMENTO_NO_CNES` | `cnes_estabelecimento.v1` | CNES do registro | linha do estabelecimento sem atributos | `ESTABELECIMENTO_AUSENTE_NO_CNES_ST` | 3 |

`INCLUIR_CBO_NO_ESTABELECIMENTO` e `RECLASSIFICAR_CBO_NO_ESTABELECIMENTO` dependem de
`CADASTRAR_ESTABELECIMENTO_NO_CNES`: numa combinação com elas, o cadastro do estabelecimento vem
antes. A ordem de aplicação é a das dependências declaradas (nível topológico) e, entre
operações independentes, a ordem das instâncias; cada combinação é simulada numa única ordem.
As contagens são sempre o total do par na versão e competência da busca: linhas repetidas do
mesmo par (aceitas pelo motor, `model.md` §4.5) são somadas, e a operação regrava o par como uma
linha com o novo total (ou nenhuma, se o total chega a zero). As operações atuam no nível
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
CNES ST e a competência que evidência atual mostra aberta no CNES). Sem `contexto`, os insumos
vêm da pasta exata de `bundle.run_id` (`contexto_da_execucao`, §3.1); sem eles a busca recusa
(`contrafactual_sem_contexto`): revalidar é obrigatório e não há como fazê-lo sem os insumos.

1. Todos os arquivos dos insumos são copiados para um diretório temporário; os originais só são
   lidos (cópia e conferência de conteúdo) e nunca mudam.
2. Cada conjunto cadastral editável (`cnes_estab_cbo.v1`, `cnes_estabelecimento.v1`) tem o conteúdo
   conferido contra o `DatasetRef` (linhas e hash lógico) e o tipo físico de todas as colunas do
   esquema conferido contra o esquema canônico pela mesma regra do motor (inteiro de qualquer
   largura, texto `VARCHAR`). Arquivo ilegível, truncado ou com conteúdo divergente é falha
   operacional (`InsumoCadastralInvalido`, `contrafactual_cadastro_invalido`), nunca ausência.
   Leiaute incompatível ou versão em `QUARENTENA_*` torna o conjunto não editável (operações
   sobre ele ficam inadmissíveis). Versão `NAO_VERIFICADO` (ou sem integridade informada) é
   editável, como na seleção do T06, mas só sustenta presença: a precondição de ausência
   (`ESTABELECIMENTO_AUSENTE_NO_CNES_ST`) exige versão `OK`, como a ausência no motor
   (`model.md` §3.3, passo 11); sem isso, a precondição fica indeterminada e a operação,
   inadmissível.
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

### 3.1 Insumos pela execução e CLI

`sustemporal counterfactual --run RUN_ID --row ROW_ID` (`explanation/counterfactual_cli.py`):

1. resolve a pasta exata da execução, `<raiz_saidas>/runs/<run_id>`: o único lugar das execuções do
   `validate` (`sustemporal.execucoes`, o mesmo leitor `ler_execucao` do `explain`), nunca um
   diretório "latest" nem `validacao/`. `run_result.json` e `entrada_validacao.json` só são lidos
   dessa pasta; uma execução que o `validate --saida` gravou fora de `runs/` não é descoberta;
2. recompõe o bundle pelo `explain` real (T08), que reexecuta as evidências;
3. lê `entrada_validacao.json`, que o `validate` grava nos modos `--entrada` e `--ingest` (a
   `EntradaValidacao` da execução: conjunto SIA-PA, `SnapshotSet`, auxiliares, seleção,
   cobertura, integridade, política resolvida e identidade adicional), usa a política gravada (sem
   ela, a que `validate` usa para o método) e recalcula o `run_id` (`calcular_run_id`: conjunto,
   seleção, regras, política, configuração sem `runtime`, auxiliares, integridade e identidade
   adicional, como o recorte territorial do `--ingest`). Divergência é recusa
   (`contrafactual_contexto_diverge_da_execucao`). O CNES ST das precondições é o auxiliar
   `cnes_estabelecimento.v1` gravado na entrada: o `validate --ingest` o grava quando a pasta do
   ingest o traz e o registro e o corte o confirmam como à produção
   (`rules/ingest_cadastros.py::CADASTROS_DO_CONTEXTO`: nenhuma regra o lê, mas ele entra nos
   auxiliares e no `run_id` da execução). Sem CNES ST no contexto (família fora da config do
   piloto, versão ausente, fora do manifesto ou observada só depois do `corte_observacao`), as
   operações ficam inadmissíveis e a busca sai `SEM_OPERACAO_ADMISSIVEL`, nunca com operação
   suposta. A competência aberta fica `None` (só fontes históricas; executabilidade nunca
   potencial);
4. publica `contrafactual.json` e `identidade.json` em
   `<raiz_saidas>/contrafactuais/<run_id>/id_<identidade>/row_<sha256(row_id)[:32]>/`, de forma
   atômica (diretório temporário renomeado). A identidade deriva do SHA-256 de
   `catalog/operations.yaml`, da versão do código e da competência as-of (AAAAMM do mês do
   relógio, lido uma vez no início e usado em toda a busca: ele decide competência fechada e
   executabilidade). Outro catálogo, outro código ou outro mês publica em outro diretório e nunca
   sobrescreve uma hipótese já publicada; instantes do mesmo mês compartilham o destino.
   `identidade.json` registra `competencia_as_of`.

Saída 0 com resultado publicado; 2 para argumento, execução, linha ou insumos ausentes,
ilegíveis (inclusive `run_result.json` ou `entrada_validacao.json` com bytes que não são UTF-8) ou
divergentes e para linha sem violação (nada a buscar; a recusa remove o resultado anterior);
5 para falha operacional (evidência divergente, cadastro ilegível, linha de base que não
reproduz a violação, motor sem concluir): o resultado anterior é removido antes de gravar
`falha.json`, então nunca sobra um `contrafactual.json` antigo, mesmo se a falha não puder ser
gravada. Execução sem `entrada_validacao.json` é recusada com `contexto_da_execucao_ausente`. A configuração
precisa ser a da execução (mesmo `config_hash` fora de `runtime`): o orçamento
`contrafactual` faz parte dela.

## 4. Revalidação

As regras revalidadas são as regras-alvo (as `VIOLACAO` do bundle) e toda regra do contexto que lê
algum conjunto que uma operação do catálogo altera. Elas são reavaliadas pelo mesmo motor
(`evaluate_rules`) em **todos** os registros do conjunto SIA-PA do contexto, primeiro sobre o estado observado
(linha de base) e depois sobre cada candidato. A linha de base precisa reproduzir a violação do
bundle; senão a busca recusa (`contrafactual_baseline_incoerente`). Execução do motor com falha
operacional interrompe a busca (`RevalidacaoFalhou`), nunca vira "sem solução". Registros de
outros conjuntos SIA-PA (outras competências ou municípios) que selecionam a mesma versão do
cadastro não são revalidados; esse limite vai em toda solução como
`revalidacao_restrita dataset=<dataset_id>`.

Um candidato é solução quando todas as regras-alvo do registro ficam `CONFORME` e nenhum par
(registro, regra) revalidado passa a `VIOLACAO` sem estar em `VIOLACAO` na linha de base. Ficar
`INCONCLUSIVO` não resolve. Par que era `CONFORME` e fica `INCONCLUSIVO` (ou
`NAO_APLICAVEL`) não desclassifica o candidato, mas é declarado em `condicoes_pendentes`
(`inconclusao_nova row=… regra=… estado=…`). Uma reclassificação que tira o último vínculo de outro CBO, por
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
| `MINIMO_ENCONTRADO`: todo o nível do menor custo com solução foi examinado | todas as de menor custo com até `max_operacoes` operações | `MINIMO_NO_CATALOGO` se há no máximo `max_operacoes` instâncias ou se esse custo < (`max_operacoes` + 1) × menor custo de instância; senão `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE` |
| `ORCAMENTO_ESGOTADO` | as encontradas | `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE`; sem solução, `BUSCA_INCONCLUSIVA` |
| `ESPACO_ESGOTADO` (sem solução) | nenhuma | `BUSCA_INCONCLUSIVA` |
| `SEM_OPERACAO_ADMISSIVEL` (nenhum candidato simulado) | nenhuma | `BUSCA_INCONCLUSIVA` |

`custo_max_explorado_completo` é o maior custo cujos candidatos foram todos examinados. Busca
interrompida pelo orçamento nunca declara mínimo, mesmo quando o custo da solução já seria o menor
possível. O limite de operações também limita a prova: uma combinação mais longa que
`max_operacoes` poderia custar o mesmo ou menos que a solução encontrada quando esse custo
alcança (`max_operacoes` + 1) × menor custo; aí o resultado é
`SOLUCAO_SEM_PROVA_DE_MINIMALIDADE`. Com `MINIMO_NO_CATALOGO`, nenhuma combinação do catálogo,
de qualquer tamanho, é solução de custo menor, e as soluções listadas são todas as de menor
custo.
`BUSCA_INCONCLUSIVA` não prova que nenhuma alteração resolveria a violação: só que nenhuma
combinação do catálogo, dentro dos limites, resolveu.

Candidatos inadmissíveis (precondição falsa) não contam no orçamento, embora a sobreposição
os aplique para descobri-lo; o estado observado fica em memória e cada avaliação apaga sua
saída do motor depois de lida.

Os testes comparam a busca com uma enumeração completa de referência escrita sem importar o código
de produção (`tests/fixtures/contrafactual_oraculo.py`) em mundos sintéticos pequenos (Hypothesis).

## 6. Executabilidade

A executabilidade de um candidato é decidida nesta ordem:

A competência aberta informada (`competencia_aberta_cnes`) só conta como evidência atual quando é
coerente com o relógio injetado: a competência do mês do relógio ou a do mês anterior. Fora disso
ela é ignorada e toda solução declara `competencia_aberta_inconsistente aberta=… relogio=…`.

1. Competência da busca encerrada → `HIPOTESE_PASSADA`. A documentação do CNES (W5,
   `OFICIAL_VISTO_EM_BUSCA`, paráfrase; `A_CONFIRMAR`) diz que o usuário não altera competência
   fechada. Com evidência atual coerente, encerrada é a anterior à aberta; sem ela, encerrada é
   toda competência anterior ao mês que precede o relógio (lado conservador: nada é declarado
   executável).
2. Sem evidência atual (competência do mês corrente ou do anterior sem evidência coerente, ou
   posterior à aberta) → `INDETERMINADO`. Fonte só histórica nunca sustenta execução atual.
3. Competência aberta e alguma operação de autoridade estadual ou federal (`GESTOR_ESTADUAL`,
   `MINISTERIO_SAUDE`) sem governança `FORA_DA_GOVERNANCA_MUNICIPAL` → `INDETERMINADO`
   (autoridade e governança incoerentes).
4. Alguma operação com governança `FORA_DA_GOVERNANCA_MUNICIPAL` → `FORA_DA_GOVERNANCA`.
5. Alguma operação com autoridade ou governança `DESCONHECIDA` → `INDETERMINADO`.
6. Caso contrário → `POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES`.

`condicoes_pendentes` lista, para toda solução, a verdade factual exigida e as precondições de cada
operação (`verdade_factual op=…`, `precondicao op=… nome=…`) e, quando potencialmente executável,
também a competência aberta e a autoridade de cada operação (`competencia_aberta competencia=…`,
`autoridade op=… autoridade=…`). Toda solução traz ainda `revalidacao_restrita dataset=…`, as
`inconclusao_nova …` e, se for o caso, `competencia_aberta_inconsistente …`. Os textos são
modelos fixos; nada é redigido por LLM. Com o
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
