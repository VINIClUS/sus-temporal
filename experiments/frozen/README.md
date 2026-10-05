# experiments/frozen — congelamentos do protocolo (T11)

Cada arquivo `frz_<sha256>.json` é um `FreezeManifest` único: o `freeze_id` deriva do conteúdo.
O arquivo nunca é sobrescrito; outro conteúdo com o mesmo id é recusado. O manifesto fixa a
identidade do protocolo (config, código limpo, ambiente, catálogos, regras e políticas), os
datasets completos, o split, a lista positiva de atributos, o bootstrap, as métricas, as
comparações primárias, as margens e a decisão G0 humana que liberou o congelamento.

## Comandos

- `sustemporal freeze --config <cfg>`: exige G0 humano em `experiments/decisions/`. Recusa
  `A_DEFINIR`, código sujo, catálogo ausente e catálogo que a config não declara em
  `config.catalogos`. Registra o catálogo de regras de `catalog/rules`, as políticas de
  `catalog/policies` e as padrão dos baselines; sem esses campos o manifesto não prova catálogo
  nem política.
- `sustemporal evaluate --freeze <id>`: confirmatório. Exige config confirmatória com dados
  REAIS, G2 humano para o `freeze_id` e o manifesto conferido por inteiro (tabela abaixo) antes
  de ler qualquer dado. Avalia só o TESTE e emite as razões do TOTAL, do domínio comum e, por
  valor, de competência, instrumento e estabelecimento (CNES); só o TOTAL e as diferenças
  pareadas levam intervalo. As execuções vêm de `<raiz_saidas>/runs/<run_id>/`: o
  `run_result.json` do motor de regras (`validate` grava ali por padrão, `raiz_execucoes(config)`)
  ou o `run.json` do baseline; os dois no mesmo diretório são recusados (`execucao_ambigua`). Entram só as
  execuções confirmatórias do mesmo `freeze_id`; as demais são ignoradas
  (`evaluate_execucao_ignorada` no log) e, sem nenhuma, o comando sai com código 2
  (`avaliacao_sem_execucoes`). Cada método precisa de resultado para todo registro do TESTE
  (seção "Cobertura dos resultados").
- `sustemporal evaluate --freeze <id> --exploratory`: explícito. Avalia só a CALIBRACAO e
  registra a divergência do manifesto em vez de recusar. Entram só as execuções exploratórias com
  o `config_hash` da config do comando e entradas do split do congelamento (ao menos uma entrada
  dos esquemas congelados e todas conteúdo congelado, a população da CALIBRACAO inclusive); as
  demais de `runs/` são ignoradas (`evaluate_execucao_ignorada`) e, sem nenhuma, o comando sai
  com código 2 (`avaliacao_sem_execucoes`), sem relatório nem registro.
- `registro_execucoes.jsonl`: registro append-only, em que cada linha leva o próprio hash e o
  da anterior. Toda avaliação entra, inclusive a de resultado nulo. Depois da abertura do teste,
  nova rodada confirmatória do mesmo congelamento exige `corrige` + `declaracao`, e a rodada
  anterior permanece. Na CLI: `sustemporal evaluate --freeze <id> --corrige <report_id>
  --declaracao <texto>`, os dois juntos; sem eles a segunda rodada sai com código 4. `corrige`
  só aponta para relatório confirmatório já registrado do mesmo congelamento; alvo de outro
  congelamento, exploratório ou inexistente é recusado (código 2) e não reabre o teste, e a
  correção só vale no confirmatório. A correção precisa de execuções diferentes das da rodada
  anterior: o `report_id` deriva das execuções, e o relatório nunca é sobrescrito.

## Como cada campo do manifesto é conferido

A comparação é uma só, `verificar_congelamento_completo` (`evaluation/freeze_conferencia.py`),
e `CAMPOS_DO_MANIFESTO` classifica todo campo: conferido contra o estado atual do avaliador
(divergência: `freeze_incompativel campos=<campos>`, saída 4), contra cada execução
(`run_incompativel_com_congelamento run=<id> campo=<campos>`) ou informativo, com o motivo. O
teste `tests/integration/test_freeze_campos.py` percorre `FreezeManifest.model_fields` e falha
se um campo novo ficar sem classificação ou se um campo conferido não tiver cenário de
divergência. A biblioteca (`evaluate_runs`) repete a conferência antes de ler dados.

| Campo | Estado atual do avaliador | Cada execução | Observação |
|---|---|---|---|
| `freeze_id` | informativo | informativo | derivado do conteúdo e recomputado ao carregar (`carregar_freeze`) |
| `criado_em` | informativo | informativo | instante do congelamento; entra no id, sem par no estado atual |
| `config_hash` | `config` | `config` | estado: protocolo da config do avaliador (`hash_protocolo`, sem `modo` e `freeze_id`); execução: `config_hash` da config confirmatória |
| `codigo` | `codigo` | `codigo` | mesmo commit e árvore limpa; `versao_pacote` (coberto por `ambiente.pacotes`) e `diff_sha256` (só em código sujo) são informativos |
| `ambiente` | `ambiente` | `ambiente` | Python, dependências (`pacotes`) e `uv_lock_sha256`; a `plataforma` é informativa (inclui a versão do kernel, que muda sem mudar as versões travadas) |
| `catalogos_sha256` | `catalogos` | não se aplica | digest recalculado dos arquivos de `config.catalogos`, pelos mesmos caminhos e a mesma função do `congelar`; arquivo ausente ou alterado diverge |
| `datasets` | `entradas` | `entradas` | estado: cada dataset do avaliador é do congelamento; execução: entradas `sia_pa.v1` e de rótulos congeladas, com a população da partição TESTE entre elas (o baseline pode trazer outras partições); auxiliares, seleções e cobertura não entram no manifesto |
| `split` | `split` | não se aplica | comparado por inteiro, não só pelo `split_id`, que não deriva do conteúdo |
| `features` | `features` | não se aplica | lista positiva de atributos |
| `bootstrap` | `bootstrap` | não se aplica | o `evaluate_runs` confirmatório usa o do manifesto e recusa outro (`avaliacao_confirmatoria_com_bootstrap_diferente_do_congelado`) |
| `metricas` | `metricas` | não se aplica | as métricas do avaliador (`METRICAS_PROTOCOLO`) |
| `comparacoes_primarias` | `comparacoes` | `metodos` | as do avaliador; o confirmatório exige a execução de cada método (M_TEMP, B_ATEND e B_PROC) e, se falta algum, recusa (`avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias`) |
| `margens` | informativo | informativo | a avaliação não usa margens de relevância prática (pendência T11 #2) |
| `decisao_g0` | informativo | informativo | G0 só autoriza congelar (exigido em `congelar`); no teste vale o G2 do `freeze_id` |
| `catalogo_regras_sha256` | `catalogo` | `catalogo` | digest do catálogo de regras; na execução vale para toda menos a de baseline |
| `politicas_sha256` | `politica` | `politica` | hash de cada política do avaliador; na execução, o `politica_id` entre as congeladas (menos baseline) |

Outras recusas, antes de ler dados, com a mesma conferência: execução PARCIAL, FALHOU ou com
falhas registradas (`execucao_incompleta_no_confirmatorio`), porque o que faltou viraria
abstenção do método; e manifesto sem catálogo de regras ou políticas, que recusa as execuções
que usam regras (as de baseline só repetem código, ambiente, config e entradas). Nada disso
entra no registro de rodadas.

## Cobertura dos resultados

Antes de calcular qualquer métrica, `evaluate_runs` compara, por método, o `row_id` dos
resultados lidos com a população da partição avaliada (`evaluation/metrics_cobertura.py`):
`ausentes` são registros sem resultado, `extras`, resultados de registros de fora dela e
`duplicados`, as linhas a mais para o mesmo (método, row_id), em `agregados_registro.v1` ou nas
predições. O método que as predições do baseline declaram em outra partição e que não tem
nenhum resultado do TESTE (o controle trivial) conta com todos os registros ausentes.

- Confirmatório: resultado repetido recusa a avaliação (`execucao_com_resultado_duplicado
  metodo=<método> duplicados=<N>`, saída 4), e depois dele qualquer ausente
  (`execucao_com_cobertura_incompleta metodo=<método> ausentes=<N> extras=<M>`, saída 4), sem
  relatório e sem registro; o primeiro método em ordem alfabética é o citado. Extras só passam
  se a execução traz, entre as entradas, a população de outra partição congelada (o baseline lê
  as partições que ajusta e avalia), o que se confere pelos hashes (pendência T11 #24).
- Exploratório: a linha sem resultado segue contando como abstenção do método, o último
  resultado repetido prevalece e as contagens vão para as notas do relatório, nos dois modos
  (`cobertura_dos_resultados metodo=<método> ausentes=<N> extras=<M> duplicados=<K>`).

Dados sintéticos nunca são confirmatórios. Nenhum congelamento real existe neste repositório
enquanto o projeto estiver antes do G0.
