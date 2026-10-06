# Alegações possíveis da dissertação (T14)

Registro de cada conclusão que a dissertação poderia afirmar, com a evidência exigida, o portão
humano ou o dado real de que depende e o estado atual. É o roteiro da revisão final do plano (T14:
"revisar cada conclusão contra sua evidência"): nenhum enunciado entra no texto sem a evidência
listada aqui. Os enunciados abaixo são conclusões possíveis, escritas como hipóteses a confirmar;
nenhum deles é um resultado.

## Estado atual

- O repositório está em pré-G0. Nenhum dado real foi processado aqui e `experiments/decisions/` só
  traz o modelo `MODELO_G0.yaml`, que nunca libera portão: não existe decisão G0, G1 ou G2, nem
  decisão sobre alguma alegação.
- O esboço (`docs/spec/esboco_original.pdf`) está PENDENTE em `docs/spec/manifest.yaml` e prevalece
  sobre o plano quanto ao escopo científico. Os enunciados de P1, P2 e P3 seguem o plano e precisam
  ser conferidos contra o esboço antes de qualquer redação final.
- Por isso toda alegação está PENDENTE.

## O que não é evidência

Nenhum teste de software é confirmação empírica do método. Teste unitário, de propriedade,
diferencial, metamórfico ou de integração verifica a implementação contra a especificação, e uma
execução sobre fixtures sintéticas (`origem_dados = SINTETICO`) é sempre exploratória e nunca
confirmatória (`docs/decisions/0003-escopo-pre-g0.md`). Também não valem como evidência:

- uma regra em `VIOLACAO`, que é alerta do modelo sobre as versões selecionadas e não o motivo
  registrado pelo sistema oficial;
- a ausência de violação, que é conformidade com aquela regra e não aprovação pelo SIA;
- `PA_INDICA` lido como causa: ele é referência de resultado;
- valor de tabela não aprovado lido como dinheiro perdido;
- uma alteração hipotética de contrafactual lida como se o registro fosse ser aprovado ou como se
  modificasse uma competência encerrada.

## Campos e vocabulário

Cada alegação é um bloco `### AL-NN — título` com os campos abaixo.

- **Conclusão possível:** o enunciado que a dissertação poderia afirmar.
- **Natureza:** DESCRITIVA (o que as fontes permitem observar, no piloto), EXPLORATORIA
  (desenvolvimento, calibração ou análise sem teste intocado) ou CONFIRMATORIA (comparação no teste
  de 2024–2025, depois de G2 e do congelamento).
- **Evidência exigida:** o que precisa existir, preservado, para o enunciado valer.
- **Depende de:** G0, G1 e G2 (decisão humana registrada em `experiments/decisions/`); DADOS_REAIS
  (execução sobre arquivos oficiais reais, na máquina do pesquisador e fora do Git);
  DOCUMENTO_OFICIAL (documento oficial preservado, com trecho, localização e SHA-256); ESPECIALISTA
  (revisão de governança); AVALIADORES (anotação humana cega); ORIENTACAO (revisão ou decisão com a
  orientação); ESBOCO (conferência com o esboço original, hoje PENDENTE).
- **Estado:** PENDENTE (sem a evidência nem o portão), EXPLORATORIA (há resultado exploratório com
  dados reais, sem congelamento), CONFIRMADA ou NAO_CONFIRMADA (resultado sob os portões exigidos; o
  resultado nulo também se registra). Todo estado diferente de PENDENTE exige a decisão humana da
  regra 2 de "Regras de atualização".
- **Limites:** o que não se conclui mesmo com a evidência.
- **Ferramentas** e **Pendências:** os comandos e módulos que produzem a evidência e as chaves de
  pendência (`docs/PENDENCIAS.md`) que bloqueiam a alegação.

## Regras de atualização

O estado de uma alegação só muda com decisão humana que a cite. Verificadas por
`tests/unit/test_alegacoes.py` e `tests/unit/test_alegacoes_decisoes.py`:

1. Toda alegação tem conclusão possível, natureza, evidência exigida, dependência (um portão ou dado
   real), estado e limites, com os valores do vocabulário acima.
2. Todo estado diferente de PENDENTE aparece, com o id da alegação e o mesmo estado, na decisão mais
   recente que a cita: arquivo `experiments/decisions/alegacoes/<AAAA-MM-DD>.yaml`, com a chave
   `alegacoes` (`AL-NN: ESTADO`), `data`, `responsaveis` e `evidencias` (listas não vazias) e
   `registrado_por_humano: true`. Reprovam: estado sem decisão que cite a alegação; estado diferente
   do decidido (inclusive PENDENTE depois de decidida); arquivo de decisão inválido ou em link
   simbólico (como em `sustemporal.gates`, o diretório também); duas decisões da mesma data com
   estados diferentes; decisão sobre alegação que não existe. Não contam arquivo `MODELO_*` nem
   decisão fora desse subdiretório. A decisão da alegação não substitui a do portão, nem o
   contrário.
3. CONFIRMADA e NAO_CONFIRMADA exigem também a decisão humana de cada portão (G0, G1 ou G2) citado
   em `Depende de`, em `experiments/decisions/`; o modelo `MODELO_*` nunca libera.
4. Alegação CONFIRMATORIA depende de G2 e de DADOS_REAIS.
5. Alegação que depende do ESBOCO não é CONFIRMADA nem NAO_CONFIRMADA enquanto o esboço estiver
   PENDENTE.
6. O texto não usa a linguagem que o AGENTS.md proíbe (Restrições globais e
   `docs/process/revisao.md`, item 7).
7. Os caminhos do repositório citados existem.

O que o teste não garante, e quem garante:

- **Quem escreveu a decisão.** A autoridade humana vem do caminho: em `docs/process/propriedade.yaml`,
  `experiments/decisions/` é só de humanos (menos `MODELO_*` e `README.md` no nível superior) e o CI
  de propriedade, que lê o mapa da base do PR, reprova PR de agente que crie, altere ou apague
  arquivo ali. O teste confere só que o mapa continua tratando os arquivos de
  `experiments/decisions/alegacoes/*.yaml` como só de humanos, para todos os donos.
- **O mérito da evidência.** O teste confere que a decisão cita a alegação e traz responsáveis e
  evidências preenchidos; ler a evidência e decidir é da revisão humana.
- **O local da decisão.** Fica num subdiretório porque `sustemporal.gates` lê todo `*.yaml` de
  `experiments/decisions/` como decisão de portão (`DecisaoPortao`), que recusa campos extras; o
  teste confere que o subdiretório não entra nesse carregamento.

## Alegações

### AL-01 — Fontes recuperáveis no recorte do piloto

- **Conclusão possível:** A confirmar: as fontes necessárias (SIA-PA, CNES, SIGTAP e os documentos
  de apoio) são recuperáveis para as seis competências de processamento do piloto no DRS XI, com
  cada original preservado e cada tentativa registrada, inclusive as que não trouxeram bytes.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Manifesto de aquisição real (`aquisicao.jsonl`: SHA-256 de cada original e
  observação de cada tentativa) e as tabelas `piloto_disponibilidade.v1` e `piloto_inconclusivos.v1`
  do `pilot-report`, em que tentativa sem bytes e quarentena por falha de coleta contam como falha
  de coleta e não como ausência da fonte.
- **Depende de:** G0, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** Ausência de observação não é ausência de publicação. As seis competências são uma
  proposta operacional fixada por calendário, não uma amostra para estimar desempenho.
- **Ferramentas:** `sustemporal acquire`, `sustemporal ingest`, `sustemporal pilot-report`
- **Pendências:** T02-1, T02-2, T05-1, T13-2

### AL-02 — Leiautes e leitura conferidos contra arquivos reais

- **Conclusão possível:** A confirmar: os leiautes do SIA-PA, do CNES (PF e ST) e do SIGTAP conferem
  com os cabeçalhos dos arquivos reais de 2018 a 2025, e a leitura DBC e DBF é fiel aos bytes
  originais.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Conferência do cabeçalho de cada arquivo real contra `catalog/layouts/`
  (roteiro do piloto, passo 2), registrada em `docs/references/fontes.md` com nome, competência e
  SHA-256; relatório de fidelidade da leitura (`verificar_fidelidade`, modo COMPLETA) por lote;
  perfil por estrato (`perfil_pa`) que reconcilia bruto e canônico.
- **Depende de:** G0, DADOS_REAIS, DOCUMENTO_OFICIAL
- **Estado:** PENDENTE
- **Limites:** Os leiautes de hoje são INFERIDA ou SECUNDARIA e A_CONFIRMAR; arquivo com outro
  leiaute vai para quarentena e nunca é convertido. A codificação real do texto segue A_CONFIRMAR (a
  leitura é em latin-1, bijetiva).
- **Ferramentas:** `src/sustemporal/ingest/dbc.py`, `src/sustemporal/evaluation/labels.py`,
  `sustemporal ingest`
- **Pendências:** T03-1, T03-11, T04-1, T04-17, T05-2

### AL-03 — PA_INDICA como rótulo utilizável

- **Conclusão possível:** A confirmar: o desfecho oficial é observável: `PA_INDICA` permite um
  rótulo normalizado utilizável no recorte, com a cobertura do campo, a distribuição dos códigos (0,
  5, 6 e desconhecido) e as contradições com quantidades e valores medidas por competência.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** `piloto_rotulos.v1` (antes e depois do pré-processamento, aprovações
  incluídas), `piloto_campos.v1` e a reconciliação entre bruto e canônico, com revisão manual de
  amostra estratificada por competência, instrumento e `PA_INDICA`; sem correção automática do
  rótulo.
- **Depende de:** G0, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** O código do Microdatasus (0 não aprovado, 5 aprovado totalmente, 6 aprovado
  parcialmente) é ponto de partida e não prova cobertura uniforme em 2018–2025. `PA_INDICA` é
  referência de resultado, não de causa.
- **Ferramentas:** `sustemporal pilot-report`, `src/sustemporal/evaluation/labels.py`
- **Pendências:** T03-13, T03-14, T05-11, T05-16

### AL-04 — Famílias de regras observáveis e documentadas

- **Conclusão possível:** A confirmar: ao menos duas famílias de regras documentáveis são
  observáveis no piloto (cobertura DISPONIVEL por família, instrumento e competência), de modo que
  uma avaliação temporal informativa é possível.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** `cobertura.v1` e `piloto_disponibilidade.v1` reais; referência normativa
  preservada de cada regra candidata (trecho, localização, SHA-256, `estado: PRESERVADO`); decisão
  humana G0 que escolhe as famílias.
- **Depende de:** G0, DADOS_REAIS, DOCUMENTO_OFICIAL
- **Estado:** PENDENTE
- **Limites:** "Duas famílias" é meta de escopo, não limiar estatístico. Fonte carregada não implica
  que todas as famílias sejam verificáveis. As famílias de hoje são `CANDIDATA_PRE_G0`.
- **Ferramentas:** `sustemporal ingest`, `sustemporal pilot-report`, `catalog/rules/`
- **Pendências:** T04-24, T07-i1, T07-i3, T06-1, T02-12

### AL-05 — Defasagem entre atendimento e processamento

- **Conclusão possível:** A confirmar: a competência de atendimento difere da de processamento em
  uma parcela mensurável dos registros do recorte, e a distribuição dessa defasagem, em meses, é
  descrita sem escolher o mês vizinho.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** `piloto_defasagem.v1` real por competência de processamento, com as linhas
  de atendimento nulo contadas à parte e os casos da borda de 2018 listados.
- **Depende de:** G0, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** A defasagem é contada, não corrigida, e não define qual competência cada regra deve
  usar: isso é política temporal. O fato de a fonte oficial distinguir apresentação de mês de
  atendimento não fixa, sozinho, a competência de cada regra.
- **Ferramentas:** `sustemporal pilot-report`
- **Pendências:** T05-1, T04-24

### AL-06 — Natureza da limitação observada e decisão G0

- **Conclusão possível:** A confirmar: a limitação observada no piloto é amostral ou estrutural,
  separadas com denominadores explícitos, e a decisão G0 (continuar, ampliar para São Paulo,
  restringir famílias ou reformular a hipótese) decorre dessa evidência e da revisão com a
  orientação.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Relatório real do piloto (`piloto_exclusoes.v1`, `piloto_inconclusivos.v1`,
  `piloto_campos.v1`, `piloto_disponibilidade.v1`) com a classificação dos inconclusivos; decisão
  humana `G0_<AAAA-MM-DD>.yaml` em `experiments/decisions/`, com evidências e responsáveis.
- **Depende de:** G0, DADOS_REAIS, ORIENTACAO
- **Estado:** PENDENTE
- **Limites:** Relatório SINTETICO não sustenta decisão. Não se substitui o desfecho oficial por
  rótulos sintéticos continuando a chamar o experimento de reprodução do SIA. Não se exige ganho
  positivo.
- **Ferramentas:** `sustemporal pilot-report`, `experiments/decisions/MODELO_G0.yaml`
- **Pendências:** T05-3, T05-4, T05-5, T05-6

### AL-07 — Política temporal documentada por regra e fonte

- **Conclusão possível:** A confirmar: para as famílias aprovadas no G0 existe critério temporal
  documentado por regra e fonte (competência de atendimento, de processamento ou outra), de modo que
  `M_TEMP_PADRAO` deixa de ser NAO_RESOLVIDA e a política DOCUMENTADA tem documento oficial
  preservado.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Documentos oficiais preservados, com trecho, localização e SHA-256, que
  fundamentam cada critério; políticas em `catalog/policies/` sem documento pendente; alternativas
  exploratórias fixadas no desenvolvimento antes do teste.
- **Depende de:** G0, DOCUMENTO_OFICIAL, ORIENTACAO
- **Estado:** PENDENTE
- **Limites:** Sem documento que sustente o critério, `M_TEMP` se abstém; a documentação corrente
  não comprova a semântica histórica. Alternativa exploratória só pode ser escolhida no
  desenvolvimento.
- **Ferramentas:** `catalog/policies/`, `sustemporal validate --policy documented`
- **Pendências:** T06-1, T07-i4, T05-8

### AL-08 — Catálogo formal de regras com vigência e referência normativa

- **Conclusão possível:** A confirmar: as restrições condicionais e de domínio das famílias
  aprovadas estão formalizadas com semântica de quatro estados, vigência e referência normativa
  documental, e a tradução para SQL coincide com um avaliador independente.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** `RuleSpec` com `referencia` preservada (trecho, localização, SHA-256) para
  cada regra aprovada; equivalência entre o motor SQL e `src/sustemporal/rules/reference.py` (teste
  diferencial) e, na cadeia real, comparação do resultado com o avaliador de referência; decisão G0
  das famílias.
- **Depende de:** G0, G1, DOCUMENTO_OFICIAL, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** Teste sintético verifica a implementação contra a especificação, não a hipótese
  empírica. `CONFORME` é satisfação da regra e não aprovação pelo SIA; ausência de violação com
  verificação incompleta é abstenção.
- **Ferramentas:** `sustemporal validate`, `catalog/rules/`, `tests/differential/test_rules.py`
- **Pendências:** T07-i3, T07-i5, T07-i6, T07-i7, T07-i8

### AL-09 — Cadeia real mínima (G1)

- **Conclusão possível:** A confirmar: uma cadeia real, pequena e reproduzível funciona: original,
  normalização, seleção temporal, regra, evidência e comparação com a referência, com as explicações
  geradas revisadas por humano.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** Execução real sobre amostra pequena, com `run_id`, manifestos e hashes
  lógicos preservados; resultado do avaliador de referência independente; explicações
  (`sustemporal explain`) revisadas contra consulta, versões, cobertura e limites; decisão humana G1
  em `experiments/decisions/`.
- **Depende de:** G1, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** `PA_INDICA` é referência de resultado, não de causa. Uma explicação não atribui o
  motivo do processamento oficial só porque uma regra falhou. O G1 é registro humano; nenhuma sessão
  o cria.
- **Ferramentas:** `sustemporal validate`, `sustemporal explain`
- **Pendências:** T08-i1, T08-i2, T07-i11

### AL-10 — Seleção temporal reprodutível e congelada

- **Conclusão possível:** A confirmar: o repositório bitemporal mantém separados o tempo de
  referência e o de observação, e a seleção de versões é reprodutível: um conjunto congelado não
  muda quando chegam versões novas depois do corte de observação.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** `SnapshotSet` com corte de observação fixado na configuração congelada;
  manifesto append-only (`aquisicao.jsonl`) com as observações; reexecução do mesmo `run_id` depois
  de novas observações, com os mesmos hashes lógicos.
- **Depende de:** G2, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** A retrospectiva não simula o conhecimento do gestor na data original: usa as versões
  que a pesquisa conseguiu observar até o corte. Um arquivo de março de 2020 obtido em 2026 não era
  conhecido pela pesquisa em março de 2020.
- **Ferramentas:** `sustemporal acquire`, `sustemporal validate`, `sustemporal freeze`
- **Pendências:** T06-4, T06-5, T07-i11, T02-5

### AL-11 — Republicações observadas na janela recente

- **Conclusão possível:** A confirmar: na observação semanal de uma janela móvel de seis
  competências recentes por doze meses ocorrem (ou não) revisões reais de arquivos já publicados,
  classificadas como inalteradas, revisão real ou correspondência ambígua, com o histórico de
  observações preservado.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** `manifests/aquisicao.jsonl` e `manifests/vigilancia.jsonl` de doze meses
  reais, com as tentativas sem mudança preservadas e o resumo da comparação.
- **Depende de:** DADOS_REAIS, ORIENTACAO
- **Estado:** PENDENTE
- **Limites:** Ausência de revisão observada não significa que nunca houve revisão. Cadência e
  janela são propostas operacionais, não garantia de capturar todas as revisões. A janela fica no
  recorte 201801–202512.
- **Ferramentas:** `sustemporal watch`
- **Pendências:** T13-1, T13-3, T13-4, T13-6

### AL-12 — P1: M_TEMP contra B_ATEND

- **Conclusão possível:** A confirmar: no teste (2024–2025, por competência de processamento), a
  política temporal por regra (`M_TEMP`) difere, em direção e magnitude a determinar, da política
  pela competência de atendimento (`B_ATEND`) quanto à cobertura de verificabilidade, à precisão dos
  alertas e aos falsos alertas em aprovações, com o mesmo catálogo de regras.
- **Natureza:** CONFIRMATORIA
- **Evidência exigida:** Relatório de `sustemporal evaluate --freeze FREEZE_ID` sobre o teste, com
  diferenças pareadas e intervalos de 95% (bootstrap por estabelecimento, 2.000 reamostragens,
  semente 2027, congelados antes do teste), resultados por competência, instrumento e
  estabelecimento, sensibilidade por blocos temporais, margens de relevância prática e correção de
  multiplicidade fixadas no protocolo; manifesto de congelamento com decisão G2.
- **Depende de:** G2, DADOS_REAIS, ORIENTACAO, ESBOCO
- **Estado:** PENDENTE
- **Limites:** Ausência de significância não é equivalência, e nenhum ganho percentual é presumido.
  Abstenções e inconclusivos ficam no denominador populacional; o domínio comum avaliável é definido
  sem olhar o resultado dos métodos. Biblioteca de regras, normalização e artefatos são idênticos
  nos comparadores; só a política muda. As métricas com `PA_INDICA` medem associação de resultado,
  não causa.
- **Ferramentas:** `sustemporal freeze`, `sustemporal evaluate`
- **Pendências:** T10-4, T10-6

### AL-13 — P1: M_TEMP contra B_PROC

- **Conclusão possível:** A confirmar: no teste, `M_TEMP` difere, em direção e magnitude a
  determinar, da política pela competência de processamento (`B_PROC`) quanto à cobertura de
  verificabilidade, à precisão dos alertas e aos falsos alertas em aprovações, com o mesmo catálogo
  de regras.
- **Natureza:** CONFIRMATORIA
- **Evidência exigida:** A mesma de AL-12 para a segunda comparação primária: diferenças pareadas,
  intervalos de 95%, estratos, sensibilidade, margens e correção de multiplicidade congelados antes
  do teste, com decisão G2.
- **Depende de:** G2, DADOS_REAIS, ORIENTACAO, ESBOCO
- **Estado:** PENDENTE
- **Limites:** Os mesmos de AL-12. As duas comparações primárias são as únicas; as demais são
  descritivas ou exploratórias.
- **Ferramentas:** `sustemporal freeze`, `sustemporal evaluate`
- **Pendências:** T10-4, T10-6

### AL-14 — P1: classificador histórico e controle trivial

- **Conclusão possível:** A confirmar: o classificador treinado só no histórico (`B_ML`, regressão
  logística regularizada) e o controle trivial (classe prevalente) servem de referência: o
  desempenho de `B_ML` é descrito ao lado das comparações primárias, sem rótulo, campos de erro,
  quantidades ou valores aprovados, nem dados futuros entre os atributos.
- **Natureza:** CONFIRMATORIA
- **Evidência exigida:** Lista positiva de atributos congelada e rastreada à origem (`FeatureSpec`
  no manifesto de congelamento); transformações, frequências, limiar e hiperparâmetros ajustados só
  em treino e calibração; predições do teste em `predicoes_baseline.v1`; ausência de vazamento por
  contrato e testes (`tests/integration/test_no_leakage.py`).
- **Depende de:** G2, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** Baseline fraco por erro de implementação não conta como evidência a favor do método.
  Republicações da mesma fonte são versões, não observações independentes, e as reapresentações não
  são vinculáveis: linhas repetidas pesam em dobro. O controle trivial é teste de sanidade, não o
  principal concorrente.
- **Ferramentas:** `src/sustemporal/evaluation/baselines.py`, `sustemporal freeze`,
  `sustemporal evaluate`
- **Pendências:** T10-1, T10-3, T10-4, T10-5, T10-6, T10-7

### AL-15 — P1: sensibilidade por ablação

- **Conclusão possível:** A confirmar: a decisão do motor é sensível (ou insensível) à versão da
  regra, à do CNES e à do SIGTAP quando cada uma é trocada isoladamente, mantendo o resto fixo.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** Execuções do motor em que só a versão da regra, só a do CNES ou só a do
  SIGTAP muda (`src/sustemporal/evaluation/ablation.py`), com a contagem de registros cuja avaliação
  mudou, sobre dados reais do desenvolvimento ou da calibração; interpretação de "congelar a versão
  da regra" confirmada com a orientação.
- **Depende de:** G1, DADOS_REAIS, ORIENTACAO
- **Estado:** PENDENTE
- **Limites:** Mede a sensibilidade do modelo; não identifica, de forma causal, a origem da decisão
  oficial.
- **Ferramentas:** `src/sustemporal/evaluation/ablation.py`
- **Pendências:** T08-i3

### AL-16 — P2: explicações verificáveis

- **Conclusão possível:** A confirmar: cada afirmação do texto de uma explicação aponta para um
  elemento verificável do pacote (evidência reexecutável, hash da fonte, cobertura, resultado vazio
  com integridade), com a representação PROV exportada.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** Explicações geradas sobre registros da cadeia real (G1), com reexecução das
  consultas de evidência por `query_id`, rastreabilidade de cada afirmação a um elemento do pacote e
  exportação PROV-N; revisão humana de que os modelos de texto descrevem corretamente consulta,
  versões, cobertura e limites.
- **Depende de:** G1, DADOS_REAIS, ESBOCO
- **Estado:** PENDENTE
- **Limites:** Resultado vazio só sustenta ausência com escopo, leiaute e cobertura suficientes; o
  PROV representa relações e não transforma resultado vazio em prova de inexistência no mundo real.
  Registro sem violação recebe conformidade ou abstenção, nunca "aprovado".
- **Ferramentas:** `sustemporal explain`
- **Pendências:** T08-i2, T08-i4, T08-i6, T08-i7

### AL-17 — P2: correção da família causal contra a referência humana

- **Conclusão possível:** A confirmar: as famílias de regra que o motor associa às rejeições
  observadas coincidem (igual, parcial ou divergente) com a referência humana cega, com causa
  indeterminada, evidência insuficiente e causa fora de escopo documentada contabilizadas à parte.
- **Natureza:** CONFIRMATORIA
- **Evidência exigida:** Amostra estratificada de cerca de 400 rejeições da partição de teste, com
  probabilidades de inclusão registradas (`sustemporal annotation-export --freeze FREEZE_ID`); dois
  avaliadores sem acesso às explicações; concordância bruta e κ antes da adjudicação; adjudicação
  cega; comparação com o motor só depois de fechar a referência.
- **Depende de:** G2, AVALIADORES, DADOS_REAIS, ESBOCO
- **Estado:** PENDENTE
- **Limites:** A referência é humana, baseada nas evidências disponíveis, e não um registro oficial
  de motivo. Não se afirma precisão causal populacional a partir de subconjunto selecionado pelo
  modelo. As horas de avaliação são estimativa de planejamento, não medição.
- **Ferramentas:** `sustemporal annotation-export`, `docs/method/annotation.md`
- **Pendências:** T12-i1, T12-i2, T12-i3, T12-i4, T12-i5, T12-i6

### AL-18 — P2: contrafactuais com limites explícitos

- **Conclusão possível:** A confirmar: para parte das rejeições explicadas existe alteração
  hipotética mínima no catálogo fechado de operações, classificada como hipótese passada,
  potencialmente executável sob condições, fora da governança ou indeterminada, com a revalidação
  das regras afetadas.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** `sustemporal counterfactual` sobre execuções reais (resultado, orçamento
  consumido e estado da minimalidade: `MINIMO_NO_CATALOGO`, `SOLUCAO_SEM_PROVA_DE_MINIMALIDADE` ou
  `BUSCA_INCONCLUSIVA`); governança de cada operação confirmada com especialista e documento oficial
  (IT CNES 1706; CNES, Dúvidas Frequentes, competências fechadas); custos recalibrados só no
  desenvolvimento.
- **Depende de:** G1, DADOS_REAIS, ESPECIALISTA, DOCUMENTO_OFICIAL, ESBOCO
- **Estado:** PENDENTE
- **Limites:** A alteração é hipotética até que alguém com autoridade a confirme fora do sistema;
  não assegura que o registro seria aprovado nem que uma alteração atual modificaria uma competência
  encerrada. Não identifica vínculo de profissional específico nem altera fato do atendimento. A
  minimalidade vale só no catálogo fechado e nos limites declarados.
- **Ferramentas:** `sustemporal counterfactual`, `catalog/operations.yaml`
- **Pendências:** T09-i1, T09-i2, T09-i3, T09-i4, T09-i5, T09-i6, T13-b1

### AL-19 — P3: parcela identificada de valor de tabela não aprovado

- **Conclusão possível:** A confirmar: em cada estrato de resultado oficial (rejeição e aprovação
  parcial, separados), a razão entre a soma de d(r) = valor apresentado menos valor aprovado nas
  ocorrências com incompatibilidade cadastral identificada sob governança municipal documentada e a
  soma de d(r) nas ocorrências contabilizáveis tem um valor r, informado só com denominador
  positivo, com registros inconclusivos, sem campos suficientes, de diferença negativa ou de rótulo
  contraditório em categorias próprias.
- **Natureza:** EXPLORATORIA
- **Evidência exigida:** `valores_p3.v1` real a partir de uma única seleção de versões, com
  contagens e valores por categoria; governança por família documentada; cada ocorrência contada uma
  vez, mesmo com várias violações; totais por família sobrepostos nunca somados.
- **Depende de:** G1, DADOS_REAIS, ESPECIALISTA, ESBOCO
- **Estado:** PENDENTE
- **Limites:** Valor de tabela não aprovado não equivale a dinheiro perdido: a razão é a parcela
  identificada no recorte contabilizável, não a de todas as perdas municipais, e não prova o motivo
  da decisão oficial. Reapresentações não vinculáveis seguem como ocorrências distintas. Os valores
  monetários do SIGTAP seguem A_CONFIRMAR (casas decimais implícitas).
- **Ferramentas:** `src/sustemporal/evaluation/values.py`
- **Pendências:** T13-b1, T13-b2, T04-2

### AL-20 — Escala do DRS XI para São Paulo

- **Conclusão possível:** A confirmar: o fluxo escala do DRS XI para o estado de São Paulo dentro de
  limites medidos de tempo, memória e armazenamento, com cache frio e quente e ao menos três
  repetições.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Relatório JSON do harness de desempenho
  (`src/sustemporal/evaluation/performance.py`) sobre artefatos reais, com ambiente, versões, cache
  e repetições registrados e preservado fora do Git; etapas do motor, da explicação, dos
  contrafactuais e das métricas montadas sobre dados reais.
- **Depende de:** DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** A medição vale para o ambiente declarado (máquina, memória, threads); os limites do
  plano (DuckDB com 8 GB e quatro threads) são perfil de ensaio, não promessa. Testes de desempenho
  com dados sintéticos não medem escala.
- **Ferramentas:** `src/sustemporal/evaluation/performance.py`
- **Pendências:** T13-b4, T13-b5, T03-6, T03-9, T03-19, T03-21, T07-i13, T07-i14, T09-i14

### AL-21 — Integridade do protocolo: exploração, congelamento e teste

- **Conclusão possível:** A confirmar: os resultados confirmatórios estão separados dos
  exploratórios: população, rótulos, políticas, catálogo, comparadores, atributos, métricas,
  sementes e artefatos foram congelados antes do teste, e toda alteração posterior à abertura do
  teste está registrada como nova versão, sem apagar a rodada anterior.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Manifesto de congelamento (`FreezeManifest`) com hashes; registro de cada
  execução do teste, inclusive resultados nulos; decisão G2 em `experiments/decisions/`; lista dos
  artefatos já inspecionados para decisões.
- **Depende de:** G2, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** Artefatos já inspecionados para decisões deixam de ser teste intocado. A janela
  recente de republicações é análise separada, não substituição de um teste com resultado
  desfavorável. Execução sintética nunca é confirmatória.
- **Ferramentas:** `sustemporal freeze`, `sustemporal evaluate`
- **Pendências:** T10-2, T11-4, T11-11, T11-18

### AL-22 — Reprodução por terceiros

- **Conclusão possível:** A confirmar: um terceiro reproduz, sem rede, as tabelas finais a partir
  dos originais locais do congelamento: hashes lógicos, contagens e métricas coincidem, e diferenças
  de bytes Parquet com hash lógico igual são distinguidas das diferenças de conteúdo.
- **Natureza:** DESCRITIVA
- **Evidência exigida:** Saída de `sustemporal reproduce --freeze FREEZE_ID --offline` com código 0
  e `resultado` `IGUAL` (ou `BYTES_DIFERENTES_HASH_LOGICO_IGUAL`) em `reproducao.json`, sobre o
  congelamento confirmatório real, mais o relato da reprodução por um terceiro em ambiente limpo
  (`docs/runbooks/reproducao.md`); instruções de reconstrução para os dados que não podem ser
  redistribuídos.
- **Depende de:** G2, DADOS_REAIS
- **Estado:** PENDENTE
- **Limites:** A reprodução sobre fixtures sintéticas é teste de software e não evidência empírica.
  O `reproduce` atual só reproduz a rodada exploratória e recusa a confirmatória, de modo que a
  evidência exigida ainda não pode ser produzida. Não se exige igualdade de bytes do Parquet: vale
  o hash lógico. Dados e documentos oficiais não são redistribuídos pelo repositório, só
  referências, hashes e trechos curtos.
- **Ferramentas:** `sustemporal reproduce`, `src/sustemporal/reporting/reproduce.py`,
  `docs/runbooks/reproducao.md`
- **Pendências:** T14-9, T14-13, T08-i6

## O que os testes de software verificam

Cada linha é uma propriedade da implementação, verificada contra a especificação com dados
sintéticos. Nenhuma delas é alegação da dissertação nem confirmação empírica do método.

| Propriedade da implementação | Testes | Por que não é evidência empírica |
|---|---|---|
| Estados e tempos não são intercambiáveis; configuração inválida bloqueia a execução | `tests/unit/test_contracts.py`, `tests/unit/test_config_heranca.py` | Contratos exercitados com valores sintéticos |
| Insumo faltante nunca vira violação; ausência só com cobertura suficiente | `tests/differential/test_rules.py`, `tests/metamorphic/test_rules.py`, `tests/unit/test_regras_motor.py` | Cenários construídos à mão e avaliador de referência sobre dados sintéticos |
| Mesmo arquivo recoletado é nova observação e não nova versão; A, B e A preservam três observações | `tests/integration/test_acquisition.py`, `tests/integration/test_republications.py` | FTP local em loopback e arquivos sintéticos |
| Seleção temporal explícita, sem mês vizinho, e conjunto congelado | `tests/unit/test_temporal_selector.py`, `tests/integration/test_temporal_motor.py` | Registros e versões sintéticos |
| Leitura DBC e DBF estrita; quarentena no lugar de conjunto vazio | `tests/unit/test_dbc_adaptador.py`, `tests/integration/test_sia_pa.py`, `tests/integration/test_reference_sources.py` | Fixtures geradas por código; pares comprimento e distância do DCL só aparecem em arquivos reais |
| Relatório do piloto: totais, denominadores e inclusão de aprovações | `tests/integration/test_pilot_report.py` | Conjuntos sintéticos pequenos |
| Classificador sem rótulo, campos de erro nem dados futuros como atributos | `tests/integration/test_no_leakage.py` | Contrato e dados sintéticos; não mede o desempenho do classificador |
| Explicação rastreável e PROV | `tests/integration/test_baselines.py`, `tests/unit/test_provenance.py` | Execuções sintéticas de ponta a ponta |
| Contrafactual com limites e minimalidade | `tests/unit/test_counterfactual.py` | Instâncias pequenas e catálogo de operações com governança DESCONHECIDA |
| Anotação cega sem resultados do motor | `tests/integration/test_annotation_blinding.py` | Pacote e formulários sintéticos |
| Valores da P3 sem dupla contagem | `tests/unit/test_values.py` | Tabelas pequenas calculadas à mão |
| Hash lógico determinístico | `tests/unit/test_hashing.py` | Relações sintéticas |
| Reprodução offline: hash lógico igual com bytes diferentes, 1 e 4 threads, split refeito com os artefatos inspecionados do congelamento, manifesto de aquisição até onde o `ingest` original o leu (coleta, republicação e ausência posteriores ao `ingest` ignoradas, seja qual for o instante), janela por artefatos, divergência de conteúdo, saída que só uma das execuções emitiu e item sem original (inclusive CNES ou SIGTAP ausente, entrada original da política ou posição do manifesto desconhecida) como falha, nenhuma conexão de rede | `tests/integration/test_reproduce_offline.py`, `tests/integration/test_reproduce_etapas.py`, `tests/unit/test_reproduce_manifesto.py`, `tests/unit/test_reproduce_comparacao.py`, `tests/unit/test_reproduce_conferencia.py`, `tests/unit/test_reproduce_insumos.py`, `tests/unit/test_reproduce_saidas.py`, `tests/unit/test_reproduce_rede.py`, `tests/unit/test_reproduce_recusas.py` | Fluxo sintético pequeno, sempre exploratório; o `reproduce` não reproduz o confirmatório |
| Portões G0, G1 e G2 só liberados por decisão humana | `tests/unit/test_gates.py` | Decisões de teste em diretório temporário |
| Licenças permissivas no runtime e nada de dados ou arquivos grandes no Git | `tests/unit/test_licencas.py`, `tests/unit/test_redistribuicao.py` | Auditoria do repositório, não do método |
