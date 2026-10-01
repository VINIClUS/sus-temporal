# Validação temporal e explicável de dados administrativos do SUS — Plano de implementação

> **Para agentes de implementação:** executar tarefa por tarefa, com `superpowers:executing-plans` ou `superpowers:subagent-driven-development`, quando disponíveis no ambiente. Os passos marcados com caixas são trabalho futuro. Nenhum resultado experimental é pressuposto por este plano.

**Objetivo:** implementar e avaliar um modelo de restrições versionadas que integre CNES, SIGTAP e SIA, preserve referências temporais e produza explicações verificáveis dos resultados abrangidos pelo modelo.

**Arquitetura:** aplicação local de pesquisa, modular e orientada a lotes. Arquivos originais imutáveis, observações de coleta registradas separadamente, tabelas canônicas em Parquet e motor SQL em DuckDB. Uma interface de linha de comando coordena aquisição, validação, experimentos e relatórios; o núcleo experimental funciona sem rede.

**Stack proposta:** Python, DuckDB, PyArrow/Parquet, Pydantic, PyYAML, pytest/Hypothesis, scikit-learn, Git e ambiente com dependências fixadas. Adaptador de leitura DBC/DBF apoiado em biblioteca existente e verificado antes de uso; PySUS é a primeira candidata, não uma fonte de regras administrativas. PROV para a representação de proveniência. Sem requisito de AWS, APIs pagas, LLM, frontend ou sistema distribuído.

**Especificação-base:** `Esboco_Validacao_Temporal_SUS_Vinicius_Santana(3).pdf`, quatro páginas, §§1–8. Na execução, preservar uma cópia byte a byte em `docs/spec/esboco_original.pdf`, com SHA-256. O documento-base prevalece sobre este plano quanto ao escopo científico; as decisões de engenharia aqui propostas não são resultados nem regras oficiais.

**Data e estado:** 01/10/2026; planejamento. Não foram baixados ou examinados os microdados para elaborar este documento. A disponibilidade histórica, a distribuição dos rótulos e o ganho do alinhamento temporal permanecem questões do piloto.

## Restrições globais

- “O recorte histórico inicial será o dos municípios do Departamento Regional de Saúde XI (Presidente Prudente), de 2018 a 2025, com teste de escala no estado de São Paulo.” [E, §5]
- “O estudo não dependerá de bases municipais restritas nem buscará identificar pacientes.” [E, §5]
- “A falta de campos ou arquivos necessários será registrada como verificação inconclusiva, não como violação.” [E, §5]
- “No BPA consolidado, a verificação cadastral ficará no nível estabelecimento–CBO, sem inferir o vínculo de um profissional específico.” [E, §5]
- “O classificador não receberá o rótulo, campos de erro ou quantidades e valores aprovados como atributos.” [E, §6]
- Não confundir data de coleta com data de registro ou publicação no sistema oficial; não substituir histórico pelo cadastro corrente. [E, §5]
- Não afirmar que uma alteração atual modifica uma competência encerrada, que um contrafactual assegura aprovação, ou que valor de tabela não aprovado equivale a perda financeira. [E, §§5–6]
- Separar achados exploratórios, decisões congeladas e resultados confirmatórios; registrar qualquer alteração posterior à abertura do teste.

## Foco de revisão

| Condição crítica | Comportamento exigido | Tarefa proprietária |
|---|---|---|
| Arquivo ausente, truncado ou incompatível com o leiaute | Quarentena/inconclusão; nunca conjunto vazio tratado como ausência cadastral | T02–T04 |
| Mesmo arquivo coletado novamente, ou conteúdo antigo reaparecendo | Nova observação; não nova versão de conteúdo nem perda do histórico de observações | T02/T06 |
| Atendimento e processamento em competências diferentes, inclusive na borda de 2018 | Resolver as dependências realmente necessárias; nunca escolher automaticamente o mês vizinho | T06–T08 |
| Linhas repetidas, agregadas ou sem identificador longitudinal confiável | Preservar multiplicidades; não inventar paciente, reapresentação ou vínculo entre competências | T03/T10/T12 |
| Contrafactual remove uma violação e cria outra, ou depende de informação local | Revalidar o conjunto afetado; declarar condições pendentes e limite de minimalidade | T09 |

---

## 1. Entregáveis científicos e rastreabilidade

| Requisito do esboço | Entrega verificável | Tarefas |
|---|---|---|
| P1: efeito do alinhamento temporal | Comparações pareadas entre política por regra, competência de atendimento e de processamento; classificador histórico | T06–T08/T10/T11 |
| P2: explicações e correções versus hipóteses passadas | Evidência positiva e negativa, PROV, contrafactuais condicionais e avaliação humana independente | T08/T09/T12 |
| P3: valores associados a incompatibilidades municipais | Agregação exploratória sem dupla contagem, com limites de atribuição | T13 |
| Repositório bitemporal e republicações | Manifestos, observações de coleta, seleção reprodutível de versões e acompanhamento prospectivo | T02/T06/T13 |
| Restrições condicionais e de domínio com vigência | Semântica formal, catálogo documental e tradução para SQL | T07 |
| Avaliação reproduzível | Partições temporais, controles de vazamento, congelamento, tabelas e procedimentos publicáveis | T10–T14 |

**Prioridade:** provar que a pergunta pode ser avaliada antes de construir todos os componentes. A aprovação de um marco depende da qualidade da evidência e da testabilidade, não de encontrar ganho positivo.

A revisão bibliográfica deve produzir uma matriz com problema, unidade de explicação, tratamento de tempo, regras versionadas, observabilidade e avaliação dos trabalhos do esboço. Essa matriz delimita a contribuição: implementar Parquet, DuckDB ou PROV, isoladamente, não constitui a novidade pretendida. [E, §§4 e 8]

## 2. Recorte operacional e marcos de decisão

### G0 — piloto de observabilidade, até a oitava semana

Começar com seis competências de processamento: janeiro e julho de 2018, 2020 e 2022. Essa seleção é uma proposta operacional fixada por calendário, não uma amostra para estimar desempenho. Usar os municípios do DRS XI e, quando o arquivo de distribuição for estadual, filtrar depois de preservar o original. Recuperar as competências auxiliares de CNES e SIGTAP exigidas pelos registros e regras; não presumir que os arquivos do mesmo mês bastam.

Verificar presença e significado de `PA_INDICA`, instrumentos, competências, CBO, procedimento, campos de erro e quantidades/valores apresentados e aprovados. O código do Microdatasus consultado decodifica 0 como não aprovado, 5 como aprovado totalmente e 6 como aprovado parcialmente; isso é um ponto de partida para o código de rótulos, não confirmação de cobertura uniforme em 2018–2025. [W1]

Produzir contagens por competência, instrumento e estabelecimento, taxas de campos ausentes, distribuição da defasagem atendimento–processamento e disponibilidade de cada tabela necessária. Inspecionar rótulos antes e depois do pré-processamento para detectar perdas introduzidas pela ferramenta de leitura. Incluir aprovações na inspeção: estudar somente rejeições impede avaliar falsos alarmes.

**Avançar** quando houver fontes recuperáveis, rótulos utilizáveis, pelo menos duas famílias de regras documentáveis e uma avaliação temporal informativa possível. Duas famílias é uma meta de escopo, não um limiar estatístico. O dimensionamento amostral dependerá das contagens e da dependência entre registros.

**Ampliar para São Paulo**, ainda no desenvolvimento, quando a limitação for quantidade ou diversidade de casos. **Restringir famílias** quando o problema for falta de campos. **Reformular a hipótese e a avaliação com a orientação** quando as rejeições oficiais não forem observáveis, mesmo após a ampliação. Não substituir silenciosamente o desfecho oficial por rótulos sintéticos e continuar chamando o experimento de reprodução do SIA.

### G1 — antes de expandir o motor

Uma cadeia real, pequena e reproduzível deve funcionar: original → normalização → seleção temporal → regra → evidência → comparação com referência. O avaliador de referência da regra será independente do SQL de produção; PA_INDICA continuará sendo referência de resultado, não de causa.

### G2 — antes do teste final

Congelar população, rótulos, políticas, catálogo, comparadores, atributos, métricas, sementes e artefatos. Concluir o dimensionamento do estudo e o manual de anotação. Não exigir superioridade prévia como condição de abertura.

## 3. Arquitetura e organização do repositório

Recomendo um **monólito modular de pesquisa**. Notebooks são adequados à exploração, mas não serão a implementação oficial das regras. Um serviço web distribuído acrescentaria implantação, autenticação e concorrência sem responder às perguntas do esboço. Um demonstrador poderá consumir os relatórios depois que os experimentos estiverem consolidados.

DuckDB sobre Parquet já é a escolha do documento-base. Sua documentação confirma leitura direta e otimizações de projeção e filtros; o plano preserva essa escolha, sem presumir que todo o estado de São Paulo caiba em memória. [E, §5; W2]

```text
sus-temporal/
  README.md
  AGENTS.md
  pyproject.toml
  uv.lock
  config/{pilot,cohort,splits,runtime}.yaml
  catalog/
    sources.yaml
    layouts/
    labels/
    rules/
    policies/
    operations.yaml
  docs/
    spec/esboco_original.pdf
    method/{model,observability,annotation,claims}.md
    decisions/
  src/sustemporal/
    contracts.py
    cli.py
    acquisition/{manifest,fetch,watch}.py
    ingest/{dbc,sia_pa,cnes,sigtap}.py
    temporal/{registry,selector}.py
    rules/{catalog,engine,reference}.py
    rules/sql/
    explanation/{evidence,prov,counterfactual}.py
    evaluation/{labels,split,baselines,metrics,annotation,ablation,values,performance}.py
    reporting/report.py
  tests/{unit,integration,differential,metamorphic,fixtures}/
  experiments/frozen/
  data/{raw,canonical,quarantine}/
  outputs/
```

`data/` e saídas volumosas não entram no Git. Manifestos, código, documentação, testes pequenos e resultados agregados selecionados entram. O projeto não depende de repositórios pessoais existentes. Eventual reaproveitamento de leitores exige revisão, licença compatível e teste de fidelidade; nenhuma implementação existente foi inspecionada para este plano.

**Armazenamento:** arquivos originais endereçados pelo hash; Parquet por fonte, família, UF quando aplicável, competência e versão de conteúdo. Evitar uma partição por estabelecimento. O catálogo consultável em DuckDB deve poder ser reconstruído a partir dos manifestos e arquivos; não introduzir um segundo banco de controle como requisito inicial.

## 4. Modelo de dados e contratos

Os nomes abaixo são internos propostos. O mapeamento para campos físicos do DATASUS será versionado e confirmado pelo piloto, sem inventar colunas que não existam.

| Entidade | Campos essenciais e significado |
|---|---|
| `ArtifactVersion` | `artifact_id`, fonte, família, localizador, competência de referência, SHA-256, tamanho, leiaute e estado de integridade |
| `ArtifactObservation` | `observation_id`, `artifact_id`, instante UTC de coleta, resultado da tentativa e metadados remotos não interpretados como registro oficial |
| `SnapshotSet` | Relação explícita dos artefatos, observações, tabelas e cobertura que uma execução usa |
| `DatasetRef` | Caminho, hash lógico, esquema, contagem, proveniência e multiplicidades da tabela canônica |
| `ProductionRecord` | `row_id`, localizador da linha original, estabelecimento, competências de atendimento/processamento, instrumento, procedimento e atributos observáveis |
| `RuleSpec` | ID, família, versão semântica, predicado de aplicabilidade, validade documentada, seleção temporal, requisitos e referência normativa |
| `RuleEvaluation` | Registro, regra, estado, fontes, consultas, evidências, motivo de inconclusão e política aplicada |
| `RunConfig` / `RunResult` | Configuração/hash, commit, ambiente, conjunto de fontes, regras, política, semente, resultado e tempos |
| `ExplanationBundle` | Avaliações, evidências, representação PROV, texto determinístico e limitações |
| `CounterfactualSearchResult` | Operações, condições, custo, revalidação, orçamento consumido e estado da minimalidade |

Outros tipos compartilhados: `SourceRequest`, `LayoutSpec`, `CohortSpec`, `SplitManifest`, `FeatureSpec`, `AnnotationSample` e `EvaluationReport`. Defini-los em T01, próximos aos contratos que consomem. Usar referências a tabelas para lotes grandes; evitar listas Python com toda a produção estadual.

### Tempo de referência não é tempo de observação

Preservar separadamente: competência de atendimento, competência de processamento, competência do arquivo, vigência documentada da regra e instante em que a pesquisa observou uma versão. A fonte oficial distingue apresentação/processamento do mês de atendimento; esse fato não define sozinho qual competência cada regra deve usar. [W3]

Um arquivo de março de 2020 obtido em 2026 não era, por isso, conhecido pela pesquisa em março de 2020. Tampouco a presença em um retrato mensal demonstra a data exata de início de um vínculo. Não interpolar vigência de vínculos entre meses ausentes sem fundamento documental. O esboço explicita esse limite. [E, §5]

O histórico de coleta será append-only. O mesmo conteúdo recebido duas vezes produz duas observações e uma versão de conteúdo. Se A, depois B, depois A forem observados, preservar as três observações; um simples par `first_seen/last_seen` não descreve adequadamente essa sequência. Quando necessário, derivar intervalos de seleção da pesquisa a partir do histórico, sem apresentá-los como o histórico transacional oficial.

O estudo histórico será **retrospectivo com versões recuperáveis**. A janela recente permitirá estudar revisões efetivamente observadas. Não chamar a retrospectiva de simulação perfeita do conhecimento disponível ao gestor na data original.

### Identidade e normalização

`row_id` combina identidade do artefato, hash e posição do registro original. Isso identifica uma ocorrência no arquivo, não uma pessoa ou tentativa longitudinal. Repetições idênticas devem preservar multiplicidade; equivalência entre republicações exige correspondência não ambígua ou comparação de multiconjuntos.

Manter códigos como texto, inclusive zeros à esquerda. Guardar valor bruto e motivo de normalização de sentinelas; distinguir vazio, desconhecido e não aplicável. Converter idade apenas com unidade conhecida. Quantidades e valores usarão representação decimal/inteira compatível com o leiaute, não ponto flutuante binário para somatórios monetários.

## 5. Motor temporal e catálogo de regras

Para registro `r`, regra `g`, conjunto de versões `S` e política temporal `p`, definir uma avaliação `V(r,g,S,p)` com quatro estados: `CONFORME`, `VIOLACAO`, `INCONCLUSIVO` e `NAO_APLICAVEL`.

`VIOLACAO` exige aplicabilidade conhecida, todos os insumos necessários e incompatibilidade demonstrada. `CONFORME` significa satisfação daquela regra, não aprovação pelo SIA. `INCONCLUSIVO` inclui arquivo ausente, campo insuficiente, vigência não resolvida e ambiguidade de versão relevante. `NAO_APLICAVEL` exige demonstrar que a regra não alcança o registro. Falha do programa é falha operacional, registrada separadamente, não um resultado científico silencioso.

Cada `RuleSpec` terá referência documental com trecho/localização, pressupostos, campos necessários, unidade de avaliação e critério temporal por fonte. As políticas serão `DOCUMENTADA`, `ALTERNATIVA_EXPLORATORIA` ou `NAO_RESOLVIDA`. Alternativas só podem ser escolhidas no desenvolvimento e devem ser fixadas antes do teste. Quando não houver suporte suficiente, manter a abstenção. [E, §5]

**Primeiro incremento:** procedimento–CBO no SIGTAP, existência de estabelecimento–CBO no CNES quando exigida pela regra, instrumento de registro e vigência do procedimento. Selecionar as duas primeiras famílias efetivamente observáveis no piloto. **Incrementos seguintes:** serviço/classificação, habilitação, CID, idade, sexo e quantidade máxima, sempre condicionados ao instrumento e à granularidade. Não comparar um total agregado por estabelecimento com um limite por atendimento/paciente como se fossem a mesma unidade. A documentação SIGTAP caracteriza quantidade máxima no contexto do tratamento/atendimento; a implementação exige verificar a semântica do instrumento. [W7]

A compilação SQL deve evitar multiplicação acidental de registros em junções muitos-para-muitos. Usar testes existenciais ou conjuntos de correspondências conforme a regra. Um `NOT EXISTS` somente poderá sustentar ausência quando o escopo pesquisado, o leiaute e a cobertura da fonte forem suficientes.

Na agregação por registro, guardar separadamente violações, regras conformes e inconclusivas. Uma violação comprovada continua válida mesmo quando outra regra é inconclusiva. Ausência de violações com verificações necessárias incompletas resulta em abstenção, não em “aprovado”.

## 6. Explicações e contrafactuais

Uma explicação contém: registro avaliado, regra e referência, versões escolhidas, motivo da seleção temporal, evidências encontradas e limites de observação. Para ausência cadastral, incluir consulta parametrizada, chaves buscadas, hash da fonte, cobertura, resultado vazio e situação de integridade.

No PROV, representar arquivos, regras e resultados como entidades; aquisição, transformação e avaliação como atividades; software e responsáveis como agentes quando apropriado. Usar relações como `used`, `wasGeneratedBy`, `wasDerivedFrom` e `wasAssociatedWith`. O modelo PROV fornece a representação dessas relações; ele não transforma, por si só, um resultado vazio em prova de inexistência no mundo real. [W4]

Começar com JSON estruturado, exportação PROV-N e texto por templates. Não usar LLM para atribuir causas ou criar rótulos de referência. Cada afirmação do texto deve apontar para um elemento verificável da explicação.

Os contrafactuais operam em uma cópia isolada, usando catálogo fechado de operações cadastrais. Cada operação informa autoridade responsável, verdade factual necessária, competências permitidas, alcance e custo. Não alterar diagnóstico, idade, sexo ou fatos do atendimento para satisfazer regras; não criar vínculo profissional fictício ou classificar toda habilitação como governança municipal.

Minimizar o número de operações, como prevê o esboço. Como configuração inicial de desenvolvimento, explorar até três operações e até mil candidatos por registro; recalibrar esses limites apenas no desenvolvimento. Enumerar custos em ordem crescente, respeitando precondições e dependências. Declarar `MINIMO_NO_CATALOGO` apenas quando todos os candidatos admissíveis de menor custo tiverem sido descartados; caso contrário, `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE` ou `BUSCA_INCONCLUSIVA`.

Reexecutar todas as regras modeladas afetadas e verificar registros dependentes, não só a regra inicialmente violada. Separar: `HIPOTESE_PASSADA`, `POTENCIALMENTE_EXECUTAVEL_SOB_CONDICOES`, `FORA_DA_GOVERNANCA` e `INDETERMINADO`. A classificação de execução atual exige evidência atual suficiente; fontes exclusivamente históricas podem deixá-la indeterminada. A documentação do CNES impede alteração pelo usuário de competências fechadas. [E, §5; W5]

## 7. Desenho experimental

### População, rótulos e partições

Proposta inicial: desenvolvimento em 2018–2022, calibração em 2023 e teste em 2024–2025, por competência de processamento. Preservar atendimento em coluna própria; recuperar dependências temporais fora dessas fronteiras quando necessárias, sem incorporá-las automaticamente à população de resultados. A geografia usará uma lista oficial versionada do DRS XI e uma definição explícita de pertença; a escolha entre recorte fixo e histórico será documentada no piloto antes de construir a coorte.

Dados de teste não podem orientar seleção de regras, política, hiperparâmetros ou recorte. Artefatos já inspecionados para decisões deixam de ser teste intocado. A janela recente de republicações constitui análise separada, não substituição oportunista de um teste com resultado desfavorável. A documentação de validação do scikit-learn destaca os problemas de dependência por grupos e de avaliações temporais inadequadas; o protocolo tratará ambas explicitamente. [W6]

Preservar `PA_INDICA` bruto e rótulo normalizado com origem do código. Analisar aprovação parcial separadamente. Valores desconhecidos e contradições com quantidades/valores serão contabilizados; não corrigir automaticamente o rótulo para favorecer algum método. Campos de erro podem auxiliar diagnóstico e anotação, nunca servir de atributos de predição.

### Métodos comparados

| Método | Implementação proposta |
|---|---|
| `B_ATEND` | Mesmo catálogo de regras, todas as fontes selecionadas pela competência de atendimento |
| `B_PROC` | Mesmo catálogo, todas as fontes pela competência de processamento |
| `B_ML` | Classificador treinado apenas no histórico; começar com regressão logística regularizada e tratamento explícito de categorias desconhecidas |
| `M_TEMP` | Catálogo versionado com seleção por regra/fonte e abstenção quando não observável |
| Controle trivial | Predição da classe prevalente, usada como controle de sanidade, não como principal concorrente |

Manter biblioteca de regras, normalização, tratamento de ausências e artefatos idênticos nos comparadores determinísticos, alterando apenas a política em estudo. O classificador terá lista positiva de atributos, rastreada à origem. Transformações, frequências, balanceamento, seleção de atributos e limiar serão ajustados exclusivamente em treino/calibração. Não fornecer resultados do processamento, dados futuros, campos de erro ou derivados disfarçados desses campos. Todos terão acesso ao mesmo universo autorizado de fontes; a diferença de construção dos atributos será documentada.

Realizar ablações que congelem a versão da regra e outras que troquem isoladamente a versão de CNES ou SIGTAP, mantendo o resto fixo. Isso mede sensibilidade do modelo, não identifica causalmente a origem da decisão oficial.

### Métricas e denominadores

Separar **cobertura de rejeições** (rejeições observadas sinalizadas / rejeições observadas) de **cobertura de verificabilidade** (registros com avaliação suficiente / população). Reportar precisão dos alertas, falsos alertas em aprovações, abstenções, tamanho dos estratos e divergências pareadas. A cobertura populacional deve continuar incluindo rejeições inconclusivas no denominador; apresentar também métricas no domínio comum avaliável, definido sem olhar o resultado dos métodos.

As métricas de rejeição com PA_INDICA avaliam associação/concordância de resultado. Correção da família causal exige a referência independente da anotação. Não tratar “nenhuma violação encontrada” como causa fora de escopo conhecida: distinguir **causa fora de escopo documentada** de **causa indeterminada**.

Proposta de análise: comparações pareadas, intervalos de 95%, duas comparações primárias (`M_TEMP` contra `B_ATEND` e `B_PROC`) e resultados por competência, instrumento e estabelecimento. Calcular bootstrap por estabelecimento, preservando a trajetória mensal completa, e análise de sensibilidade por blocos temporais. Documentar as diferentes populações-alvo e limitações dessas reamostragens; não fingir independência de cada linha nem proteção simultânea contra toda dependência. Usar 2.000 reamostragens e semente 2027 como configuração inicial, congelada antes do teste. Se forem usados testes formais nas duas comparações primárias, fixar a correção por multiplicidade no protocolo.

Escolher margens de relevância prática e dimensionar a amostra com o piloto; não impor ganho percentual inventado nem interpretar ausência de significância como equivalência.

### Anotação das explicações

Preparar cerca de 400 rejeições estratificadas, como no esboço, com dois avaliadores sem acesso à explicação do motor. Usar estratos observáveis independentemente do método — instrumento, período, estabelecimento e defasagem — e registrar probabilidades de inclusão. Não selecionar somente rejeições que o modelo explica. [E, §6]

Usar pequena amostra de desenvolvimento para treinar os avaliadores e ajustar o formulário; excluí-la da avaliação final. O formulário permite múltiplas incompatibilidades, causa indeterminada e evidência insuficiente. Calcular concordância bruta e κ antes da adjudicação; para famílias múltiplas, calcular concordância por família e evitar forçar uma causa única. A adjudicação deve permanecer cega à explicação. O resultado é uma referência humana baseada nas evidências disponíveis, não um log oficial de causa.

Estimar esforço com o tempo medido no treinamento: `horas = 2 × 400 × minutos_por_caso / 60`, mais adjudicação. Com 5–10 minutos por caso, são aproximadamente 67–133 horas de avaliação combinada, uma estimativa de planejamento, não uma medição.

### P3: parcela identificada de valor de tabela não aprovado

Fixar uma única seleção de versões para contabilização. Para cada ocorrência observada, definir `d(r) = valor_apresentado(r) - valor_aprovado(r)`. Em cada estrato de resultado oficial — rejeição e aprovação parcial separadamente — o denominador será a soma de `d(r)` nos registros com ambos os valores conhecidos e diferença não negativa. O numerador será a soma sobre o subconjunto que tenha ao menos uma incompatibilidade cadastral identificada e operação sob governança municipal documentada. Cada ocorrência entra uma vez, mesmo com várias violações.

Informar a razão numerador/denominador somente quando o denominador for positivo. Publicar também contagens e valores dos registros inconclusivos, sem campos suficientes, com diferenças negativas ou com rótulos contraditórios; não convertê-los em zero nem omiti-los da descrição da população. A razão é a parcela identificada no recorte contabilizável, não a parcela de todas as perdas municipais. Reapresentações não vinculáveis permanecem ocorrências distintas: não afirmar que o total deduplica atendimentos ou tentativas que a base não permite reconhecer.

## 8. Plano de execução por tarefas

**Ciclo obrigatório de cada tarefa:** escrever os testes do contrato; executá-los e observar falha pertinente; implementar o mínimo; executar testes e revisão da evidência; registrar um commit pequeno. Os comandos a seguir são contratos de verificação futura — não foram executados sobre uma implementação.

### T01 — Contratos, configuração e esqueleto reprodutível

**Criar:** `pyproject.toml`, `AGENTS.md`, `src/sustemporal/contracts.py`, `config/*.yaml`, `tests/unit/test_contracts.py`, `docs/spec/`.

**Interfaces:** todos os tipos definidos na seção 4; enums de avaliação e minimalidade; `load_config(path: Path) -> RunConfig` em `cli.py`.

- [ ] Escrever testes `test_missing_input_is_not_violation`, `test_observation_time_is_not_reference_period` e `test_original_spec_hash_preserved`.
- [ ] Verificar falha antes da implementação; definir contratos sem conversões silenciosas de códigos.
- [ ] Fixar dependências no ambiente escolhido; configurar execução offline por padrão e comandos de aquisição explícitos.
- [ ] Verificar `pytest tests/unit/test_contracts.py -q`; registrar o ambiente e fazer commit.

**Aceite:** estados e tempos não intercambiáveis; configuração inválida bloqueia a execução antes de processar dados.

### T02 — Aquisição verificável e manifesto

**Criar:** `acquisition/manifest.py`, `acquisition/fetch.py`, `catalog/sources.yaml`, `tests/integration/test_acquisition.py`.

**Interface:** `fetch_source(request: SourceRequest, store: Path) -> ArtifactObservation`.

- [ ] Testar conteúdo repetido, A→B→A, download interrompido, checksum, HTML recebido no lugar de dados e caminho inseguro em arquivo compactado.
- [ ] Implementar download temporário, validação de integridade e promoção atômica; preservar observações e falhas. Não executar binários distribuídos em arquivos de dados.
- [ ] Testar reexecução idempotente, aquisição interrompida e recuperação sem sobrescrever original.
- [ ] Verificar `pytest tests/integration/test_acquisition.py -q`; revisar manifesto e fazer commit.

**Aceite:** toda tabela posterior remonta aos bytes obtidos e à observação correspondente.

### T03 — SIA-PA, rótulos e perfil de observabilidade

**Criar:** `ingest/dbc.py`, `ingest/sia_pa.py`, `evaluation/labels.py`, `catalog/layouts/sia_pa.yaml`, `catalog/labels/sia_pa.yaml`, `tests/integration/test_sia_pa.py`.

**Interfaces:** `normalize_pa(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef`; `label_pa(dataset: DatasetRef, codebook: Path, out: Path) -> DatasetRef`.

- [ ] Testar zeros à esquerda, competências distintas, duplicatas com multiplicidade, registros agregados, 0/5/6, códigos desconhecidos e valores contraditórios.
- [ ] Validar o adaptador DBC/DBF contra uma leitura independente e registrar biblioteca/versão; não aceitar filtros implícitos que removam registros não aprovados.
- [ ] Produzir perfil por estrato a partir do bruto e do canônico, com reconciliação das contagens.
- [ ] Verificar `pytest tests/integration/test_sia_pa.py -q`; revisar amostra manual e fazer commit.

**Aceite:** todas as perdas/transformações são explicadas; rótulos permanecem separados de atributos de predição.

### T04 — CNES, SIGTAP e cobertura por regra

**Criar:** `ingest/cnes.py`, `ingest/sigtap.py`, `catalog/layouts/{cnes,sigtap}.yaml`, `tests/integration/test_reference_sources.py`.

**Interfaces:** `normalize_cnes(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef`; `normalize_sigtap(artifact: ArtifactVersion, layout: LayoutSpec, out: Path) -> DatasetRef`.

- [ ] Testar componente ausente, cardinalidade muitos-para-muitos, sentinelas, mudança de leiaute e identificadores com zeros.
- [ ] Mapear tabelas efetivamente disponíveis para estabelecimento–CBO, serviços/classificações, habilitações e compatibilidades SIGTAP; preservar documentação e notas técnicas.
- [ ] Produzir matriz família × instrumento × competência com estados disponível, insuficiente e ausente.
- [ ] Verificar `pytest tests/integration/test_reference_sources.py -q`; revisar cobertura e fazer commit.

**Aceite:** uma fonte “carregada” não implica automaticamente que todas as famílias de regras são verificáveis.

### T05 — Relatório do piloto e decisão G0

**Criar:** `reporting/report.py`, `docs/method/observability.md`, `outputs/pilot/`, `tests/integration/test_pilot_report.py`.

**Interface:** `build_pilot_report(datasets: list[DatasetRef], cohort: CohortSpec, out: Path) -> EvaluationReport`.

- [ ] Testar totais, denominadores, classificação dos registros inconclusivos e inclusão de aprovações.
- [ ] Executar as seis competências de desenvolvimento e registrar fontes auxiliares necessárias, bytes, tempo e casos de defasagem.
- [ ] Documentar decisão: continuar, ampliar SP, restringir famílias ou reformular o desfecho. Separar limitação amostral de ausência estrutural de informação.
- [ ] Verificar `pytest tests/integration/test_pilot_report.py -q`; revisar o relatório com a orientação antes de ampliar o projeto.

**Aceite:** a pergunta experimental e seus limites são explícitos; não se exige ganho positivo.

### T06 — Registro e seleção temporal

**Criar:** `temporal/registry.py`, `temporal/selector.py`, `catalog/policies/`, `tests/unit/test_temporal_selector.py`.

**Interface:** `select_snapshots(record: ProductionRecord, rule: RuleSpec, config: RunConfig) -> SnapshotSet`.

- [ ] Testar atendimento diferente de processamento, arquivo auxiliar anterior a 2018, republicação tardia, ausência no mês exigido e política documental ambígua.
- [ ] Implementar seleção explícita por fonte/regra e corte de observação da pesquisa, sem retroagir a data da coleta.
- [ ] Verificar que um conjunto congelado não muda quando chegam novas versões.
- [ ] Verificar `pytest tests/unit/test_temporal_selector.py -q`; documentar semântica e fazer commit.

**Aceite:** toda versão selecionada tem justificativa reproduzível ou a avaliação se abstém.

### T07 — Catálogo formal e primeiro motor SQL

**Criar:** `rules/catalog.py`, `rules/engine.py`, `rules/reference.py`, `rules/sql/`, `catalog/rules/`, `docs/method/model.md`, `tests/differential/test_rules.py`, `tests/metamorphic/test_rules.py`.

**Interface:** `evaluate_rules(dataset: DatasetRef, snapshots: SnapshotSet, rules: list[RuleSpec], config: RunConfig, out: Path) -> RunResult`.

- [ ] Escrever casos manuais para cada estado e regra; o avaliador de referência não reutiliza o predicado SQL ou seu seletor.
- [ ] Formalizar aplicabilidade, seleção de versões, restrições condicionais/de domínio e agregação de resultados; implementar as primeiras famílias aprovadas em G0.
- [ ] Testar invariância à ordem, reexecução, inclusão de linhas irrelevantes e mudança apenas nos registros dependentes de uma alteração.
- [ ] Verificar `pytest tests/differential tests/metamorphic -q`; revisar referência normativa e fazer commit por família.

**Aceite:** equivalência aos exemplos e ao avaliador independente, sem alegar que testes sintéticos validam a hipótese empírica. Expandir famílias somente após esse aceite.

### T08 — Baselines determinísticos e evidência PROV

**Criar:** `evaluation/ablation.py`, `explanation/evidence.py`, `explanation/prov.py`, `tests/integration/test_baselines.py`, `tests/unit/test_provenance.py`.

**Interface:** `explain(run: RunResult, row_id: str) -> ExplanationBundle`.

- [ ] Testar `B_ATEND` e `B_PROC` com o mesmo motor; conferir que só a política muda.
- [ ] Testar ausência documentada, fonte incompleta, vínculo encontrado e rastreabilidade de cada afirmação do texto.
- [ ] Gerar JSON, PROV-N e relatório legível por templates; verificar a reexecução de consultas de evidência.
- [ ] Verificar `pytest tests/integration/test_baselines.py tests/unit/test_provenance.py -q`; revisar exemplos reais e fazer commit.

**Aceite:** alcançar G1; uma explicação não atribui causa oficial apenas porque uma regra falhou.

### T09 — Contrafactuais com limites explícitos

**Criar:** `catalog/operations.yaml`, `explanation/counterfactual.py`, `tests/unit/test_counterfactual.py`.

**Interface:** `search_counterfactuals(bundle: ExplanationBundle, config: RunConfig) -> CounterfactualSearchResult`.

- [ ] Testar solução de uma operação, dependência entre operações, violação nova, competência fechada, autoridade desconhecida e orçamento esgotado.
- [ ] Implementar busca de custo crescente, simulação isolada e revalidação das dependências; não alterar originais.
- [ ] Comparar a minimalidade com enumeração completa em instâncias pequenas; não declarar minimalidade quando a busca for interrompida.
- [ ] Verificar `pytest tests/unit/test_counterfactual.py -q`; revisar governança com especialista e fazer commit.

**Aceite:** alteração hipotética, operação potencialmente executável e garantia de aprovação nunca aparecem como sinônimos.

### T10 — Coortes, classificador e proteção contra vazamento

**Criar:** `evaluation/split.py`, `evaluation/baselines.py`, `config/splits.yaml`, `tests/integration/test_no_leakage.py`.

**Interfaces:** `build_splits(dataset: DatasetRef, cohort: CohortSpec, out: Path) -> SplitManifest`; `fit_baseline(split: SplitManifest, features: FeatureSpec, config: RunConfig, out: Path) -> RunResult`.

- [ ] Testar separação temporal, proibição de campos pós-processamento e transformações ajustadas só em treino.
- [ ] Implementar classificador e controle trivial; auditar origem de cada atributo e dados permitidos em cada corte.
- [ ] Tratar republicações como versões da mesma fonte, não observações independentes; registrar limites de identificação longitudinal.
- [ ] Verificar `pytest tests/integration/test_no_leakage.py -q`; congelar seleção de atributos e fazer commit.

**Aceite:** ausência de vazamento demonstrada por contrato e testes; um baseline fraco por erro de implementação não conta como evidência a favor do método.

### T11 — Métricas, congelamento e teste

**Criar:** `evaluation/metrics.py`, `experiments/frozen/`, `tests/unit/test_metrics.py`, `tests/integration/test_freeze.py`.

**Interface:** `evaluate_runs(runs: list[RunResult], labels: DatasetRef, split: SplitManifest, out: Path) -> EvaluationReport`.

- [ ] Validar precisão, cobertura, falsos alertas, abstenção e aprovações parciais com tabelas pequenas calculadas à mão.
- [ ] Fixar protocolo, comparações, reamostragem, margens e hashes; emitir manifesto único com a configuração congelada.
- [ ] Executar comparações pareadas no teste uma vez que G2 esteja aprovado; registrar toda execução, inclusive resultados nulos.
- [ ] Verificar `pytest tests/unit/test_metrics.py tests/integration/test_freeze.py -q`; reproduzir as tabelas a partir das saídas imutáveis.

**Aceite:** resultados confirmatórios distinguíveis da exploração. Correção de bug após abertura gera nova versão e declaração explícita, não apagamento da rodada anterior.

### T12 — Avaliação humana cega

**Criar:** `evaluation/annotation.py`, `docs/method/annotation.md`, `tests/integration/test_annotation_blinding.py`.

**Interface:** `prepare_annotation_sample(labels: DatasetRef, split: SplitManifest, config: RunConfig, out: Path) -> AnnotationSample`.

- [ ] Testar que formulários e pacotes não contêm resultados/explicações do motor nem identificadores desnecessários.
- [ ] Treinar dois avaliadores em exemplos de desenvolvimento; medir tempo e ajustar o formulário antes de congelá-lo.
- [ ] Sortear a amostra estratificada, recolher avaliações independentes, medir concordância e realizar adjudicação cega.
- [ ] Verificar `pytest tests/integration/test_annotation_blinding.py -q`; comparar com o motor só após fechar a referência.

**Aceite:** referência independente, indeterminados preservados e amostragem documentada. Não afirmar precisão causal populacional a partir de subconjunto selecionado pelo modelo.

### T13 — Republicações, valores e escala

**Criar:** `acquisition/watch.py`, `evaluation/values.py`, `evaluation/performance.py`, `tests/integration/test_republications.py`, `tests/unit/test_values.py`.

**Interfaces:** `observe_updates(requests: list[SourceRequest], store: Path) -> list[ArtifactObservation]`; `summarize_values(run: RunResult, labels: DatasetRef, out: Path) -> DatasetRef`.

- [ ] Testar conteúdo inalterado, revisão real, correspondência ambígua entre versões e uma linha com múltiplas violações.
- [ ] A partir do piloto, acompanhar semanalmente uma janela móvel de seis competências recentes durante doze meses; preservar também tentativas sem mudança. Cadência/janela são propostas operacionais, não garantias de capturar todas as revisões.
- [ ] Medir troca isolada de fontes, valores apresentados menos aprovados, memória, armazenamento e tempo no DRS XI e SP. Reportar valores negativos ou contraditórios como categoria própria; não truncá-los silenciosamente.
- [ ] Verificar `pytest tests/integration/test_republications.py tests/unit/test_values.py -q`; revisar agregações e registrar ambiente/cache/repetições dos testes de escala.

**Aceite:** uma ocorrência contribui uma vez ao total global de valores, mesmo com múltiplas regras. Totais por família sobrepostos não são somados. Ausência de revisão observada não significa que nunca houve revisão.

### T14 — Artefato reproduzível e dissertação

**Criar:** documentação operacional, relatório final, pacote de exemplos e `tests/integration/test_reproduce_offline.py`.

**Interface:** `reproduce(config: RunConfig, out: Path) -> EvaluationReport`, exposta na CLI.

- [ ] Reproduzir um conjunto pequeno desde originais locais até tabelas finais, em ambiente limpo e sem rede.
- [ ] Verificar hashes lógicos e igualdade das contagens/métricas; distinguir diferenças de bytes Parquet de diferenças de conteúdo.
- [ ] Auditar direitos de redistribuição e exposição desnecessária; publicar código, catálogo, procedimentos, manifestos e dados permitidos. Fornecer instruções de reconstrução quando redistribuição não estiver assegurada.
- [ ] Verificar `pytest tests/integration/test_reproduce_offline.py -q`; revisar cada conclusão contra sua evidência em `docs/method/claims.md`.

**Aceite:** terceiro consegue reproduzir o fluxo documentado; nenhum resultado de teste de software é apresentado como confirmação empírica do método.

## 9. Interface de execução planejada

Estes comandos serão implementados; não estão disponíveis nesta entrega:

```bash
sustemporal acquire --config config/pilot.yaml
sustemporal ingest --config config/pilot.yaml
sustemporal pilot-report --config config/pilot.yaml
sustemporal validate --config config/cohort.yaml --policy documented
sustemporal explain --run RUN_ID --row ROW_ID
sustemporal counterfactual --run RUN_ID --row ROW_ID
sustemporal freeze --config config/splits.yaml
sustemporal evaluate --freeze FREEZE_ID
sustemporal annotation-export --freeze FREEZE_ID
sustemporal reproduce --freeze FREEZE_ID --offline
```

IDs de execução e congelamento devem resolver artefatos exatos, nunca um diretório “latest” mutável. Comandos de avaliação recusam fontes ou código incompatíveis com o manifesto congelado, salvo execução exploratória explicitamente identificada.

## 10. Cronograma, recursos e contenção do escopo

| Período | Trabalho principal e marco |
|---|---|
| Semanas 1–2 | T01/T02, primeiras leituras PA, inventário documental e identificação dos avaliadores |
| Semanas 3–4 | T03/T04, reconciliação de contagens e primeiros cruzamentos |
| Semanas 5–8 | T05, demonstração mínima e decisão G0; iniciar observação de versões recentes |
| Meses 3–6 | T06/T07, revisão aprofundada, formalização, coorte e cadeia mínima |
| Meses 7–12 | T08/T10, expansão controlada das regras, comparadores, qualificação e protocolo; G1 |
| Meses 13–18 | T09/T11/T12/T13, G2, teste, explicações, análise e preparação de artigo |
| Meses 19–24 | T14, artefatos, redação consolidada, submissão e defesa |

A tabela preserva o horizonte de 24 meses do esboço. Redação, revisão e registro de resultados ocorrem desde o primeiro mês; a coleta de republicações roda em paralelo, pois versões não coletadas hoje podem deixar de ser recuperáveis. Os marcos acadêmicos devem ser ajustados com a orientação e as exigências efetivas do programa, não assumidos como calendário institucional confirmado.

**Ambiente inicial proposto:** usar a máquina Linux já disponível, um processo de escrita e lotes por competência; medir memória e disco antes de expandir. Como perfil de ensaio, limitar DuckDB a 8 GB e quatro threads apenas quando houver memória física suficiente; reduzir limites em máquinas menores. Não adquirir infraestrutura antes do piloto. Armazenamento deve ser estimado a partir dos bytes reais de originais, Parquet, temporários e versões observadas, com margem explicitada.

**Prioridades de corte:** retirar primeiro frontend, serviços, LLM, múltiplos classificadores sofisticados e formalização mecanizada extensa. Reduzir o número de famílias antes de enfraquecer observabilidade, independência do teste ou rastreabilidade. Alloy pode auxiliar uma propriedade temporal bem delimitada, mas não é condição inicial; usar Alloy, TLA+ e Lean simultaneamente não é um entregável do esboço.

**Primeira autorização de execução recomendada:** somente T01–T05. O próximo investimento em motor completo depende da decisão documentada de G0. O primeiro sucesso procurado não é alta acurácia: é uma amostra auditável que mostre o que pode e o que não pode ser afirmado com as fontes públicas.

## Fontes e distinção de fundamento

[E] Esboço anexado, `Esboco_Validacao_Temporal_SUS_Vinicius_Santana(3).pdf`, especialmente §§2, 5, 6, 7 e 8. Fonte dos objetivos, recorte, hipóteses e limites. Os contratos, tarefas, partições específicas e configurações deste plano são propostas de implementação.

Fontes técnicas primárias consultadas em 01/10/2026; preservar uma cópia/versão na execução, pois documentação corrente não comprova automaticamente a semântica histórica:

[W1] Microdatasus, código `R/process_sia.R`, bloco `PA_INDICA`. URL: `https://github.com/rfsaldanha/microdatasus/blob/master/R/process_sia.R`.

[W2] DuckDB, Reading and Writing Parquet Files. URL: `https://duckdb.org/docs/current/data/parquet/overview`.

[W3] Ministério da Saúde, Manual do BPA, configuração de competência. URL: `https://wiki.saude.gov.br/sia/index.php/BPA`.

[W4] W3C, PROV-DM, componentes e relações de proveniência. URL: `https://www.w3.org/TR/prov-dm/`.

[W5] Ministério da Saúde, CNES — Dúvidas Frequentes, competências fechadas. URL: `https://wiki.saude.gov.br/cnes/index.php/D%C3%BAvidas_Frequentes`.

[W6] Scikit-learn, Cross-validation: evaluating estimator performance. URL: `https://scikit-learn.org/stable/modules/cross_validation.html`.

[W7] Ministério da Saúde, SIGTAP — Gerais, quantidade máxima. URL: `https://wiki.saude.gov.br/sigtap/index.php/Gerais`.

[W8] Ministério da Saúde, SIGTAP — Download, arquivos mensais e notas técnicas. URL: `https://wiki.saude.gov.br/sigtap/index.php/Download`.

[W9] PySUS, documentação do projeto; apoio técnico à aquisição/leitura, sujeito a teste de fidelidade. URL: `https://pysus.readthedocs.io/`.
