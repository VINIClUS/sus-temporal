# experiments/frozen — congelamentos do protocolo (T11)

Cada arquivo `frz_<sha256>.json` é um `FreezeManifest` único: o `freeze_id` deriva do conteúdo.
O arquivo nunca é sobrescrito; outro conteúdo com o mesmo id é recusado. Um manifesto fixa:
- `config_hash`: identidade do protocolo, sem `modo` e `freeze_id`;
- versão do código, que precisa estar limpa, e ambiente;
- hashes dos catálogos;
- `catalogo_regras_sha256`: identidade do catálogo de regras (a mesma que as execuções de
  validação registram) e `politicas_sha256`: hash canônico de cada política, por `politica_id`.
  `sustemporal freeze` registra as regras de `catalog/rules`, as políticas de `catalog/policies`
  e as padrão dos baselines; sem esses campos o manifesto não prova catálogo nem política;
- datasets completos (`sia_pa.v1` e rótulos);
- split, com partições e rótulos por partição;
- lista positiva de atributos;
- bootstrap (reamostragens, semente e correção por multiplicidade);
- métricas;
- comparações primárias (`M_TEMP_x_B_ATEND`, `M_TEMP_x_B_PROC`);
- margens;
- a decisão G0 humana que liberou o congelamento.

- `sustemporal freeze --config <cfg>`: exige G0 humano em `experiments/decisions/`. Recusa
  `A_DEFINIR`, código sujo e catálogo ausente.
- `sustemporal evaluate --freeze <id>`: confirmatório. Exige config confirmatória com dados
  REAIS, G2 humano para o `freeze_id` e código, split, atributos, config e entradas idênticos ao
  manifesto. Avalia só o TESTE. Antes de ler qualquer dado, confere cada execução contra o
  manifesto carregado, não só pelo `freeze_id`:
  - `codigo`: mesmo commit e árvore limpa;
  - `config`: o `config_hash` da execução é o da config confirmatória, cujo protocolo
    (`hash_protocolo`, sem `modo` e `freeze_id`) confere com o manifesto;
  - `catalogo` e `politica` (toda execução, menos a de baseline): `catalogo_regras_sha256`
    igual ao congelado e `politica_id` entre as políticas congeladas;
  - `entradas`: toda entrada `sia_pa.v1` ou de rótulos é do congelamento, e ao menos uma existe;
    auxiliares, seleções e cobertura não entram no manifesto e não são conferidos.

  Divergência recusa com `run_incompativel_com_congelamento run=<id> campo=<campos>` (saída 4).
  Manifesto sem catálogo ou políticas recusa as execuções que usam regras; as de baseline só
  repetem código, config e entradas. O confirmatório também exige execução de cada método das
  comparações primárias do manifesto (M_TEMP, B_ATEND e B_PROC); se falta alguma, recusa
  (`avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias`) antes de avaliar, e nada entra
  no registro.
- `sustemporal evaluate --freeze <id> --exploratory`: explícito. Avalia só a CALIBRACAO e
  registra a divergência do manifesto em vez de recusar.
- `registro_execucoes.jsonl`: registro append-only, em que cada linha leva o próprio hash e o
  da anterior. Toda avaliação entra, inclusive a de resultado nulo. Depois da abertura do teste,
  nova rodada confirmatória do mesmo congelamento exige `corrige` + `declaracao`, e a rodada
  anterior permanece. `corrige` só aponta para relatório confirmatório já registrado do mesmo
  congelamento; alvo de outro congelamento, exploratório ou inexistente é recusado e não reabre
  o teste.

Dados sintéticos nunca são confirmatórios. Nenhum congelamento real existe neste repositório
enquanto o projeto estiver antes do G0.
