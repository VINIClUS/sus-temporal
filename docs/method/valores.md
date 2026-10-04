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
| `ROTULO_CONTRADITORIO` | `contradicoes` não vazio no rótulo | não |
| `CAMPOS_INSUFICIENTES` | valor apresentado ou aprovado desconhecido | não |
| `DIFERENCA_NEGATIVA` | `d(r) < 0` (valor mantido negativo, nunca truncado) | não |
| `IDENTIFICADA_GOVERNANCA_MUNICIPAL` | VIOLACAO em ao menos uma família com governança `MUNICIPAL_DOCUMENTADA` | sim (numerador) |
| `INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA` | VIOLACAO só em famílias sem governança municipal documentada | sim |
| `INCONCLUSIVO` | sem violação e resultado `ABSTENCAO` | sim |
| `SEM_VIOLACAO_VERIFICADA` | demais | sim |

- **Denominador**: soma de `d(r)` nas quatro categorias elegíveis (valores conhecidos, `d ≥ 0`,
  rótulo sem contradição). **Numerador**: `IDENTIFICADA_GOVERNANCA_MUNICIPAL`. Cada ocorrência
  entra uma vez, mesmo com várias violações.
- **Razão** (`RAZAO`, só em `NAO_APROVADO` e `APROVADO_PARCIAL`): numerador ÷ denominador com 12
  casas (meio-par), apenas com denominador positivo; senão nula.
- **Totais por família** (`FAMILIA_<F>`, `aditiva = false`): ocorrências elegíveis com VIOLACAO na
  família F. Uma ocorrência com duas famílias aparece nas duas; esses totais não se somam.
- Toda categoria sai em todo estrato, mesmo com zero ocorrências; nenhuma é omitida.

## Governança municipal
A governança vem do catálogo de operações do T09 (`Governanca`: `MUNICIPAL_DOCUMENTADA`,
`FORA_DA_GOVERNANCA_MUNICIPAL`, `DESCONHECIDA`), passada como `governanca_por_familia`. Sem esse
mapa — situação atual, com o T09 ainda fora do main e as operações com governança `DESCONHECIDA`
—, nenhuma família conta como documentada e o numerador é zero; as incompatibilidades ficam em
`INCOMPATIBILIDADE_SEM_GOVERNANCA_DOCUMENTADA`, com contagem e valor.

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
`medir(Etapa, repeticoes=, cache=)` registra tempos por repetição (relógio injetável), pico de
memória Python (`tracemalloc`; não inclui buffers nativos do DuckDB), RSS máximo do processo e
armazenamento do diretório de saída; `gravar_relatorio` grava ambiente, instante UTC, origem dos
dados, cache e repetições. Etapas sem implementação no main (`contrafactuais` do T09, `metricas`
do T11) saem `NAO_MEDIDO motivo=…`. O teste `tests/perf/test_desempenho_s8.py` (marcador `perf`)
exercita o harness em cenário sintético pequeno; a escala DRS XI e SP roda na máquina do
pesquisador, com etapas montadas sobre os artefatos reais (aquisição, ingestão, rótulos, seleção,
motor, explicação, anotação e valores), cache frio e quente declarados e ao menos três repetições.
