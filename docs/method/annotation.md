# Anotação humana cega das rejeições (T12)

Estado: software pronto e testado só com dados `SINTETICO`. Nada aqui é resultado empírico; as
horas abaixo são planejamento, não medição.

## Objetivo e limites
A anotação produz uma **referência humana baseada nas evidências disponíveis** para a causa
cadastral de rejeições observadas (rótulo `NAO_APROVADO`). Ela não é log oficial de causa. A
comparação com o motor só acontece depois de a referência ser fechada. A amostra não sustenta
afirmação de precisão causal populacional fora do desenho amostral registrado; em particular,
nunca se avalia só o subconjunto que o motor explica.

## População e partições
- Rejeições da partição `TESTE` do `SplitManifest` congelado (competência de processamento). A
  partição é um `DatasetRef` `sia_pa.v1` cujo hash lógico e contagem conferem com
  `hash_por_particao`/`linhas_por_particao`; Parquet ilegível ou divergente é falha operacional.
- Os rótulos (`sia_pa_rotulos.v1`) precisam cobrir toda a partição; registro sem rótulo interrompe
  a preparação (não é tratado como aprovado nem descartado em silêncio).
- Linhas repetidas não são deduplicadas: cada `row_id` é uma ocorrência; reapresentações não
  vinculáveis continuam ocorrências distintas.

## Estratos (características observáveis, independentes do método)
| Dimensão | Definição | Valores |
|---|---|---|
| `instrumento` | `instrumento` canônico | código; `DESCONHECIDO` se nulo |
| `periodo` | ano da competência de processamento | `AAAA`; `DESCONHECIDO` |
| `estabelecimento` | terço do CNES por volume de registros na partição (todos os registros, não só rejeições) | `VOLUME_1` (menor) a `VOLUME_3`; `DESCONHECIDO` |
| `defasagem` | meses entre processamento e atendimento | `0`, `1`, `2_3`, `4_MAIS`, `NEGATIVA`, `DESCONHECIDA` |

Nenhuma saída do motor (`avaliacoes.v1`, `agregados_registro.v1`, `evidencias.v1`) é lida; a
função recusa dimensão fora dessa lista (`dimensao_nao_observavel`). A faixa de volume do
estabelecimento substitui o CNES individual porque, no DRS XI, o número de CNES pode exceder o
tamanho da amostra; a escolha é de desenho e pode ser revista antes do congelamento.

## Sorteio e probabilidades de inclusão
- Tamanho padrão 400 (configurável por `tamanho`); semente `RunConfig.semente`.
- Alocação proporcional com ao menos um caso por estrato e soma exata; com mais estratos que
  casos, a preparação falha. Se o tamanho cobre a população, faz-se censo (probabilidade 1).
- Em cada estrato, amostra aleatória simples sem reposição. `Estrato.prob_inclusao =
  amostra/populacao` (12 casas, meio-par), conferida pelo contrato. Peso de desenho = inverso.
- `privado/estratos.json` guarda o estrato de cada rejeição da população, para estimativas
  ponderadas e auditoria.

## Treino dos avaliadores
`casos_treino` (padrão 20) sai das rejeições da partição `DESENVOLVIMENTO`, nunca da amostra
final; o contrato recusa interseção e a concordância recusa caso de treino
(`caso_de_treino_na_avaliacao_final`). O treino serve para medir tempo e ajustar o formulário
antes de congelá-lo.

## Pacote cego
`pacote/` contém `casos.json`, `treino.json` e `formulario.json`:
- só as colunas de `COLUNAS_PACOTE` (estabelecimento, competências, procedimento, instrumento,
  CBO, CID, idade, sexo, quantidades, valores e campos de erro do processamento) e o rótulo;
- `caso_id` pseudônimo (`caso_NNNN`, `treino_NNNN`) em ordem embaralhada pela semente, que não
  revela o estrato;
- fora do pacote: `row_id`, artefato, membro, índice, colunas `_bruto`/`_motivo`, município do
  paciente, raça/cor, etnia e qualquer coluna estranha ao esquema (inclusive resultados do motor
  que porventura estejam no Parquet). A lista fica em `AnnotationSample.colunas_excluidas`;
- `privado/mapa_casos.json` (caso → row_id) fica com a coordenação, fora do pacote.

Por que cada grupo de colunas é necessário: CNES, município, tipo de unidade, gestão e
habilitações/incentivos permitem consultar o cadastro do estabelecimento (CNES); competências
permitem escolher a versão de referência; procedimento, instrumento, CBO, CID, caráter, idade e
sexo são os insumos das famílias de compatibilidade do SIGTAP; quantidades e valores, código de
ocorrência e indicadores de erro do processamento (`pa_codoco`, `pa_flqt`, `pa_fler`,
`pa_flidade`) são evidência oficial que o plano admite na anotação (nunca atributo de predição).
Idade, sexo e CID são quase-identificadores: o pacote fica em ambiente controlado, sem
identificador de paciente nem município de residência, e não sai da máquina do pesquisador.
Não há proteção de privacidade formal (ex.: k-anonimato); isso é limitação declarada.

Parquet sem alguma coluna exigida pela amostragem (rótulo, competências, CNES, instrumento) ou
pelo pacote é falha operacional (`anotacao_leiaute_incompativel`) antes de qualquer consulta.

Uma exportação existente em `out/` nunca é sobrescrita por amostra diferente
(`pacote_ja_exportado`); repetir a mesma exportação é idempotente. Partição de teste sem
rejeições interrompe a exportação (`anotacao_sem_rejeicoes`) em vez de gerar pacote vazio;
treino menor que o pedido é registrado em log.

## Formulário `anotacao_formulario.v1`
`AvaliacaoCaso`: `conclusao` ∈ {`INCOMPATIBILIDADE_IDENTIFICADA`,
`CAUSA_FORA_DE_ESCOPO_DOCUMENTADA`, `CAUSA_INDETERMINADA`, `EVIDENCIA_INSUFICIENTE`}; `familias`
múltiplas (obrigatórias só com incompatibilidade identificada); `evidencias` (texto livre do
avaliador); `minutos`. Causa indeterminada e evidência insuficiente são categorias próprias.

As respostas são entregues em `LoteAvaliacoes` (`sample_id`, `formulario_versao`, `avaliador`,
`respostas`); o cabeçalho de `pacote/casos.json` traz o `sample_id` a copiar. Lote de outra amostra
ou de outro formulário é falha operacional (`respostas_de_outra_amostra`,
`respostas_de_outro_formulario`), mesmo que os `caso_id` coincidam. O conjunto de famílias usado
no κ por família vem da versão congelada do formulário (`FAMILIAS_POR_FORMULARIO`), nunca do enum
corrente; versão desconhecida é falha operacional (`formulario_desconhecido`).

## Concordância e adjudicação
- Antes da adjudicação: concordância bruta e κ de Cohen (exatos, em `Fraction`) sobre a resposta
  inteira (conclusão e conjunto de famílias) e, por família, sobre PRESENTE/AUSENTE/NAO_DETERMINADO; κ indefinido (`None`) quando
  a concordância esperada é 1. Cada avaliador responde todos os casos, uma vez.
- Adjudicação cega: recebe só as duas respostas e o adjudicador não pode ser um dos avaliadores;
  casos iguais viram consenso, divergentes exigem
  adjudicação. Com pendências a referência fica `ABERTA`; `FECHADA` exige todos os casos da
  amostra (`casos_amostra`).
- `comparar_com_motor` recusa referência `ABERTA` (`ReferenciaNaoFechada`). Categorias:
  `IGUAL`, `PARCIAL`, `DIVERGENTE`, `MOTOR_SEM_FAMILIA`, `MOTOR_SEM_RESULTADO`,
  `CONCORDA_FORA_DE_ESCOPO`, `MOTOR_ATRIBUI_FAMILIA_FORA_DE_ESCOPO`, `CAUSA_INDETERMINADA`,
  `EVIDENCIA_INSUFICIENTE`. Indeterminados não contam como acerto nem erro do motor.

## Estimativa de esforço (planejamento)
`horas = 2 × 400 × minutos_por_caso / 60`, mais a adjudicação (`estimar_horas`). Com 5 a 10
minutos por caso: cerca de 67 a 133 horas de avaliação combinada. O tempo real deve ser medido no
treino antes de fixar o cronograma.

## Execução
`sustemporal annotation-export --freeze FREEZE_ID` lê
`<runtime.dir_congelamentos>/FREEZE_ID.json`, confere o id pelo conteúdo, resolve rótulos e
partições pelos `DatasetRef` do manifesto (hash lógico do split) e grava em
`<runtime.raiz_saidas>/anotacao/FREEZE_ID/`.
