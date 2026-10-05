# Semântica formal de V(r, g, S, p) — catálogo de regras e motor (T07)

Estado: pré-G0, exploratório. Tudo o que este documento descreve foi exercitado só com dados
`SINTETICO`; nenhum teste sintético valida a hipótese empírica. As quatro famílias do primeiro
incremento estão `CANDIDATA_PRE_G0`; escolher as duas primeiras famílias observáveis é decisão do
G0 (humana). Referências normativas estão `PENDENTE` e leiautes vindos de fonte secundária ficam
`A_CONFIRMAR`.

Este documento é a especificação de duas implementações que não compartilham código: o motor SQL
(`rules/engine.py` + `rules/sql/`) e o avaliador de referência em Python puro
(`rules/reference.py`). Ambos dependem só dos contratos (`sustemporal.contracts`) e do catálogo.

## 1. Objetos

- `r` — registro SIA-PA canônico (`sia_pa.v1`), identificado por `row_id`. Linhas repetidas são
  registros distintos (multiplicidade preservada); nunca se infere paciente, reapresentação ou
  vínculo entre competências.
- `g` — regra (`RuleSpec`, catálogo `catalog/rules/**/*.yaml`), de uma `FamiliaRegra`.
- `p` — política temporal da execução (`PoliticaTemporal`): um método (`M_TEMP`, `B_ATEND`,
  `B_PROC`) e, por fonte auxiliar, um critério (`CriterioTemporal`: base `ATENDIMENTO` ou
  `PROCESSAMENTO` e deslocamento em meses). Uma execução avalia um único método e uma única
  política; `--policy documented|atendimento|processamento` escolhe `M_TEMP|B_ATEND|B_PROC` e só a
  política muda, o motor é o mesmo.
- `S` — seleção de versões: para cada `(r, g, f)` com `f` fonte auxiliar exigida por `g`, uma
  linha `selecao_versoes.v1` (`SelecaoVersao`) com estado, base, competência requerida e versões
  de conteúdo (`artifact_id`). A fonte do próprio registro (`SIA_PA`) não é selecionada.
- Insumos auxiliares: conjuntos canônicos (`DatasetRef`) por `schema_id`, a matriz de cobertura
  `cobertura.v1` e a integridade de cada versão de conteúdo (`EstadoIntegridade`).

## 2. Estados e tabela-verdade

`V(r, g, S, p) ∈ {CONFORME, VIOLACAO, INCONCLUSIVO, NAO_APLICAVEL}` é dado por
`decidir_estado(aplicabilidade, insumos_completos, incompatibilidade, motivos)` (contrato
`contracts/rules.py`), que é a especificação:

| aplicabilidade | insumos completos | motivos | incompatibilidade | estado |
|---|---|---|---|---|
| `NAO_APLICAVEL_DEMONSTRADA` | qualquer | qualquer | qualquer | `NAO_APLICAVEL` |
| `DESCONHECIDA` | qualquer | qualquer | qualquer | `INCONCLUSIVO` |
| `APLICAVEL` | não | qualquer | qualquer | `INCONCLUSIVO` |
| `APLICAVEL` | sim | não vazio | qualquer | `INCONCLUSIVO` |
| `APLICAVEL` | sim | vazio | nula | `INCONCLUSIVO` |
| `APLICAVEL` | sim | vazio | verdadeira | `VIOLACAO` |
| `APLICAVEL` | sim | vazio | falsa | `CONFORME` |

Sustentação exigida pelo contrato `RuleEvaluation`: `VIOLACAO` tem seleções não vazias, todas
`SELECIONADA`, e ao menos uma evidência; `CONFORME` tem seleções não vazias, todas `SELECIONADA`;
`INCONCLUSIVO` tem ao menos um motivo; `NAO_APLICAVEL` tem ao menos uma evidência.

`CONFORME` é satisfação daquela regra, nunca aprovação pelo SIA. Falha do programa (exceção,
arquivo canônico ilegível, violação de chave de um insumo, contrato inválido) é
`FalhaOperacional` em `falhas.v1`, nunca `INCONCLUSIVO`.

## 3. Procedimento de decisão

Notação: `I(r)` instrumento (`instrumento`), `P(r)` procedimento, `C(r)` CBO, `E(r)` CNES,
`A(r)`/`Q(r)` competências de atendimento/processamento; `M` é o conjunto de motivos, começando
vazio. Os passos são aplicados em ordem; "fim" encerra a avaliação de `(r, g)`.

Domínio dos códigos do registro: `P(r)` fora de `^[0-9]{10}$`, `C(r)` fora de `^[0-9A-Z]{6}$`,
`E(r)` fora de `^[0-9]{7}$` e competências fora de `^[0-9]{4}(0[1-9]|1[0-2])$` contam como nulos
em todos os passos (campo insuficiente, vigência, chave de cobertura). `I(r)` fora de
`^[CIPSAB]$` (domínio PA_DOCORIG) também conta como nulo.

### 3.1 Aplicabilidade
0. Integridade da versão SIA-PA do próprio registro (`artifact_id`) em qualquer estado
   `QUARENTENA_*`: aplicabilidade `DESCONHECIDA`,
   `M = {APLICABILIDADE_DESCONHECIDA, ARQUIVO_EM_QUARENTENA}`, `insumos_completos = falso`,
   incompatibilidade nula. Fim (registro de arquivo em quarentena não demonstra nada, nem a não
   aplicabilidade). Integridade não informada ou `NAO_VERIFICADO` não muda nada.
1. `I(r)` nulo (ou coluna ausente): aplicabilidade `DESCONHECIDA`,
   `M = {CAMPO_INSUFICIENTE, APLICABILIDADE_DESCONHECIDA}`, `insumos_completos = falso`,
   incompatibilidade nula. Fim.
2. `I(r) ∉ g.instrumentos`: `NAO_APLICAVEL_DEMONSTRADA`, `insumos_completos = verdadeiro`,
   incompatibilidade nula, `M = ∅`, evidência `APLICABILIDADE`. Fim.
3. `g.vigencia` definida: a competência do tipo `g.vigencia.referente_a` (`ATENDIMENTO → A(r)`,
   `PROCESSAMENTO → Q(r)`; outro tipo conta como nula) nula: `DESCONHECIDA`,
   `M = {CAMPO_INSUFICIENTE, APLICABILIDADE_DESCONHECIDA}`, `insumos_completos = falso`. Fim.
   Fora de `[inicio, fim]` (limites inclusivos, nulos abertos): `NAO_APLICAVEL_DEMONSTRADA` como no
   passo 2. Fim.
4. Caso contrário, `APLICAVEL`.

### 3.2 Insumos (só com `APLICAVEL`)
5. Política: `p.tipo = NAO_RESOLVIDA` acrescenta `POLITICA_NAO_RESOLVIDA`.
6. Campos: cada `c ∈ g.campos_necessarios` ausente do conjunto SIA-PA ou nulo em `r` acrescenta
   `CAMPO_INSUFICIENTE`. Domínio da família `INSTRUMENTO_REGISTRO`: `I(r)` fora do mapa
   instrumento→registro (§4.3) acrescenta `CAMPO_INSUFICIENTE`.
7. Seleção, para cada fonte auxiliar `f` de `g.requisitos_fonte` (toda fonte ≠ `SIA_PA`): sem
   linha `S(r, g, f)` → `VIGENCIA_NAO_RESOLVIDA`; estado `AUSENTE → ARQUIVO_AUSENTE`,
   `AMBIGUA → VERSAO_AMBIGUA`, `INCOMPLETA → COBERTURA_INSUFICIENTE`,
   `EM_QUARENTENA → ARQUIVO_EM_QUARENTENA`, `FORA_DO_CORTE → FORA_DO_CORTE`,
   `NAO_RESOLVIDA → VIGENCIA_NAO_RESOLVIDA`, `SELECIONADA` → nada. Nunca se procura outra
   competência (mês vizinho) quando a requerida falta.
8. Leiaute e escopo, para cada `f` com seleção `SELECIONADA` e requisito `(f, schema, campos)`:
   nenhum conjunto auxiliar com aquele `schema_id` → `ARQUIVO_AUSENTE`; conjunto sem alguma coluna
   de `campos ∪ {artifact_id}`, ou com coluna de tipo físico diferente do esquema canônico (código
   `TEXTO` gravado como número, por exemplo), ou com algum valor não nulo fora do domínio numa
   coluna de chave ou competência (`co_procedimento` `[0-9]{10}`; `co_ocupacao` e `cbo`
   `[0-9A-Z]{6}`; `cnes` `[0-9]{7}`; `co_registro` `[0-9]{2}`; `dt_competencia` e
   `competencia_arquivo` AAAAMM; em qualquer linha do conjunto) → `LEIAUTE_INCOMPATIVEL`; senão,
   alguma versão selecionada fora de `DatasetRef.artifact_ids` → `ARQUIVO_AUSENTE`; senão, alguma
   versão selecionada com integridade `QUARENTENA_*` → `ARQUIVO_EM_QUARENTENA` (vale também para
   correspondência encontrada: nunca `CONFORME` sobre arquivo em quarentena); senão, alguma linha
   do escopo com competência do conteúdo (`dt_competencia` ou `competencia_arquivo`) diferente da
   `competencia_requerida` da seleção, ou nula → `VIGENCIA_NAO_RESOLVIDA` (nunca o mês vizinho);
   senão, escopo vazio → `COBERTURA_INSUFICIENTE`. Integridade não informada ou `NAO_VERIFICADO` não impede
   `CONFORME` (a correspondência foi observada no conteúdo), mas impede ausência (passo 11).
   O escopo `Esc(r, g, f)` são as linhas do conjunto auxiliar cujo `artifact_id` pertence às
   versões selecionadas: conjunto vazio nunca vira ausência cadastral.
9. `M ≠ ∅`: `INCONCLUSIVO`, incompatibilidade nula. Fim.

### 3.3 Predicado (insumos completos)
10. O predicado da família (§4) é avaliado sobre `Esc(r, g, f)` por testes existenciais. Ele
    devolve: correspondência encontrada (incompatibilidade falsa, evidência
    `VINCULO_ENCONTRADO`); ausência; aplicabilidade desconhecida
    (`DESCONHECIDA`, `M = {APLICABILIDADE_DESCONHECIDA}`); ou motivo de inconclusão.
11. Ausência só sustenta `VIOLACAO` (`NOT EXISTS`) quando, além do escopo não vazio: a cobertura
    `cobertura.v1` na chave `(g.familia, I(r), Q(r), base de S(r, g, f))` é `DISPONIVEL`, toda
    versão selecionada tem integridade `OK` e toda versão selecionada tem ao menos uma linha no
    conjunto auxiliar. Então incompatibilidade verdadeira, evidência
    `AUSENCIA_NA_FONTE` (zero resultados, cobertura e integridade registradas). Senão
    `COBERTURA_INSUFICIENTE`, incompatibilidade nula. Chave de cobertura sem linha, `Q(r)` nulo ou
    matriz não fornecida contam como cobertura insuficiente (matriz com coluna de tipo físico diferente
    do esquema canônico, como competência numérica, não é utilizável e conta como não fornecida); integridade não informada conta como
    não `OK`.

`insumos_completos` é verdadeiro exatamente quando `M` não contém motivo diferente de
`APLICABILIDADE_DESCONHECIDA` (no passo 2 também verdadeiro). Motivos são gravados ordenados e sem
repetição.

## 4. Famílias do primeiro incremento (`CANDIDATA_PRE_G0`)

Cada família tem exatamente uma fonte auxiliar. Predicados sobre `Esc` (as colunas citadas são as
do esquema canônico). Em todas as famílias, logo depois do teste de correspondência e antes dos
demais ramos: se existe linha de `Esc` em que cada coluna da chave é igual ao valor do registro ou
nula, com ao menos uma nula, o resultado é `CAMPO_INSUFICIENTE` (o valor nulo poderia ser o que
casaria; nunca vira ausência). As colunas da chave estão listadas em cada família.

### 4.1 `PROCEDIMENTO_CBO` (SIGTAP `sigtap_proc_ocupacao.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento, cbo`. Chave: `co_procedimento = P(r)`, `co_ocupacao = C(r)`.
`∃ co_procedimento = P(r) ∧ co_ocupacao = C(r)` →
correspondência. Senão, `¬∃ co_procedimento = P(r)` → aplicabilidade desconhecida (procedimento sem
ocupação listada; aplicabilidade `A_CONFIRMAR`). Senão → ausência (§3.3, passo 11).

### 4.2 `ESTABELECIMENTO_CBO` (CNES PF `cnes_estab_cbo.v1`, unidade `ESTABELECIMENTO_CBO`)
Campos: `instrumento, cnes, cbo`. Chave: `cnes = E(r)`, `cbo = C(r)`, `n_vinculos > 0`.
`∃ cnes = E(r) ∧ cbo = C(r) ∧ n_vinculos > 0` → correspondência. Senão, chave com nulo →
`CAMPO_INSUFICIENTE` (inclui `n_vinculos` nulo).
Senão, `¬∃ cnes = E(r)` → `COBERTURA_INSUFICIENTE` (estabelecimento fora do escopo pesquisado).
Senão → ausência. A unidade é o par estabelecimento–CBO: registros com o mesmo par, competência e
seleção recebem o mesmo resultado e a mesma evidência; nunca se identifica nem se infere o vínculo
de um profissional específico, e presença num retrato mensal não data o início de um vínculo.

### 4.3 `INSTRUMENTO_REGISTRO` (SIGTAP `sigtap_proc_registro.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento`. Chave: `co_procedimento = P(r)`,
`co_registro = map(I(r))`. Mapa `PA_DOCORIG → CO_REGISTRO`: `C→01, I→02, P→06, S→07,
A→08, B→09` (`INFERIDA` dos rótulos; `A_CONFIRMAR`). `∃ co_procedimento = P(r) ∧ co_registro =
map(I(r))` → correspondência. Senão, `¬∃ co_procedimento = P(r)` → `COBERTURA_INSUFICIENTE` (o
procedimento sem registro listado é assunto da família de vigência). Senão → ausência.

### 4.4 `VIGENCIA_PROCEDIMENTO` (SIGTAP `sigtap_procedimento.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento`. Chave: `co_procedimento = P(r)`. `∃ co_procedimento = P(r)`
→ correspondência. Senão, chave com nulo → `CAMPO_INSUFICIENTE`. Senão → ausência.

### 4.5 Junções sem multiplicação
Toda verificação é existencial (`EXISTS`/`NOT EXISTS`) ou uma contagem agregada por registro; o
número de linhas de `avaliacoes.v1` é exatamente `|registros| × |regras avaliadas|`, qualquer que
seja a multiplicidade das relações auxiliares (relações N:N, linhas repetidas). Chaves dos insumos
(`selecao_versoes.v1`: `row_id, rule_id, fonte`; `cobertura.v1`) com repetição são falha
operacional, não uma escolha arbitrária.

## 5. Seleção de versões por fonte

`RuleSpec.criterios_temporais` registra o critério temporal documental por fonte; vazio significa
critério documental não resolvido (as quatro candidatas estão assim, com o motivo nos
`pressupostos`). Esse campo não escolhe versões: quem escolhe é a política da execução.

**Política da execução.** Cada execução tem uma única política, resolvida só em
`politica_da_execucao`, nesta ordem: `InsumosAvaliacao.politica` explícita; `RunConfig.politica_id`
carregada por `temporal.politicas.carregar_politica` (id inexistente ou inválido →
`ConfigInvalida`; método diferente do único método de validação em `RunConfig.metodos` →
recusa); a padrão do método da configuração (`B_ATEND`/`B_PROC` exploratórias; `M_TEMP` sem
documento → `NAO_RESOLVIDA`). `RuleSpec.politica_id` nunca escolhe a política. A mesma política
resolvida é repassada à seleção temporal e ao motor.

**Seleção em lote (T06).** `avaliar_com_registro` (`rules/lote.py`) recebe o `RegistroTemporal` e
roda `selecionar_lote` sobre a tabela `registros` já conferida (conteúdo, tipos, domínio, chave e
linhagem), com `uf` (`uf_da_execucao`: piloto ou vigilância) e `corte`
(`RunConfig.corte_observacao`) tirados da própria `RunConfig`;
`gravar_selecoes` grava `selecao_versoes.v1` em `out/selecoes/<sel_id>/` e devolve o `DatasetRef`
(hash lógico sobre as colunas do esquema). O `SnapshotSet` da execução é `unir_snapshots` das
seleções distintas do lote (uma por chave fonte, base, competência requerida). `sel_id` deriva da
política, do conjunto SIA-PA, do catálogo de regras, do registro temporal completo (observações,
versões, partes esperadas), da UF e do corte. A seleção gravada volta a `evaluate_rules` como
`InsumosAvaliacao.selecoes`: o motor confere conteúdo contra o `DatasetRef` e coerência com a
política exatamente como numa seleção fornecida. Entre métodos, com os mesmos insumos, só a seleção
(e o `SnapshotSet`) muda. Falha na etapa de seleção em lote interrompe antes da avaliação, com
exceção e sem saídas de avaliação; nunca vira `INCONCLUSIVO`. Versão ausente, fora do corte ou em
quarentena no registro temporal chega como seleção diferente de `SELECIONADA` e dá `INCONCLUSIVO`.

**Validação a partir do ingest.** `sustemporal validate --policy P --ingest DIR` (`rules/ingest.py`,
`rules/validate_ingest.py`) monta os insumos de uma pasta `execucao_*` do `sustemporal ingest` e do
registro temporal; todas as conferências (inclusive conteúdo, tipo físico e colunas obrigatórias
de todo conjunto) vêm antes de gravar qualquer arquivo:

- registro: `RegistroTemporal.de_manifesto` do manifesto de aquisição em `raiz_manifestos`, com as
  partes esperadas do catálogo; manifesto ausente, ilegível ou corrompido → saída 2;
- `datasets.jsonl`: cada `DatasetRef` conferido como no motor (linhas, hash lógico, tipo físico de
  todas as colunas do esquema, `DECIMAL` e `DATA` inclusive), pelas colunas obrigatórias e pela
  linhagem. Toda coluna não anulável do esquema canônico do conjunto (na produção, `row_id`,
  `artifact_id`, `indice_registro` e `deletado`; também nos auxiliares e na cobertura) existe no
  arquivo e não tem nulo, senão saída 2 (`entrada_fora_do_esquema`, com `coluna`, `dataset`,
  `linhas` e `motivo=ausente|nulo`): sem `deletado` a situação da linha seria desconhecida e ela
  passaria por ativa, e sem `artifact_id` não há linhagem a conferir. Toda linha tem `artifact_id`
  declarado pelo próprio conjunto, senão saída 2 (`linhagem_divergente`), o que impede trocar uma
  versão por outra na união; `origem_dados` igual em todos;
- produção: união de todos os `sia_pa.v1`, cada linha física preservada (sem deduplicar; uma linha
  repetida em duas partes conta duas vezes), `artifact_ids` = união ordenada, hash por
  `hash_logico_relacao`. Republicação concorrente → saída 2, nunca escolha automática: duas versões
  da pasta com a mesma chave lógica (fonte, UF, competência do arquivo, parte) ou versão da pasta
  que não é a visível no registro (mesmo que a pasta traga uma só). Pelo seletor do T06
  (`selecionar_versao`, critério de processamento) sobre o registro inteiro até o corte, a pasta só
  é aceita quando a seleção de cada competência do arquivo é `SELECIONADA` ou `INCOMPLETA` (esta
  vira marca de incompletude, abaixo); qualquer outro estado (`AMBIGUA`, `EM_QUARENTENA`,
  `FORA_DO_CORTE`, `AUSENTE`, `NAO_RESOLVIDA`) → saída 2 (`producao_com_selecao_nao_aceita`, com
  competência, estado e motivo do seletor), antes de gravar: produção em quarentena nunca é avaliada
  como produção comum. A pasta traz todas as versões que o seletor escolhe para cada competência do
  arquivo: parte selecionada ausente da pasta → saída 2 (`producao_com_partes_ausentes`), nunca
  avaliação só das partes presentes; a marca `sia_pa_incompleto` da ingestão não isenta a parte
  ausente.
  Artefato fora do registro, de UF ou competência do arquivo fora do piloto, ou, com
  `corte_observacao`, sem observação `OBTIDO` até o corte → saída 2; `row_id` repetido → falha
  operacional (saída 5);
- população e território: território carregado por `ingest.territorio.carregar_territorio`
  (contrato, UF e dígito verificador) e `municipios_ibge6`. Produção sem
  `municipio_estabelecimento` ou `competencia_processamento` → saída 2 (`territorio_sem_coluna`).
  Saem da população, nunca avaliadas, e são contadas em `out/<run_id>/recorte_territorial.json`,
  cada linha num único motivo, na precedência do T10 (`evaluation/split.py`):
  `registro_deletado` (deletado no DBF) > `sem_competencia_processamento` >
  `fora_das_competencias_do_piloto` > `territorio_indeterminado` (município nulo; no T10,
  `sem_municipio_estabelecimento`) > `fora_do_territorio`. Recorte que deixa a população vazia →
  saída 2 (`populacao_vazia_apos_recorte`), nunca execução `CONCLUIDA` vazia. O hash do conteúdo
  inteiro de `recorte_territorial.json` (municípios, contagens, cobertura da ingestão) entra no
  `run_id` (`InsumosAvaliacao.identidade_adicional`), então outro território ou outras contagens
  dão outra execução mesmo quando a produção filtrada é igual;
- auxiliares: por esquema exigido pelas regras, uma relação derivada com as linhas de todos os
  artefatos daquele esquema, cada linha com o seu `artifact_id`; nada é deduplicado entre artefatos,
  porque a seleção decide quais versões valem e a avaliação junta por `artifact_id`;
- cobertura: no máximo um `cobertura.v1` (mais de um → saída 2); nenhum → matriz não fornecida.
  Com um, a cobertura avaliada é recalculada por `ingest.coverage.build_coverage` sobre a
  produção territorial e os conjuntos auxiliares originais da ingestão (com `reconciliacao`, então
  perda de linhas continua tornando a célula insuficiente), nas competências de processamento do
  piloto, preservando as marcas de incompletude da ingestão (motivos
  `sia_pa_incompleto competencia=AAAAMM motivo=…`, lidos por `incompletude_da_cobertura` na passada
  de conferência, antes de qualquer gravação; marca fora do formato → saída 2): nunca
  sai `DISPONIVEL` onde a ingestão marcou arquivo incompleto. Assim um registro de fora do
  território não torna insuficiente uma célula do território. O seletor do T06 também marca, mesmo
  quando a cobertura da ingestão não tem a marca (catálogo alterado depois do ingest): a competência
  do arquivo cuja seleção da produção é `INCOMPLETA` (parte esperada ausente, parte não declarada ou
  partes sem declaração no catálogo) entra com `motivo=selecao_incompleta` e o motivo do seletor, e
  as competências de processamento que as linhas dos artefatos dela trazem, como na ingestão
  (`propagar_incompletude`), entram com `motivo=incompleto_via_arquivo competencia_arquivo=AAAAMM`
  (`rules/ingest_selecao.py::marcas_de_incompletude`, depois do recorte); a marca da ingestão
  prevalece quando existe. A competência fica `INSUFICIENTE`, e a linha que dependeria de uma parte
  ausente sai `INCONCLUSIVO`, nunca `VIOLACAO`. A cobertura recalculada entra na
  avaliação e no `run_id`; a da ingestão fica registrada em `recorte_territorial.json`
  (`cobertura_da_ingestao`);
- integridade por versão, derivada do registro: a da versão, piorada pelas observações dela —
  integridade observada `QUARENTENA_*` prevalece; tentativa com o artefato que não terminou em
  `OBTIDO` (falha de coleta com bytes) deixa a versão `NAO_VERIFICADO`, nunca `OK`. Com
  `corte_observacao`, só contam as observações até o corte e só entram versões observadas até ele.

Toda execução do `validate` (`--entrada` ou `--ingest`) grava `out/<run_id>/entrada_validacao.json`
(`rules/entrada.py::EntradaValidacao`): conjunto SIA-PA, `SnapshotSet`, auxiliares, seleção,
cobertura, integridade, a política resolvida e a `identidade_adicional` (hash do território), com os
mesmos `DatasetRef` de `RunResult.entradas`; reexecutar com `--entrada` sobre esse arquivo reproduz o
`run_id`.
No caminho direto (`--entrada`) não há onde registrar exclusões: produção com `deletado`
verdadeiro é recusada (`producao_com_registros_deletados`, saída 2); erro de leitura do Parquet
nessa pré-checagem segue para o motor e vira falha operacional (saída 5, `falhas.v1`). O motor grava esses anexos atomicamente (`evaluate_rules(..., anexos=)`) antes de qualquer saída, então
`run_result.json` nunca existe sem eles. Uma entrada com `politica` reavalia com essa política.

A política é a de `politica_da_execucao` com o método de `--policy`; a avaliação é
`avaliar_com_registro`, e as saídas ficam em `<raiz_saidas>/runs/<run_id>/` (relações derivadas em
`runs/entradas/`, seleções em `runs/selecoes/`).

Sem registro temporal, o motor aceita uma tabela `selecao_versoes.v1` pronta ou deriva a seleção
do `SnapshotSet` por correspondência exata: para `(r, g, f)`, com critério `(base, deslocamento)`
de `p` para `f`, competência requerida `= base(r) + deslocamento` (base `ATENDIMENTO → A(r)`,
`PROCESSAMENTO → Q(r)`); a seleção é a única `SelecaoVersao` do `SnapshotSet` com a mesma fonte,
base e competência; nenhuma → `AUSENTE`; competência base nula ou política sem critério para `f` →
`NAO_RESOLVIDA`; duas entradas para a mesma chave no `SnapshotSet` → falha operacional.

Em `M_TEMP`, o critério da política para a fonte `f` só vale quando coincide (base e deslocamento)
com o critério documental da regra para `f` (`RuleSpec.criterios_temporais`); senão, a regra não
tem critério para `f` e a seleção é `NAO_RESOLVIDA` (abstenção). Assim, uma política
`DOCUMENTADA` não impõe critério a regras cujo critério documental não está resolvido. A regra
vive numa única função, `temporal.selector.criterio_da_regra(politica, regra, fonte)`, usada pela
seleção (por registro e em lote) e pela conferência do motor (`criar_regras_fontes`).

Uma tabela de seleção fornecida precisa ser coerente com a política da execução: toda linha com
estado diferente de `NAO_RESOLVIDA` tem `base` igual à base do critério de `p` para a fonte e
`competencia_requerida = base(r) + deslocamento`; sem critério para a fonte (inclusive política
`NAO_RESOLVIDA`) ou com competência base nula, só `NAO_RESOLVIDA` é aceita. Qualquer linha
incoerente é falha operacional (etapa `conferir_selecao`, execução `FALHOU`), nunca avaliação com
versões de outra política registrada como esta. Nunca há
fallback para o mês vizinho nem substituição do histórico pelo cadastro corrente.

## 6. Agregação por registro

`AgregadoRegistro.agregar` guarda separadamente violações, conformes, inconclusivas e não
aplicáveis. `ALERTA` exige uma violação e vale mesmo com outra regra inconclusiva;
`SEM_VIOLACAO_VERIFICADA` exige ao menos uma conforme e nenhuma violação ou inconclusiva; os demais
casos (inconclusiva sem violação, só não aplicáveis, nenhuma regra) são `ABSTENCAO`. Não existe
estado "aprovado". Registro afetado por falha operacional não recebe agregado: a falta de uma regra
nunca é lida como conformidade.

## 7. Saídas, identidade e determinismo

Cada evidência carrega consulta (`query_id`), SHA-256 do SQL efetivamente executado (modelo com
os marcadores resolvidos), parâmetros em JSON, conjunto
consultado (`dataset_id`, hash lógico, versões), cobertura, integridade (`OK` só se todas as versões
selecionadas forem `OK`; senão o pior estado, `NAO_VERIFICADO` quando não informado), número de
resultados e chaves encontradas. O `evidence_id` deriva desse conteúdo, então registros com os
mesmos parâmetros (por exemplo, o mesmo par estabelecimento–CBO) citam a mesma evidência.
`NAO_APLICAVEL` cita uma evidência `APLICABILIDADE` sobre o próprio registro (instrumento fora da
lista da regra ou competência fora da vigência).

Toda tabela de entrada passa por um único verificador de tipos físicos contra o esquema canônico
antes de qualquer projeção ou conversão. Divergência no conjunto SIA-PA ou na seleção fornecida é
falha de carga (`FalhaOperacional`, execução `FALHOU`); no conjunto auxiliar é
`LEIAUTE_INCOMPATIVEL`; na cobertura, a matriz não é utilizável. Integridade com estado fora de
`EstadoIntegridade` também é falha de carga. Chave nula ou repetida no conjunto SIA-PA (`row_id`)
ou na seleção (`row_id, rule_id, fonte`) é falha de carga; a matriz de cobertura com coluna
ausente, tipo divergente ou chave nula não é utilizável (conta como não fornecida). Linhas
auxiliares com chave nula seguem a regra de `CAMPO_INSUFICIENTE` do §4. A linhagem de cada
registro também é conferida na carga: `artifact_id` não nulo, igual ao artefato do `row_id`
(formato `art_…[/membro]#n` do `RowLocator`) e pertencente a `DatasetRef.artifact_ids`; senão,
falha de carga (`linhagem_incoerente` ou `linhagem_fora_do_dataset`). Os `schema_id` da seleção
(`selecao_versoes.v1`) e da cobertura (`cobertura.v1`) também são exigidos. Na CLI, erro semântico
anterior à execução (esquema do conjunto, origem de dados misturada) sai como configuração
inválida, sem traceback.

Antes de avaliar, todo `DatasetRef` lido (SIA-PA, auxiliares, seleção, cobertura) tem o conteúdo
conferido: contagem de linhas e hash lógico `lh1` das colunas do esquema canônico presentes no
arquivo, na ordem do esquema (a mesma convenção das saídas). Divergência é falha operacional
`conteudo_divergente`; arquivo canônico ausente, truncado ou ilegível também é falha operacional
(a quarentena de arquivo original acontece na ingestão). Nos dois casos, o auxiliar vira falha da
regra que depende dele (as demais seguem, execução `PARCIAL`) e o SIA-PA, a seleção ou a cobertura
viram falha em `carregar_insumos` (execução `FALHOU`); nunca `VIOLACAO` nem `INCONCLUSIVO`. A
evidência cita o hash do conteúdo conferido. Códigos são sempre texto e nunca são convertidos de
número.

No modo confirmatório, antes de qualquer avaliação, o motor exige dados `REAL` e a decisão humana
G2 do congelamento (`exigir_confirmatorio_valido`), além de política resolvida; a recusa é
`PortaoRecusado`, nunca `INCONCLUSIVO`.

`out/<run_id>/` recebe `avaliacoes.parquet`, `evidencias.parquet`, `agregados_registro.parquet`,
`selecao_versoes.parquet` e `falhas.parquet` (esquemas em `catalog/schemas/`) e cada um vira um
`DatasetRef` com hash lógico `lh1`. O `run_id` deriva do conteúdo (conjunto, seleção, regras,
política e configuração), então a reexecução com os mesmos insumos produz os mesmos hashes,
independentemente da ordem das linhas e do número de threads do DuckDB. SQL é sempre
parametrizado; identificadores só vêm da allowlist derivada dos esquemas canônicos.

## 8. Limites declarados
- Testes sintéticos verificam a implementação contra esta especificação, não a hipótese empírica.
- Referências normativas das quatro famílias estão `PENDENTE`; o mapa instrumento→registro é
  `INFERIDA`; leiautes SIGTAP/CNES são `SECUNDARIA`/`A_CONFIRMAR`.
- Política `DOCUMENTADA` depende de documento ainda pendente; sem ela, `M_TEMP` avalia com política
  `NAO_RESOLVIDA` e se abstém.
