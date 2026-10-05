# sus-temporal

Validação temporal e explicável de dados administrativos do SUS: modelo de restrições
versionadas que integra CNES, SIGTAP e SIA-PA, preserva referências temporais e produz explicações
verificáveis. Aplicação local de pesquisa, orientada a lotes (Python 3.12, DuckDB, Parquet). O
recorte inicial são os municípios do DRS XI (Presidente Prudente), de 2018 a 2025, com teste de
escala em SP.

## Estado
Pré-G0. Nenhum dado real foi processado neste repositório; testes e exemplos usam dados
sintéticos gerados por código. Nenhum resultado empírico é afirmado: nenhum teste de software
confirma o método, e `docs/method/claims.md` registra cada conclusão possível da dissertação como
PENDENTE, com a evidência exigida e o portão humano (G0, G1 ou G2) ou o dado real de que depende; o
estado só muda por decisão humana registrada em `experiments/decisions/`.
As decisões G0, G1 e G2 são humanas e ainda não existem. O esboço original
(`docs/spec/esboco_original.pdf`) está pendente e, quando entrar, prevalece sobre o plano quanto ao
escopo científico.

## O que existe
- Aquisição verificável com manifesto append-only (`acquire`, `watch`), leitura estrita de DBC e
  DBF e normalização de SIA-PA, CNES e SIGTAP com cobertura por regra (`ingest`). Quarentena e
  arquivo ausente viram resultados registrados, nunca tabela vazia.
- Relatório de observabilidade do piloto (`pilot-report`) e seleção temporal explícita da versão de
  cada fonte por competência: nunca o mês vizinho e nunca o cadastro atual no lugar do histórico.
- Motor de regras em DuckDB (`validate`) com os estados `CONFORME`, `VIOLACAO`, `INCONCLUSIVO` e
  `NAO_APLICAVEL`: falta de arquivo ou de campo é inconclusão, nunca violação. Cada execução é
  imutável: outro código não regrava `<raiz_saidas>/runs/<run_id>/` (saída 2).
- Explicações com PROV (`explain`) e contrafactuais com condições pendentes e limite de
  minimalidade declarados (`counterfactual`).
- Partições temporais e classificador que não recebe rótulo, campos de erro nem quantidades e
  valores aprovados; congelamento do protocolo (`freeze`); avaliação com registro append-only das
  rodadas (`evaluate`); anotação humana cega (`annotation-export`); P3 de valores e harness de
  desempenho.
- Auditorias no CI: licenças do runtime e redistribuição.

## Comandos
`uv run sustemporal --help` lista os comandos abaixo. Os códigos de saída são 0 (ok), 1 (erro
genérico), 2 (configuração ou entrada inválida), 3 (comando não implementado), 4 (portão recusado),
5 (falha operacional) e 6 (rede proibida).

| Comando | O que faz | Onde ler |
|---|---|---|
| `acquire` | Aquisição das fontes com manifesto append-only; usa a rede só com `runtime.rede_permitida: true` | `docs/runbooks/piloto_local.md` §1 |
| `watch` | Observa de novo a janela de competências recentes e compara com as versões já observadas | `docs/method/temporal.md` §6 |
| `ingest` | Normaliza cada versão do manifesto pela família da fonte e grava a cobertura | `docs/runbooks/piloto_local.md` §3 |
| `pilot-report` | Relatório de observabilidade do piloto | `docs/method/observability.md` |
| `validate` | Avalia as regras com `--policy documented`, `atendimento` ou `processamento`, a partir de `--ingest` ou `--entrada` | `docs/method/model.md` |
| `explain` | Explicação de um registro (`--run`, `--row`) com PROV e limitações | `docs/method/explicacoes.md` |
| `counterfactual` | Busca de contrafactuais de um registro (`--run`, `--row`) | `docs/method/contrafactuais.md` |
| `freeze` | Congela o protocolo; exige decisão G0 humana | `experiments/frozen/README.md` |
| `evaluate` | Avalia as execuções de um congelamento (`--freeze`); o confirmatório exige G2 humano e dados reais, o exploratório é `--exploratory` | `experiments/frozen/README.md` |
| `annotation-export` | Pacote cego de anotação humana de um congelamento (`--freeze`) | `docs/method/annotation.md` |
| `reproduce` | Reprodução offline de um congelamento (`--freeze`, `--offline`) | `docs/runbooks/reproducao.md` |

## O que falta
Tudo o que depende de dados reais ou de decisão humana: aquisição real e conferência dos leiautes,
piloto e decisão G0, decisões G1 e G2, comparações do teste, anotação humana, escala (DRS XI e SP) e
licença de publicação. A lista por dono, com a ferramenta pronta e o passo do runbook de cada item,
está em `docs/PENDENCIAS.md`.

## Como rodar
```bash
uv sync --locked
bash scripts/ci.sh
uv run sustemporal --help
```
`scripts/ci.sh` roda `ruff`, `mypy`, a verificação de propriedade de arquivos e o `pytest`, sem
rede e sem dados reais. Reprodução por um terceiro, em ambiente limpo e sem rede depois da
instalação: `docs/runbooks/reproducao.md`. Piloto real, na máquina do pesquisador:
`docs/runbooks/piloto_local.md`. Dados reais nunca entram no Git.

## Documentação
- Plano de implementação: `docs/plan/`; especificação-base e manifesto: `docs/spec/`
- Alegações possíveis e evidência exigida: `docs/method/claims.md`; método: `docs/method/`
- Pendências consolidadas por dono: `docs/PENDENCIAS.md` (detalhe em `docs/pendencias/`)
- Roteiros de execução: `docs/runbooks/`
- Guia para contribuidores e agentes: `AGENTS.md`; processo e propriedade de arquivos:
  `docs/process/`
- Decisões de arquitetura: `docs/decisions/`; fontes e inventário de campos: `docs/references/`
