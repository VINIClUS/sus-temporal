# experiments/frozen — congelamentos do protocolo (T11)

Cada arquivo `frz_<sha256>.json` é um `FreezeManifest` único: o `freeze_id` deriva do conteúdo.
O arquivo nunca é sobrescrito; outro conteúdo com o mesmo id é recusado. Um manifesto fixa:
- `config_hash`: identidade do protocolo, sem `modo` e `freeze_id`;
- versão do código, que precisa estar limpa, e ambiente;
- hashes dos catálogos;
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
  manifesto. Avalia só o TESTE.
- `sustemporal evaluate --freeze <id> --exploratory`: explícito. Avalia só a CALIBRACAO e
  registra a divergência do manifesto em vez de recusar.
- `registro_execucoes.jsonl`: registro append-only, em que cada linha leva o próprio hash e o
  da anterior. Toda avaliação entra, inclusive a de resultado nulo. Depois da abertura do teste,
  nova rodada confirmatória do mesmo congelamento exige `corrige` + `declaracao`, e a rodada
  anterior permanece.

Dados sintéticos nunca são confirmatórios. Nenhum congelamento real existe neste repositório
enquanto o projeto estiver antes do G0.
