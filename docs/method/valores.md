# P3: parcela identificada de valor de tabela não aprovado (T13b)

Estado: software pronto e testado só com dados `SINTETICO`. Nada aqui é resultado empírico.

## O que a razão é e o que não é
A razão é a **parcela identificada no recorte contabilizável**: dentro de um estrato de resultado
oficial, a fração da diferença entre valor apresentado e valor aprovado que recai sobre
ocorrências com ao menos uma incompatibilidade cadastral identificada pelo motor **e** governança
municipal documentada. Ela **não** é:
- perda financeira: valor de tabela não aprovado não equivale a dinheiro perdido;
- parcela de todas as perdas municipais: fica restrita ao recorte, às famílias implementadas e às
  ocorrências com valores conhecidos;
- prova de causa da decisão oficial: a incompatibilidade é associação verificada pelo motor, não
  log oficial de motivo;
- deduplicação de atendimentos: reapresentações não vinculáveis continuam ocorrências distintas.

Ausência de revisão observada (T13a) não significa que nunca houve revisão.

## Definição (`summarize_values(run, labels, out)`)
- **Uma única seleção de versões**: a população é o conjunto de registros avaliados por um único
  `RunResult` concluído. Avaliações com mais de uma `(politica_id, metodo)`, ou com política
  diferente da do run, são recusadas (`selecao_de_versoes_multipla`).
- **Ocorrência**: cada `row_id` de `agregados_registro.v1` do run. Não há deduplicação nem vínculo
  entre competências.
- `d(r) = valor_apresentado(r) − valor_aprovado(r)`, em `Decimal` (DECIMAL no DuckDB, nunca
  float), com valores de `sia_pa_rotulos.v1`.
- **Estratos**: o rótulo oficial normalizado (`NAO_APROVADO`, `APROVADO_PARCIAL` e, se presentes,
  `APROVADO_TOTAL` e `DESCONHECIDO`). Rejeição e aprovação parcial nunca se misturam.
- **Categorias** (cada ocorrência cai em exatamente uma, nesta precedência):

| Categoria | Condição | No denominador? |
|---|---|---|
| `CAMPOS_INSUFICIENTES` | valor apresentado ou aprovado desconhecido | não |
| `DIFERENCA_NEGATIVA` | `d(r) < 0` (valor mantido negativo, nunca truncado) | não |
| `IDENTIFICADA_GOVERNANCA_MUNICIPAL` | VIOLACAO em ao menos uma família com governança `MUNICIPAL_DOCUMENTADA` | sim (numerador) |
| `INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA` | VIOLACAO só em famílias sem governança municipal documentada | sim |
| `INCONCLUSIVO` | sem violação e resultado `ABSTENCAO` | sim |
| `SEM_VIOLACAO_VERIFICADA` | demais | sim |

- **Denominador**: soma de `d(r)` nas quatro categorias elegíveis (valores conhecidos e `d ≥ 0`),
  como define o plano; rótulo contraditório não tira a ocorrência do denominador.
- **Numerador**: `IDENTIFICADA_GOVERNANCA_MUNICIPAL`. Cada ocorrência entra uma vez, mesmo com
  várias violações.
- **Razão** (`RAZAO`, só em `NAO_APROVADO` e `APROVADO_PARCIAL`): numerador ÷ denominador com 12
  casas (meio-par), apenas com denominador positivo; senão nula.
- **Rótulo contraditório** (`ROTULO_CONTRADITORIO`, `aditiva = false`): ocorrências com
  `contradicoes` não vazio, em qualquer categoria, reportadas à parte com contagem e valor; o
  recorte se sobrepõe às categorias e não se soma a elas.
- **Totais por família** (`FAMILIA_<F>`, `aditiva = false`): ocorrências elegíveis com VIOLACAO na
  família F. Uma ocorrência com duas famílias aparece nas duas; esses totais não se somam.
- Toda categoria sai em todo estrato, mesmo com zero ocorrências; nenhuma é omitida.

## Governança municipal
A governança vem do catálogo de operações do T09 (`Governanca`: `MUNICIPAL_DOCUMENTADA`,
`FORA_DA_GOVERNANCA_MUNICIPAL`, `DESCONHECIDA`), passada como `governanca_por_familia`.
- Sem o mapa (situação atual: T09 fora do main e operações com governança `DESCONHECIDA`), o
  numerador e a razão ficam **indeterminados** (nulos, não zero); as incompatibilidades ficam em
  `INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA`, com contagem e valor.
- Com o mapa, só famílias `MUNICIPAL_DOCUMENTADA` entram no numerador; `DESCONHECIDA` e
  `FORA_DA_GOVERNANCA_MUNICIPAL` não entram (numerador zero é então um valor determinado).
- CID, idade e sexo são fatos do atendimento, fora do catálogo de operações (plano §6), e não
  podem ser marcados como governança municipal.

## Coerência das entradas
- Rótulos precisam cobrir os registros de entrada do run (`artifact_ids` dos `sia_pa.v1` em
  `RunResult.entradas`); rótulos de outro dataset são recusados. Sem entradas declaradas, a
  conferência não é possível e fica registrada em log.
- `agregados_registro.v1` incoerente (ALERTA sem violação ou violação sem ALERTA) é falha
  operacional.
- `politica_id` e `metodo` das avaliações precisam coincidir com os do run.
- A família de cada regra vem do catálogo usado no run: `catalogo_regras_sha256` do run precisa
  coincidir com o hash do catálogo (completo ou do subconjunto avaliado) e cada `versao` avaliada
  com a do catálogo; run sem hash de catálogo é recusado.
- Somas usam precisão decimal de 80 dígitos; valor com mais de 32 dígitos inteiros ou mais de 6
  casas decimais é recusado, nunca arredondado.

## Saída `valores_p3.v1`
Uma linha por estrato e categoria: `run_id`, `estrato`, `categoria`, `aditiva`, `ocorrencias`,
`valor_apresentado`, `valor_aprovado`, `diferenca` (somas dos valores conhecidos; nulas sem
nenhum valor conhecido), `razao`. Hash lógico sobre as nove colunas, na ordem; `linhas` é a
contagem real. O esquema está declarado em `evaluation/values.py` até ser promovido a
`catalog/schemas/` pelo orquestrador.

## Falhas
Parquet ilegível ou divergente do `DatasetRef`, coluna exigida ausente, rótulo ausente para
registro avaliado ou ocorrência repetida no run são `FalhaOperacionalErro` (nunca zero, nunca
categoria). Execução não concluída é recusada.

## Desempenho (`evaluation/performance.py`)
`medir(Etapa, repeticoes=, cache=)`:
- cronometra cada repetição sem `tracemalloc` (relógio injetável);
- mede o pico de memória Python numa rodada extra com `tracemalloc` (não inclui buffers nativos do
  DuckDB); se quem chama já usa `tracemalloc`, a memória fica nula com motivo
  `memoria_nao_medida_tracemalloc_ativo`;
- registra o RSS máximo do **processo inteiro** (`ru_maxrss`, convertido para bytes), que não
  isola etapas do mesmo processo: para isolar, rodar cada etapa em processo próprio;
- registra o armazenamento acrescentado ao diretório de saída durante a medição e o total;
- registra o cache por repetição: com `FRIO`, só a primeira repetição é fria.

`gravar_relatorio` grava ambiente, instante UTC, origem dos dados e as medições. Etapas sem
implementação no main (`contrafactuais` do T09, `metricas` do T11) saem `NAO_MEDIDO motivo=…`. O
teste `tests/perf/test_desempenho_s8.py` (marcador `perf`) exercita o harness em cenário sintético
pequeno; a escala DRS XI e SP roda na máquina do pesquisador, com etapas montadas sobre os
artefatos reais (aquisição, ingestão, rótulos, seleção, motor, explicação, anotação e valores),
cache frio e quente declarados e ao menos três repetições.
