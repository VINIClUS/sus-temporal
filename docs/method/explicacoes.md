# Explicações, evidências e PROV (T08)

Pré-G0: tudo aqui roda só sobre execuções SINTETICAS. Nada descreve resultado empírico.

## 1. Entrada: só a execução exata
`explain(run: RunResult, row_id: str) -> ExplanationBundle` (`explanation/explain.py`) lê apenas o
que a execução declara:

- **Saídas** (`RunResult.saidas`): `avaliacoes.v1`, `selecao_versoes.v1`, `evidencias.v1`,
  `agregados_registro.v1` e `falhas.v1`. Cada uma precisa existir uma vez, ter
  `produzido_por == run.run_id` e conferir linhas e hash lógico com o `DatasetRef`
  (`rules.conteudo.verificar_conteudo`). Linha com `run_id` de outra execução recusa a explicação
  inteira (`saida_mistura_execucoes`).
- **Entradas** (`RunResult.entradas`): o `sia_pa.v1` de onde vem o registro e os conjuntos
  auxiliares que as evidências citam, também conferidos pelo hash.
- **Regras**: o catálogo (ou `regras=`, keyword-only) cujo `catalogo_sha256` bate com
  `RunResult.catalogo_regras_sha256` (catálogo inteiro ou só as regras avaliadas), com a versão
  de cada avaliação.

A CLI (`sustemporal explain --run RUN_ID --row ROW_ID`, `explanation/cli.py`) resolve
`<raiz_saidas>/runs/<run_id>/run_result.json` ou `<raiz_saidas>/validacao/<run_id>/run_result.json`;
nenhum, dois diferentes ou `run_id` gravado diferente dão saída 2. Nunca há diretório "latest".
A saída vai para `<raiz_saidas>/explicacoes/<run_id>/row_<sha256(row_id)[:32]>/`: `bundle.json`,
`prov.provn`, `prov.json` (os bytes cujo SHA-256 está em `prov_json_sha256`), `explicacao.txt` e
`reexecucoes.json`. Execução ou linha inexistente ou incoerente: saída 2 com mensagem
`chave=valor`. Evidência divergente: saída 5, só `falha.json` (`FalhaOperacional`, relógio injetado)
no diretório; arquivos de tentativas anteriores são removidos. Falha de leitura ou gravação: 5.
Execução `FALHOU`, ou falha operacional registrada para o registro ou para a execução inteira
(`falhas.v1` com `row_id` nulo), recusa a explicação: nunca "nenhuma violação verificada" sobre
avaliação incompleta.

## 2. Estrutura do bundle
| Campo | Conteúdo |
|---|---|
| `registro` | `ProductionRecord` lido do `sia_pa.v1` da execução (códigos como texto) |
| `avaliacoes` | `RuleEvaluation` do registro, por `rule_id`, com as seleções da regra |
| `selecoes` | Seleções distintas das avaliações (fonte, base, competência requerida, versões, motivo) |
| `evidencias` | Evidências citadas pelas avaliações, como gravadas pelo motor |
| `afirmacoes` | Texto por template; cada uma cita ids do bundle (regra, evidência ou versão) |
| `limitacoes` | Sempre `RESULTADO_NAO_E_CAUSA_OFICIAL` e `RETROSPECTIVO`; ver §5 |
| `prov_n`, `prov_json_sha256` | PROV-N e hash do PROV-JSON canônico |
| `causa_oficial_atribuida` | Sempre `False` (tipo `Falso` do contrato) |

`bundle_id = exp_` + 40 hex do hash canônico de execução, registro, hash do PROV, afirmações e
limitações. O PROV não contém caminhos de arquivo; contém os instantes da execução. A mesma
execução (mesmo `RunResult`) dá o mesmo bundle, byte a byte.

## 3. Evidência de ausência e reexecução
A evidência de ausência (`AUSENCIA_NA_FONTE`) guarda a consulta (`query_id`, `sql_sha256` do SQL de
avaliação da regra, `parametros` = chaves buscadas), o conjunto (`dataset_id`, `hash_logico`,
`artifact_ids` das versões selecionadas), a cobertura, a integridade e `n_resultados = 0`. Só
sustenta violação com cobertura `DISPONIVEL`, integridade `OK` e zero resultados; fonte incompleta
leva a `INCONCLUSIVO` no motor e o contrato do bundle recusa violação sustentada por evidência
`FONTE_INCOMPLETA` ou por ausência sem cobertura.

Antes de citar uma evidência, `explanation/evidence.py`:

1. confere que o `sql_sha256` é o do SQL que o motor executa para a regra (`montar_consulta`);
2. relê o conjunto citado (pelo `dataset_id`, entre as entradas da execução) e recalcula o hash
   lógico;
3. para `*.existencia`, reexecuta uma consulta existencial parametrizada própria (allowlist
   por `query_id`; filtro pelas versões citadas e pelos parâmetros) e compara o número de
   correspondências; evidências `aplicabilidade.*` têm só o hash conferido.

Qualquer divergência levanta `EvidenciaDivergente` (falha registrada); a evidência gravada nunca é
trocada pela recalculada. O SHA-256 da consulta de reexecução fica no PROV
(`sus:sql_reexecucao_sha256`) e o texto em `reexecucoes.json`.

## 4. Mapeamento PROV (`explanation/prov.py`, biblioteca `prov`)
| PROV | Elemento |
|---|---|
| `entity` | versões de conteúdo (`art_…`), conjuntos (`ds_…`, entradas e saídas), regras (`regra_<id>_<versão>`), registro, evidências (`ev_…`), avaliações |
| `activity` | aquisição de cada versão, transformação de cada conjunto de entrada, avaliação (a execução, com início e fim) |
| `agent` | o software (`prov:SoftwareAgent`, versão do pacote e commit) |
| `wasGeneratedBy` | versão ← aquisição; conjunto ← transformação; saídas, evidências e avaliações ← execução |
| `used` | transformação → versões; execução → conjuntos de entrada, regras e versões selecionadas |
| `wasDerivedFrom` | conjunto → versões; registro → `sia_pa.v1`; evidência → conjunto consultado; avaliação → registro, regra e evidências |
| `wasAssociatedWith` | cada atividade → software |

Avaliações e evidências declaram em `sus:derivada_de` as origens exigidas (registro, regra e cada
evidência; conjunto consultado). `exigir_relacoes` recusa documento sem qualquer das quatro
relações ou sem alguma dessas arestas `wasDerivedFrom`. Evidência de ausência ou de fonte incompleta carrega `sus:limitacao`: o
resultado vazio não prova inexistência no mundo real; a relação PROV só registra a consulta e o
conjunto consultado. Aquisição e transformação não têm instantes: a execução não os declara.

## 5. Templates (`explanation/templates/afirmacoes.yaml`)
Texto só por templates fixos (`string.Template`), nunca por LLM. Cada template declara as
referências exigidas (`regra`, `regras`, `evidencias`, `artefatos`); template desconhecido, campo
sem valor ou referência não resolvível levantam `TemplateInvalido`, e o contrato recusa afirmação
cujas referências não estão no bundle.

- Registro: `registro.alerta` (há `VIOLACAO`: alerta do modelo, não é causa oficial),
  `registro.sem_violacao` (não equivale a aprovação), `registro.abstencao`.
- Regra: `regra.violacao`, `regra.conforme`, `regra.nao_aplicavel`, `regra.inconclusiva`.
- Seleção temporal: `selecao.escolhida` (versões, base, competência e motivo) e
  `selecao.nao_escolhida` (o mês vizinho nunca substitui a competência requerida).

Limitações: `RESULTADO_NAO_E_CAUSA_OFICIAL` e `RETROSPECTIVO` sempre;
`RETRATO_MENSAL_NAO_DATA_EXATA` quando há seleção; `AUSENCIA_NAO_PROVA_INEXISTENCIA` quando há
evidência de ausência ou de fonte incompleta, ou motivo `ARQUIVO_AUSENTE`/`COBERTURA_INSUFICIENTE`;
`DADOS_SINTETICOS` quando `origem_dados` é `SINTETICO`.

## 6. Baselines e ablações
`B_ATEND` e `B_PROC` usam o mesmo motor, catálogo, normalização e conjuntos; só a política muda,
e com ela as seleções (`tests/integration/test_baselines.py`).

`evaluation/ablation.py` compara duas execuções que diferem num único fator:

- `VERSAO_REGRA`: a versão das regras muda; entradas e snapshot idênticos; só regras com versão
  alterada podem mudar de estado.
- `VERSAO_CNES` / `VERSAO_SIGTAP`: `trocar_versao_fonte` reescreve só as versões da fonte na
  `selecao_versoes.v1` (base, competência e estado fixos; observações antigas descartadas e motivo
  marcado); catálogo, política, configuração, código, ambiente, snapshot e demais entradas
  idênticos; seleções das outras fontes iguais em todos os campos. Versão substituta de outra
  competência é recusada pelo motor (competência divergente), nunca usada como mês vizinho.

Diferença em qualquer outro fator levanta `AblacaoNaoIsolada`. O relatório traz
`INTERPRETACAO_ABLACAO`: a ablação mede sensibilidade do modelo; não identifica causalmente a
origem da decisão oficial. A leitura de "congelar a versão da regra" é A_CONFIRMAR
(`docs/pendencias/T08.md`).

## 7. Limites
- Uma explicação não atribui causa oficial só porque uma regra falhou; `VIOLACAO` é alerta do
  modelo sobre as versões selecionadas.
- Registro sem violação recebe conformidade ("não equivale a aprovação") ou abstenção, nunca
  "aprovado".
- O G1 é decisão humana; este módulo só torna possível revisá-lo com cadeia real pequena.
