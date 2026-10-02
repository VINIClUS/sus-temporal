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

### 3.1 Aplicabilidade
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
   de `campos ∪ {artifact_id}` → `LEIAUTE_INCOMPATIVEL`; senão, alguma versão selecionada fora de
   `DatasetRef.artifact_ids` → `ARQUIVO_AUSENTE`; senão, escopo vazio → `COBERTURA_INSUFICIENTE`.
   O escopo `Esc(r, g, f)` são as linhas do conjunto auxiliar cujo `artifact_id` pertence às
   versões selecionadas: conjunto vazio nunca vira ausência cadastral.
9. `M ≠ ∅`: `INCONCLUSIVO`, incompatibilidade nula. Fim.

### 3.3 Predicado (insumos completos)
10. O predicado da família (§4) é avaliado sobre `Esc(r, g, f)` por testes existenciais. Ele
    devolve: correspondência encontrada (incompatibilidade falsa, evidência
    `VINCULO_ENCONTRADO`); ausência; aplicabilidade desconhecida
    (`DESCONHECIDA`, `M = {APLICABILIDADE_DESCONHECIDA}`); ou motivo de inconclusão.
11. Ausência só sustenta `VIOLACAO` (`NOT EXISTS`) quando, além do escopo não vazio: a cobertura
    `cobertura.v1` na chave `(g.familia, I(r), Q(r), base de S(r, g, f))` é `DISPONIVEL` e toda
    versão selecionada tem integridade `OK`. Então incompatibilidade verdadeira, evidência
    `AUSENCIA_NA_FONTE` (zero resultados, cobertura e integridade registradas). Senão
    `COBERTURA_INSUFICIENTE`, incompatibilidade nula. Chave de cobertura sem linha, `Q(r)` nulo ou
    matriz não fornecida contam como cobertura insuficiente; integridade não informada conta como
    não `OK`.

`insumos_completos` é verdadeiro exatamente quando `M` não contém motivo diferente de
`APLICABILIDADE_DESCONHECIDA` (no passo 2 também verdadeiro). Motivos são gravados ordenados e sem
repetição.

## 4. Famílias do primeiro incremento (`CANDIDATA_PRE_G0`)

Cada família tem exatamente uma fonte auxiliar. Predicados sobre `Esc` (as colunas citadas são as
do esquema canônico):

### 4.1 `PROCEDIMENTO_CBO` (SIGTAP `sigtap_proc_ocupacao.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento, cbo`. `∃ co_procedimento = P(r) ∧ co_ocupacao = C(r)` →
correspondência. Senão, `¬∃ co_procedimento = P(r)` → aplicabilidade desconhecida (procedimento sem
ocupação listada; aplicabilidade `A_CONFIRMAR`). Senão → ausência (§3.3, passo 11).

### 4.2 `ESTABELECIMENTO_CBO` (CNES PF `cnes_estab_cbo.v1`, unidade `ESTABELECIMENTO_CBO`)
Campos: `instrumento, cnes, cbo`. `∃ cnes = E(r) ∧ cbo = C(r) ∧ n_vinculos > 0` →
correspondência. Senão, `∃ cnes = E(r) ∧ cbo = C(r) ∧ n_vinculos nulo` → `CAMPO_INSUFICIENTE`.
Senão, `¬∃ cnes = E(r)` → `COBERTURA_INSUFICIENTE` (estabelecimento fora do escopo pesquisado).
Senão → ausência. A unidade é o par estabelecimento–CBO: registros com o mesmo par, competência e
seleção recebem o mesmo resultado e a mesma evidência; nunca se identifica nem se infere o vínculo
de um profissional específico, e presença num retrato mensal não data o início de um vínculo.

### 4.3 `INSTRUMENTO_REGISTRO` (SIGTAP `sigtap_proc_registro.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento`. Mapa `PA_DOCORIG → CO_REGISTRO`: `C→01, I→02, P→06, S→07,
A→08, B→09` (`INFERIDA` dos rótulos; `A_CONFIRMAR`). `∃ co_procedimento = P(r) ∧ co_registro =
map(I(r))` → correspondência. Senão, `¬∃ co_procedimento = P(r)` → `COBERTURA_INSUFICIENTE` (o
procedimento sem registro listado é assunto da família de vigência). Senão → ausência.

### 4.4 `VIGENCIA_PROCEDIMENTO` (SIGTAP `sigtap_procedimento.v1`, unidade `OCORRENCIA`)
Campos: `instrumento, procedimento`. `∃ co_procedimento = P(r)` → correspondência. Senão →
ausência.

### 4.5 Junções sem multiplicação
Toda verificação é existencial (`EXISTS`/`NOT EXISTS`) ou uma contagem agregada por registro; o
número de linhas de `avaliacoes.v1` é exatamente `|registros| × |regras avaliadas|`, qualquer que
seja a multiplicidade das relações auxiliares (relações N:N, linhas repetidas). Chaves dos insumos
(`selecao_versoes.v1`: `row_id, rule_id, fonte`; `cobertura.v1`) com repetição são falha
operacional, não uma escolha arbitrária.

## 5. Seleção de versões por fonte

A seleção por registro é produzida pela seleção temporal (T06, sessão S1). Enquanto a seleção em
lote não está disponível, o motor aceita uma tabela `selecao_versoes.v1` pronta ou deriva a seleção
do `SnapshotSet` por correspondência exata: para `(r, g, f)`, com critério `(base, deslocamento)`
de `p` para `f`, competência requerida `= base(r) + deslocamento` (base `ATENDIMENTO → A(r)`,
`PROCESSAMENTO → Q(r)`); a seleção é a única `SelecaoVersao` do `SnapshotSet` com a mesma fonte,
base e competência; nenhuma → `AUSENTE`; competência base nula ou política sem critério para `f` →
`NAO_RESOLVIDA`; duas entradas para a mesma chave no `SnapshotSet` → falha operacional. Nunca há
fallback para o mês vizinho nem substituição do histórico pelo cadastro corrente.

## 6. Agregação por registro

`AgregadoRegistro.agregar` guarda separadamente violações, conformes, inconclusivas e não
aplicáveis. `ALERTA` exige uma violação e vale mesmo com outra regra inconclusiva;
`SEM_VIOLACAO_VERIFICADA` exige ao menos uma conforme e nenhuma violação ou inconclusiva; os demais
casos (inconclusiva sem violação, só não aplicáveis, nenhuma regra) são `ABSTENCAO`. Não existe
estado "aprovado". Registro afetado por falha operacional não recebe agregado: a falta de uma regra
nunca é lida como conformidade.

## 7. Saídas, identidade e determinismo

`out/` recebe `avaliacoes.parquet`, `evidencias.parquet`, `agregados_registro.parquet`,
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
