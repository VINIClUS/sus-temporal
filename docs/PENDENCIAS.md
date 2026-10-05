# Pendências consolidadas (T14)

Consolidação de todas as pendências registradas em `docs/pendencias/T*.md`, por dono: pesquisador,
orientação, avaliadores e engenharia. Os arquivos originais continuam sendo a fonte do detalhe;
nenhum foi alterado ou apagado. Cada ação traz a ferramenta pronta e o passo do runbook.

Estado: pré-G0. Nenhum dado real foi processado neste repositório e nenhuma pendência de dado real
ou de decisão humana foi fechada. Nada aqui é resultado empírico.

## Como ler

- **Chaves.** `TNN-n` é o item numerado `n` do arquivo; `TNN-bn` é o item `bn` da T13b; `TNN-in` é
  o n-ésimo item sem número do arquivo (ponto de lista no primeiro nível ou linha de tabela sem
  coluna `#`), contado de cima para baixo. `ORQ-NN` são as pendências registradas pelo
  orquestrador (seção 5).
- **Ação.** Cada bloco `### XX-NN` reúne itens que se fecham com o mesmo trabalho. `PQ` é
  pesquisador, `OR` orientação, `AV` avaliadores, `EN` engenharia e `FE` item já fechado.
- **Runbooks.** `docs/runbooks/piloto_local.md` (piloto real, seções 0 a 5) e
  `docs/runbooks/reproducao.md` (reprodução; a seção 7 traz as etapas com rede ou dados reais).
- **Alegações.** `docs/method/claims.md` cita as chaves de cada alegação em `Pendências`.

## Resumo

| Dono | Ações | Itens dos arquivos T*.md |
|---|---|---|
| Pesquisador | 12 | 73 |
| Orientação | 9 | 37 |
| Avaliadores | 3 | 3 |
| Engenharia | 24 | 96 |
| Fechadas | 3 | 36 |
| Orquestrador (seção 5) | 33 linhas `ORQ` | fora dos arquivos T*.md |

Total de itens dos arquivos T*.md: 245 em 14 arquivos.

**Manutenção.** Quem registrar pendência nova em `docs/pendencias/TNN.md` avisa o orquestrador ou
a S9 para refazer esta consolidação (só a S9 e o orquestrador editam este arquivo). O teste
`tests/unit/test_pendencias.py` falha se um item consolidado sumir daqui e só avisa
(`pendencia_nao_reconsolidada`) quando um arquivo de pendências muda depois da consolidação.

## 1. Pesquisador

### PQ-01 — Aquisição real do piloto e conferência do catálogo de fontes

- **Itens:** T02-1 (diretórios e padrões de nome de catalog/sources.yaml); T02-2 (primeira aquisição
  real das seis competências); T02-7 (temporários baixando_* deixados por SIGKILL); T13-2
  (diretórios e padrões de nome da janela de vigilância)
- **Ferramenta pronta:** `sustemporal acquire --config CFG` (passada primária) e
  `--passada auxiliar --competencias-atendimento ARQUIVO`; manifesto `aquisicao.jsonl`.
- **Runbook:** `docs/runbooks/piloto_local.md` §1; `docs/runbooks/reproducao.md` §7.1.
- **Estado:** aberta (máquina com rede)
- **Nota:** Compare a listagem observada com `catalog/sources.yaml` e registre em
  `docs/references/fontes.md`.

### PQ-02 — Documentos oficiais: obter, preservar e fundamentar regras e políticas

- **Itens:** T02-6 (documentos só com URL http:// não são requisitáveis); T06-1 (base documental das
  políticas, M_TEMP_PADRAO é NAO_RESOLVIDA); T07-i3 (trecho normativo de cada compatibilidade,
  referencia PENDENTE); T07-i4 (critério temporal documental por fonte); T07-i5 (mapa PA_DOCORIG
  para CO_REGISTRO, INFERIDA); T07-i6 (aplicabilidade de PROCEDIMENTO_CBO sem ocupação listada);
  T07-i7 (instrumentos e procedimentos em que vale estabelecimento–CBO); T07-i8 (presença em
  tb_procedimento como vigência); T04-25 (INSTRUMENTO_REGISTRO só DISPONIVEL com o CO_REGISTRO do
  instrumento); T09-i4 (IT CNES 1706, O7); T09-i5 (CNES, Dúvidas Frequentes, competências fechadas,
  W5); T09-i6 (calendário de fechamento de competência do CNES)
- **Ferramenta pronta:** `catalog/sources.yaml` (`documentos`; `acquire` obtém por ftp, https e
  `file://`, canal IMPORTACAO_MANUAL), `docs/references/fontes.md` e o `DocRef` PRESERVADO em
  `RuleSpec.referencia` (`catalog/rules/`).
- **Runbook:** `docs/runbooks/piloto_local.md` §1 e §2 (passo 3 de "Atualizar o catálogo por PR");
  `docs/runbooks/reproducao.md` §7.1 e §7.3.
- **Estado:** aberta
- **Nota:** Sem trecho e hash preservados a política `M_TEMP` se abstém e as referências ficam
  `PENDENTE`.

### PQ-03 — Leiautes e cabeçalhos reais (SIA-PA, CNES e SIGTAP)

- **Itens:** T02-3 (versões de DBF/dBASE aceitas e validade do cabeçalho DBC); T03-11 (leiaute do
  SIA-PA contra cabeçalhos reais); T04-1 (leiaute SIGTAP estrito contra os *_layout.txt reais);
  T04-2 (casas decimais implícitas de VL_SH, VL_SA e VL_SP); T04-3 (DT_COMPETENCIA diferente da
  competência do arquivo); T04-7 (nome exato dos membros do zip do SIGTAP); T04-17 (leiaute PF de 40
  campos contra cabeçalhos reais); T04-18 (leiaute ST inferido); T04-31 (um leiaute CNES por fonte);
  T05-2 (leiautes A_CONFIRMAR antes do ingest real)
- **Ferramenta pronta:** `ler_cabecalho` e `descomprimir_dbc` (`src/sustemporal/ingest/dbf.py` e
  `dbc.py`) no roteiro de conferência; `catalog/layouts/*.yaml` atualizado por PR de humano.
- **Runbook:** `docs/runbooks/piloto_local.md` §2 e "Atualizar o catálogo por PR";
  `docs/runbooks/reproducao.md` §7.3.
- **Estado:** aberta (máquina com dados reais)
- **Nota:** Leiaute errado manda o arquivo para `QUARENTENA_LEIAUTE`; rode antes do `ingest` real.

### PQ-04 — Fidelidade e codificação da leitura DBC nos arquivos reais

- **Itens:** T03-1 (fidelidade nos DBC reais do recorte, modo COMPLETA); T03-2 (terminador 0x0D do
  cabeçalho pode faltar em DBC reais); T03-3 (back-references DCL só exercitadas por arquivos
  reais); T03-5 (codificação real do texto, a leitura é latin-1 bijetivo); T03-7 (4 bytes após o
  cabeçalho sem especificação); T03-8 (bytes após o código de fim DCL); T03-12 (leitura diferencial
  em arquivos reais e perfis)
- **Ferramenta pronta:** `sustemporal ingest` com `runtime.verificacao_fidelidade: COMPLETA`
  (padrão), que chama `verificar_fidelidade` (`src/sustemporal/ingest/dbc.py`); `perfil_pa`
  (`src/sustemporal/evaluation/labels.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.4; `docs/runbooks/piloto_local.md` §3.
- **Estado:** aberta (máquina com dados reais)
- **Nota:** O relatório de fidelidade só vai para o log: guarde a saída do `ingest`.

### PQ-05 — Declarar as partes esperadas do SIA-PA no catálogo

- **Itens:** T02-12 (partes esperadas por competência não declaradas); T06-3 (partes esperadas não
  declaradas deixam a competência INCOMPLETA)
- **Ferramenta pronta:** `catalog/sources.yaml` (`partes_esperadas`) e a listagem da
  `sustemporal acquire`.
- **Runbook:** `docs/runbooks/reproducao.md` §7.2.
- **Estado:** aberta (PR de humano)
- **Nota:** Sem a declaração, a competência multipartes fica INSUFICIENTE e as linhas dependentes
  saem INCONCLUSIVO (ver ORQ-12).

### PQ-06 — Execução do piloto, registro e perfil de rótulos e campos

- **Itens:** T05-1 (execução real das seis competências de desenvolvimento); T05-10 (execução do
  ingest usada pelo pilot-report); T05-11 (rótulos do piloto só descrevem a distribuição); T05-16
  (campos do G0 em piloto_campos.v1); T03-13 (amostra manual estratificada, bruto contra canônico);
  T03-14 (cobertura do PA_INDICA em 2018–2025); T03-15 (semântica dos motivos, sentinelas e padrões
  A_CONFIRMAR); T03-16 (unidade de PA_IDADE e sentinela 999); T03-20 (formas numéricas e motivos de
  ausência); T03-23 (inteiros negativos viram CODIFICACAO_INVALIDA)
- **Ferramenta pronta:** `sustemporal ingest` e `sustemporal pilot-report` (`piloto_rotulos.v1`,
  `piloto_campos.v1`, `piloto_defasagem.v1`); `label_pa` e `perfil_pa`
  (`src/sustemporal/evaluation/labels.py`).
- **Runbook:** `docs/runbooks/piloto_local.md` §3 e §4; `docs/runbooks/reproducao.md` §7.5 e §7.6.
- **Estado:** aberta (máquina com dados reais)
- **Nota:** Guarde a pasta do `ingest` de cada relatório (T05-10) e os hashes das tabelas.

### PQ-07 — Medir quarentenas, descartes e exclusões nas fontes de referência

- **Itens:** T04-4 (chave repetida com conteúdo divergente no SIGTAP); T04-5 (código fora do domínio
  do motor manda a tabela para quarentena); T04-6 (atributo numérico não numérico manda a tabela
  para quarentena); T04-10 (disponibilidade do SIGTAP por competência, mensal ou trimestral); T04-19
  (linha do PF com CNES ou CBO inválido deixa a competência INSUFICIENTE); T04-20 (registros
  deletados do DBF e semântica de deleção)
- **Ferramenta pronta:** `resultados.jsonl` e a reconciliação do `ingest` (`excluidas_por_motivo`,
  `FORA_DO_RECORTE`); `piloto_exclusoes.v1` do `pilot-report`.
- **Runbook:** `docs/runbooks/piloto_local.md` §3 (revisar `resultados.jsonl`);
  `docs/runbooks/reproducao.md` §7.5.
- **Estado:** aberta (máquina com dados reais)
- **Nota:** Frequência alta de quarentena ou de linhas inválidas deixa a família inconclusiva em
  massa e passa ao G0.

### PQ-08 — Medir tetos de descompressão e leitura nos maiores arquivos reais

- **Itens:** T02-8 (tetos do ZIP sem medição); T02-13 (teto do DBF descomprimido sem medição); T04-9
  (limite de descompressão por membro)
- **Ferramenta pronta:** `bytes_recebidos` de cada observação em `aquisicao.jsonl`; parâmetros
  `LimitesZip` e `LIMITE_DBF_PADRAO` (`src/sustemporal/acquisition/validation.py`) e
  `limite_membro_bytes` (`src/sustemporal/ingest/sigtap.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.1 e §7.5.
- **Estado:** aberta (máquina com dados reais)
- **Nota:** Mover para o catálogo ou a configuração só depois da medição (ver EN-03).

### PQ-09 — Escala e desempenho no DRS XI e em SP

- **Itens:** T03-6 (custo da verificação de fidelidade em arquivos estaduais); T03-9 (custo da
  leitura por arquivo); T03-19 (memória da leitura com fidelidade ligada); T03-21 (descompressão
  limitada e custo do processo filho); T07-i13 (validação linha a linha dos contratos: medir com
  volume real); T07-i14 (conferência do conteúdo de cada DatasetRef a cada execução); T08-i7 (custo
  por linha da conferência de hashes em cada explicação); T09-i12 (candidatos inadmissíveis não
  contam em max_candidatos); T09-i15 (limite de prova de minimalidade pela soma dos menores custos);
  T09-i18 (custo de reavaliar o conjunto SIA-PA a cada candidato); T13-b4 (escala do DRS XI e de SP:
  tempo, memória e armazenamento)
- **Ferramenta pronta:** `sustemporal.evaluation.performance` (`medir` e `gravar_relatorio`,
  `src/sustemporal/evaluation/performance.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.8; `docs/method/valores.md` (seção "Desempenho").
- **Estado:** aberta (máquina com dados reais)
- **Nota:** Cache frio e quente e ao menos três repetições; relatório JSON fora do Git.

### PQ-10 — Vigilância de republicações por doze meses

- **Itens:** T13-1 (doze meses de observação semanal reais)
- **Ferramenta pronta:** `sustemporal watch --config config/watch.yaml` (`vigilancia.jsonl`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.7; `docs/method/temporal.md` §6 (exemplos de cron e
  systemd).
- **Estado:** aberta (agendar na máquina com rede)
- **Nota:** Versões não coletadas hoje podem deixar de ser recuperáveis: comece cedo.

### PQ-11 — Licença de publicação, bibliotecas embarcadas, esboço e reprodução real

- **Itens:** T14-5 (licença de publicação ainda não definida); T14-6 (bibliotecas do GCC embarcadas
  nas wheels); T14-7 (esboço original PENDENTE: conferir os enunciados das alegações); T14-9
  (reprodução do congelamento real por um terceiro)
- **Ferramenta pronta:** `tests/unit/test_licencas.py`, `tests/unit/test_redistribuicao.py`,
  `docs/spec/manifest.yaml` e `sustemporal reproduce` (só reproduz o exploratório).
- **Runbook:** `docs/runbooks/reproducao.md` §5 e §8.
- **Estado:** aberta (decisão humana)
- **Nota:** A licença escolhida precisa caber na allowlist de licenças permissivas do runtime.

### PQ-12 — Congelar, validar e avaliar no mesmo ambiente e na raiz do repositório

- **Itens:** T11-15 (manifesto sem catalogo_regras_sha256 ou politicas_sha256: congelar de novo);
  T11-22 (plataforma do Ambiente é informativa: sistema e arquitetura podem mudar resultados
  numéricos); T11-23 (ambiente observado a partir do diretório de trabalho: congelar, validar e
  avaliar sempre da raiz do repositório)
- **Ferramenta pronta:** `sustemporal freeze` (registra `catalogo_regras_sha256` e
  `politicas_sha256`), `ambiente` (`src/sustemporal/runtime_info.py`) e a observação
  `pacotes_diferentes_do_congelado` do `reproduce`.
- **Runbook:** `docs/runbooks/reproducao.md` §5.3 (comandos da raiz do clone) e §7.6.
- **Estado:** aberta (rotina do pesquisador antes do G2)
- **Nota:** Se a reprodução entre máquinas for requisito do teste, registrar família do sistema e
  arquitetura em campos próprios do `Ambiente` e conferi-los (T11-22).

## 2. Orientação

### OR-01 — Revisar o relatório real do piloto e registrar a decisão G0

- **Itens:** T05-3 (revisão do relatório real com a orientação); T05-4 (decisão G0 humana, o modelo
  não libera portão); T05-12 (métricas por estabelecimento); T07-i1 (G0: escolher as duas primeiras
  famílias observáveis); T07-i2 (famílias pós-G1 continuam reservadas); T04-14 (colapso de
  duplicatas exatas, decisão do orquestrador, revisar no G0)
- **Ferramenta pronta:** `sustemporal pilot-report` sobre dados reais,
  `experiments/decisions/MODELO_G0.yaml` (cópia `G0_<AAAA-MM-DD>.yaml` por PR de humano) e
  `sustemporal.gates`.
- **Runbook:** `docs/runbooks/piloto_local.md` §5; `docs/runbooks/reproducao.md` §7.6.
- **Estado:** aberta (decisão humana)
- **Nota:** Separar limitação amostral de ausência estrutural, com denominadores. O modelo nunca
  libera portão e agentes não criam decisões.

### OR-02 — Território, pertença e critério geográfico

- **Itens:** T05-5 (pertença territorial: fixa ou histórica); T05-6 (critério geográfico: município
  do estabelecimento); T05-19 (pertença histórica versionada recusada); T04-29 (território: dígito
  verificador e composição de 2018 a 2025); T10-2 (pertença geográfica A_DEFINIR no build_splits)
- **Ferramenta pronta:** `catalog/territorio/drs_xi.yaml`, `config/cohort.yaml` (`pertenca`,
  `criterio_geografico`) e `CohortSpec`.
- **Runbook:** `docs/runbooks/piloto_local.md` §0 (coorte) e §5; `docs/runbooks/reproducao.md` §7.6.
- **Estado:** aberta (decisão humana)
- **Nota:** `pertenca=HISTORICA` segue recusada até haver composição datada do DRS XI.

### OR-03 — Seleção temporal e republicações: decisões de política

- **Itens:** T06-2 (republicação divergente sem política vira AMBIGUA); T06-4 (corte de observação
  não definido para o piloto); T06-8 (quarentena divergente ao lado de conteúdo íntegro); T05-20
  (versões concorrentes do SIA-PA saem da população); T10-4 (identificação longitudinal e versões
  republicadas na mesma partição)
- **Ferramenta pronta:** `catalog/policies/` (`B_ATEND`, `B_PROC`, `M_TEMP_PADRAO`),
  `RunConfig.corte_observacao` e `sustemporal validate --policy`.
- **Runbook:** `docs/runbooks/piloto_local.md` §3 (revisar `versoes_concorrentes`) e §5;
  `docs/runbooks/reproducao.md` §4.3 e §7.6.
- **Estado:** aberta (decisão humana, possivelmente no G0)
- **Nota:** Decidir como resolver republicação divergente, fixar o corte de observação e a versão
  vigente por fonte antes do G2.

### OR-04 — Interpretações e escopo a confirmar com a orientação

- **Itens:** T08-i3 (ablação que congela a versão da regra: interpretação a confirmar); T13-3
  (semântica dos resultados da comparação de republicações); T13-6 (janela da vigilância limitada ao
  recorte 201801–202512)
- **Ferramenta pronta:** `src/sustemporal/evaluation/ablation.py`, comparação de republicações
  (`src/sustemporal/acquisition/comparacao.py`) e `config/watch.yaml`.
- **Runbook:** `docs/runbooks/reproducao.md` §7.7 (T13-3 e T13-6); a ablação ainda não tem passo
  próprio.
- **Estado:** aberta (decisão humana)
- **Nota:** Confirmar antes de usar o relatório da vigilância e as ablações em análise.

### OR-05 — Revisão G1: explicações de uma cadeia real pequena

- **Itens:** T08-i1 (G1: revisar explicações de uma cadeia real pequena); T08-i2 (revisão de
  exemplos reais dos modelos de texto)
- **Ferramenta pronta:** `sustemporal explain --run RUN_ID --row ROW_ID` e
  `docs/method/explicacoes.md`.
- **Runbook:** `docs/runbooks/reproducao.md` §4.3 (o mesmo comando sobre a cadeia real);
  `docs/runbooks/piloto_local.md` §3.
- **Estado:** aberta (decisão humana)
- **Nota:** Corrigir os modelos de texto antes do G1, nunca para favorecer um método. O G1 é
  registro humano em `experiments/decisions/`.

### OR-06 — Governança das operações cadastrais, com especialista

- **Itens:** T09-i1 (governança das operações com especialista); T09-i2 (calibração dos custos 1, 2
  e 3); T09-i3 (admissibilidade da reclassificação de CBO); T13-b1 (governança municipal por família
  na P3)
- **Ferramenta pronta:** `catalog/operations.yaml` e
  `sustemporal counterfactual --run RUN_ID --row ROW_ID`; `docs/method/contrafactuais.md` §2 e §6.
- **Runbook:** ainda sem passo de runbook; ver `docs/method/contrafactuais.md` §2 e §6 e
  `docs/runbooks/reproducao.md` §7.6 para o registro.
- **Estado:** aberta (decisão humana)
- **Nota:** Sem autoridade e governança confirmadas, nenhuma solução sai potencialmente executável e
  a razão da P3 fica indeterminada.

### OR-07 — Protocolo do teste (G2): atributos, hiperparâmetros e anotação

- **Itens:** T10-1 (atributos com dados reais: observabilidade antes do processamento); T10-6
  (hiperparâmetros fixos, sem busca); T12-i3 (confirmar tamanho, estratos e faixa de volume no
  protocolo congelado)
- **Ferramenta pronta:** `FEATURES_PADRAO` (`src/sustemporal/evaluation/features.py`),
  `config/splits.yaml`, `sustemporal freeze` e
  `docs/method/annotation.md`.
- **Runbook:** `docs/runbooks/reproducao.md` §4.4 e §4.5 (portões e freeze) e §7.9.
- **Estado:** aberta (decisão humana antes do G2)
- **Nota:** Congelar população, rótulos, políticas, catálogo, atributos, métricas, sementes e
  artefatos antes do teste.

### OR-08 — Revisar cada conclusão contra a evidência

- **Itens:** T14-8 (revisar cada conclusão contra a evidência ao redigir)
- **Ferramenta pronta:** `docs/method/claims.md`, `tests/unit/test_alegacoes.py` e
  `tests/unit/test_alegacoes_decisoes.py`.
- **Runbook:** `docs/runbooks/reproducao.md` §3 e §6.
- **Estado:** aberta (decisão humana)
- **Nota:** O estado de uma alegação só muda por PR de humano com a decisão da alegação em
  `experiments/decisions/alegacoes/<AAAA-MM-DD>.yaml` (regra 2 de `docs/method/claims.md`) e, em
  CONFIRMADA e NAO_CONFIRMADA, a decisão de cada portão.

### OR-09 — Protocolo do teste (G2): estatística, margens, dimensionamento e populações-alvo

- **Itens:** T11-1 (correção por multiplicidade A_DEFINIR em config/splits.yaml); T11-2 (margens de
  relevância prática não definidas); T11-3 (dimensionamento do estudo); T11-4 (G2 e teste
  confirmatório: nenhum resultado confirmatório existe); T11-5 (bootstrap: 2000 reamostragens,
  semente 2027 e as duas populações-alvo); T11-7 (domínio comum avaliável); T11-17 (lista exata
  das políticas do protocolo); T11-18 (corrige só aceita alvo do mesmo freeze_id)
- **Ferramenta pronta:** `sustemporal freeze` e `sustemporal evaluate --freeze FREEZE_ID`
  (`src/sustemporal/evaluation/cli.py`), `config/splits.yaml` (`Protocolo`) e
  `experiments/decisions/MODELO_G0.yaml` (G2 é registro humano no mesmo diretório).
- **Runbook:** `docs/runbooks/reproducao.md` §4.5 (congelamento e avaliação exploratórios sobre o
  mundo sintético) e §7.6.
- **Estado:** aberta (decisão humana antes do G2)
- **Nota:** Fixar HOLM, BONFERRONI ou SEM_TESTE_FORMAL, as margens e o domínio comum sem olhar
  resultados do teste, e congelá-los antes do G2. A rodada confirmatória é única e exige dados
  REAIS, `freeze` compatível e o G2 que a libere.

## 3. Avaliadores

### AV-01 — Recrutar dois avaliadores independentes e um adjudicador

- **Itens:** T12-i1 (recrutar dois avaliadores independentes e um adjudicador)
- **Ferramenta pronta:** `docs/method/annotation.md` (seções "Pacote cego" e "Adjudicação").
- **Runbook:** `docs/runbooks/reproducao.md` §7.9.
- **Estado:** aberta
- **Nota:** Nenhum deles acessa explicações, contrafactuais ou saídas do motor antes do fechamento
  da referência.

### AV-02 — Treinar os avaliadores e ajustar o formulário

- **Itens:** T12-i2 (treinar, medir minutos por caso e ajustar o formulário)
- **Ferramenta pronta:** casos `treino_*` do pacote, formulário `anotacao_formulario.v1` e
  `estimar_horas` (`src/sustemporal/evaluation/annotation_concordancia.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.9; `docs/method/annotation.md` ("Treino dos
  avaliadores").
- **Estado:** aberta
- **Nota:** Mudança no formulário gera nova versão antes da amostra final.

### AV-03 — Anotação real, concordância e adjudicação cega

- **Itens:** T12-i4 (anotação real, concordância e adjudicação cega)
- **Ferramenta pronta:** `sustemporal annotation-export --freeze FREEZE_ID`,
  `prepare_annotation_sample` (`src/sustemporal/evaluation/annotation.py`) e `comparar_com_motor`.
- **Runbook:** `docs/runbooks/reproducao.md` §7.9; `docs/method/annotation.md` ("Execução").
- **Estado:** aberta (exige dados reais, G2 e congelamento)
- **Nota:** κ antes da adjudicação; comparar com o motor só depois de fechar a referência.

## 4. Engenharia

### EN-01 — Empacotamento e orquestração

- **Itens:** T01-1 (catalog/ e config/ fora do pacote instalável); T07-i15 (empacotamento de
  catalog/ e config/ no wheel); T01-2 (merge pelo MCP exige SUSTEMPORAL_PAPEL=orquestrador)
- **Ferramenta pronta:** `pyproject.toml` (alvo do hatch, só do orquestrador) e
  `.claude/hooks/bloquear_mcp_github.py` (`SUSTEMPORAL_PAPEL=orquestrador`).
- **Runbook:** — (decisão de orquestração; ver `docs/process/protocolo-sessao.md`, "Guardas
  automáticas").
- **Estado:** aberta; T01-2 é decisão humana do pesquisador
- **Nota:** O runbook de reprodução assume o clone com `uv sync`; o wheel não carrega catálogo nem
  configuração.

### EN-02 — Âncora de integridade dos registros append-only

- **Itens:** T02-5 (âncora do manifesto ao lado dele: apagar os dois não é detectado); T11-11
  (o registro de rodadas do congelamento não detecta truncamento do sufixo); T11-30 (arquivo de
  trava do registro fora do .gitignore e leitura sem a trava)
- **Ferramenta pronta:** `EstadoManifesto.cabeca_sha256`
  (`src/sustemporal/acquisition/manifest.py`) e `ler_registro`
  (`src/sustemporal/evaluation/freeze_registro.py`).
- **Runbook:** —
- **Estado:** aberta (T14 e execução)
- **Nota:** Registrar a cabeça no `RunResult` ou no congelamento; ver também ORQ-10.

### EN-03 — Canais e limites de aquisição

- **Itens:** T02-4 (canal HTTPS do FTP e portal de transferência não usados); T02-9 (prazo total por
  transferência fora de RuntimeConfig)
- **Ferramenta pronta:** `RuntimeConfig` (`src/sustemporal/contracts/config.py`) e `PRAZO_TOTAL` em
  `src/sustemporal/acquisition/transport.py`.
- **Runbook:** —
- **Estado:** aberta (depende de PQ-08)
- **Nota:** Os mesmos bytes por outro canal são a mesma versão.

### EN-04 — Unificar leitores DBC e classificação de erros da descompressão

- **Itens:** T02-10 (validação do DBC chama datasus_dbc direto); T06-6 (validação de DBC ainda chama
  datasus_dbc direto); T02-14 (saída anômala do filho da descompressão vira quarentena de conteúdo);
  T03-4 (truncamento classificado pelo texto do erro do datasus-dbc); T04-12 (zip corrompido: lista
  de exceções do zipfile); T04-16 (CRC divergente classificado pelo texto da mensagem)
- **Ferramenta pronta:** `src/sustemporal/ingest/dbc.py` e `descomprimir_limitado`
  (`src/sustemporal/acquisition/descompressao.py`).
- **Runbook:** —
- **Estado:** aberta
- **Nota:** A classificação por texto de mensagem (`end of input`, `Bad CRC-32`) depende da versão
  da biblioteca: reavaliar a cada atualização.

### EN-05 — Observação, integridade e seleção temporal

- **Itens:** T02-11 (mesmos bytes caracterizados de outro modo, integridade da observação); T06-5
  (UF da seleção vem de piloto.uf ou vigilancia.uf); T06-7 (motor importar criterio_da_regra e
  apagar a cópia); T06-10 (SnapshotSet da execução derivado das chaves do lote)
- **Ferramenta pronta:** `src/sustemporal/temporal/selector.py` (`criterio_da_regra`) e
  `src/sustemporal/temporal/lote.py` (`selecionar_lote`).
- **Runbook:** —
- **Estado:** aberta
- **Nota:** O seletor deve preferir a caracterização da observação selecionada.

### EN-06 — Leitura e normalização do SIA-PA: contratos, limites e sugestões

- **Itens:** T03-17 (tipar RegistroRotulo.contradicoes com o vocabulário fechado); T03-22 (caminho
  do conteúdo e janela entre resolução e leitura); T03-24 (prova de ausência de bytes após o fim
  DCL); T03-25 (sugestões da revisão independente do PR #11)
- **Ferramenta pronta:** `src/sustemporal/ingest/sia_pa.py`, `catalog/labels/sia_pa.yaml` e
  `src/sustemporal/evaluation/labels.py`.
- **Runbook:** —
- **Estado:** aberta (sugestões)
- **Nota:** T03-17 é proposta ao orquestrador: tipar `RegistroRotulo.contradicoes` em
  `contracts/records.py`.

### EN-07 — Esquemas canônicos e catálogo: promoções e tipos

- **Itens:** T05-14 (esquemas piloto_*.v1 fora de catalog/schemas/); T10-5 (esquema
  predicoes_baseline.v1 definido em código); T13-b2 (esquema valores_p3.v1 declarado em values.py);
  T04-13 (DECIMAL no verificador de tipos do motor)
- **Ferramenta pronta:** `carregar_esquema` (`src/sustemporal/rules/catalog.py`),
  `TABELAS_RELATORIO` (`src/sustemporal/reporting/report_publicacao.py`), `SCHEMA_PREDICOES`
  (`src/sustemporal/evaluation/baselines.py`) e `_TIPOS` em `src/sustemporal/evaluation/values.py`.
- **Runbook:** —
- **Estado:** parcial (esquemas promovidos a `catalog/schemas/` no PR #35; faltam trocar
  `SCHEMA_PREDICOES` por `carregar_esquema` e decidir o tipo esperado de DECIMAL no motor)
- **Nota:** `piloto_*.v1`, `valores_p3.v1` e `predicoes_baseline.v1` têm YAML em
  `catalog/schemas/` (T05-14 e T13-b2 fechados; T10-5 só no catálogo, a constante segue em
  `evaluation/baselines.py`). `tests/unit/test_catalogo_esquemas_emitidos.py` falha se um
  `schema_id` literal de `src/` ficar sem YAML. Abertos: trocar a constante (módulo da S5) e
  decidir o tipo esperado de colunas DECIMAL no motor (T04-13).

### EN-08 — SIGTAP e CNES: escolhas de ingestão a rever depois do G0

- **Itens:** T04-8 (tb_registro e o esquema sigtap_registro.v1); T04-11 (multiplicidade depois de
  remover duplicatas exatas); T04-15 (teste ponta a ponta até evaluate_rules com SIGTAP e CNES);
  T04-21 (agregação das linhas válidas por CNES e CBO); T04-22 (famílias SR e HB levantam
  FamiliaReservada); T04-23 (campos pessoais do PF lidos só para conferir o leiaute); T04-27
  (armazenamento lido em <raiz_dados>/raw); T04-28 (saída 0 com quarentena, ausência e família
  reservada)
- **Ferramenta pronta:** `src/sustemporal/ingest/sigtap.py`, `cnes.py`, `cnes_leitura.py` e
  `cli.py`.
- **Runbook:** —
- **Estado:** registrada (revisar no G0)
- **Nota:** Famílias SR e HB só ganham esquema quando o G0 as ativar; tabela de referência colapsa
  duplicata exata e conta a perda.

### EN-09 — Cobertura e recorte da ingestão: escolhas a rever

- **Itens:** T04-24 (semântica da matriz de cobertura); T04-26 (campos exigidos por família na
  cobertura); T04-30 (campos SIA-PA nulos não entram na cobertura); T04-32 (competência do SIA-PA
  vista pelos registros); T04-33 (partes do SIA-PA e o seletor); T04-34 (famílias auxiliares
  multipartes: a guarda é o seletor); T04-35 (recorte da ingestão por UF); T04-36 (republicação
  divergente do SIA-PA deixa a competência incompleta); T04-37 (um DatasetRef por artefato); T04-38
  (recorte por família, UF e corte de observação); T04-40 (incompletude via arquivo)
- **Ferramenta pronta:** `src/sustemporal/ingest/coverage.py` (`build_coverage`) e
  `src/sustemporal/ingest/cli.py`.
- **Runbook:** —
- **Estado:** registrada (revisar no G0)
- **Nota:** A cobertura nunca usa o mês vizinho; a decisão de base e de deslocamento é da política
  temporal.

### EN-10 — Relatório do piloto: escolhas a rever

- **Itens:** T05-7 (coorte derivada quando não há bloco coorte); T05-8 (políticas da seleção no
  relatório, B_PROC e B_ATEND); T05-9 (prioridade das classes de ausência); T05-13 (contrato do
  motivo sia_pa_incompleto); T05-15 (build_coverage sem o parâmetro familias); T05-17 (entrada sem
  cobertura.v1 é recusada); T05-18 (campos-chave da coorte fora de piloto_campos.v1)
- **Ferramenta pronta:** `src/sustemporal/reporting/report.py` (`build_pilot_report`) e
  `src/sustemporal/reporting/cli.py`.
- **Runbook:** —
- **Estado:** registrada (revisar no G0); T05-18 aberta
- **Nota:** Medir os campos-chave da coorte também antes das exclusões (ver ORQ-11).

### EN-11 — Motor SQL e validate (T07)

- **Itens:** T07-i11 (P2 do Codex adiados no validate --ingest, itens a, b, c e d); T07-i12
  (cobertura.v1 e integridade alimentam o NOT EXISTS); T07-i16 (linhagem da evidência de
  aplicabilidade no ExplanationBundle); T07-i17 (oráculo independente do §5: seleção, política e
  deslocamento); T07-i18 (evidência APLICABILIDADE grava cobertura=DISPONIVEL fixa); T07-i19
  (ausência com integridade diferente de OK sem motivo próprio)
- **Ferramenta pronta:** `src/sustemporal/rules/validate_ingest.py`, `src/sustemporal/rules/lote.py`
  e `src/sustemporal/rules/engine.py`.
- **Runbook:** —
- **Estado:** aberta
- **Nota:** ORQ-07 a ORQ-09, ORQ-13 e ORQ-20 também tratam do `validate --ingest`.

### EN-12 — Explicação e PROV (T08)

- **Itens:** T08-i4 (atividades de aquisição e transformação no PROV sem instantes); T08-i5
  (registro com código fora do padrão recusa a explicação); T08-i8 (integração com a seleção em
  lote); T08-i9 (reexecução de evidências por query_id, allowlist); T08-i10 (T09 consome
  ExplanationBundle); T08-i13 (ElementosProv incoerente em chamada direta, P2 do #24)
- **Ferramenta pronta:** `src/sustemporal/explanation/explain.py`, `evidence.py` e `prov.py`.
- **Runbook:** —
- **Estado:** aberta (T08-i13) e registrada
- **Nota:** Família nova no motor exige consulta nova na allowlist de evidência, senão a explicação
  é recusada.

### EN-13 — Contrafactuais (T09)

- **Itens:** T07-i20 (CNES ST no contexto do validate --ingest: duas escolhas conservadoras);
  T09-i9 (identidade do resultado inclui o mês do relógio, as-of); T09-i11 (operações dependem do
  CNES ST da competência); T09-i13 (revalidação restrita ao conjunto SIA-PA do contexto); T09-i14
  (competência aberta sem instante de observação); T09-i16 (search_counterfactuals sem contexto
  resolve os insumos; falta o instante da competência aberta)
- **Ferramenta pronta:** `src/sustemporal/explanation/counterfactual.py`,
  `counterfactual_contexto.py` e a CLI `sustemporal counterfactual`
  (`src/sustemporal/explanation/counterfactual_cli.py`); `CADASTROS_DO_CONTEXTO`
  (`src/sustemporal/rules/ingest_cadastros.py`).
- **Runbook:** —
- **Estado:** aberta (CNES ST multipartes: ORQ-27)
- **Nota:** Sem o CNES ST da competência no contexto, inclusão e reclassificação ficam
  inadmissíveis. O `validate --ingest` o grava desde o #34 quando o registro temporal e o corte o
  confirmam (T09-i8, fechado). Ver ORQ-04, ORQ-27 e ORQ-30.

### EN-14 — Coortes, classificador e congelamento (T10 e T11)

- **Itens:** T10-3 (fonte_por_artefato ainda não derivado do manifesto); T10-7 (aprovação parcial e
  DESCONHECIDO fora do ajuste)
- **Ferramenta pronta:** `build_splits` (`src/sustemporal/evaluation/split.py`) e `fit_baseline`
  (`src/sustemporal/evaluation/baselines.py`).
- **Runbook:** —
- **Estado:** aberta
- **Nota:** Desde o #29, `fit_baseline` em CONFIRMATORIO carrega o `FreezeManifest` do `freeze_id` e o
  confere antes de abrir qualquer arquivo (T10-8, fechado). `reproduce_etapas.derivar_protocolo`
  deriva o mapa `fonte_por_artefato` do manifesto de aquisição (fonte, UF, competência do arquivo e
  parte) para o fluxo pequeno e para o `reproduce`; a derivação na integração em lote (T10-3) segue
  aberta.

### EN-15 — Vigilância: comparação linha a linha das demais famílias

- **Itens:** T13-4 (famílias sem normalizador não comparadas linha a linha)
- **Ferramenta pronta:** `src/sustemporal/acquisition/watch.py` e `comparacao.py`.
- **Runbook:** —
- **Estado:** aberta
- **Nota:** Comparar por multiconjunto quando os normalizadores estiverem em uso.

### EN-16 — Harness de desempenho: etapas ainda não montadas

- **Itens:** T13-b5 (etapas de contrafactuais e métricas NAO_MEDIDO no harness)
- **Ferramenta pronta:** `src/sustemporal/evaluation/performance.py` (`etapa_pendente`).
- **Runbook:** —
- **Estado:** aberta
- **Nota:** Montar as etapas de `search_counterfactuals` e `evaluate_runs`, já em `main`.

### EN-17 — Anotação: integrações com o congelamento e o motor

- **Itens:** T12-i5 (prepare_annotation_sample usa split.particoes); T12-i6 (adaptador de
  avaliacoes.v1 para row_id e famílias do motor); T11-6 (causa fora de escopo vem de causas=,
  referência da anotação humana)
- **Ferramenta pronta:** `src/sustemporal/evaluation/annotation.py` e `annotation_cli.py`;
  `evaluate_runs` (`causas=`, `src/sustemporal/evaluation/metrics.py`).
- **Runbook:** —
- **Estado:** aberta
- **Nota:** A comparação recebe `row_id` e famílias do motor só depois da referência FECHADA.

### EN-18 — Parte B e entrega da T14

- **Itens:** T14-4 (README final do projeto); T14-10 (pacote de exemplos e relatório final);
  T14-12 (caminhos absolutos em DatasetRef e saída da reprodução em out novo); T14-13 (o reproduce
  só reproduz o exploratório); T08-i6 (DatasetRef.caminho absoluto: explicação depende dos mesmos
  caminhos)
- **Ferramenta pronta:** `sustemporal reproduce --freeze FREEZE_ID --offline`
  (`src/sustemporal/reporting/reproduce.py`, com `reproduce_comparacao.py`, `reproduce_etapas.py` e
  `reproduce_rede.py`) e o `reproducao.json` que ele grava.
- **Runbook:** `docs/runbooks/reproducao.md` §4.5 e §5.
- **Estado:** aberta (README e relatório final; confirmatório e caminhos relativos)
- **Nota:** O `reproduce` resolve o manifesto pelo `freeze_id`, compara por hash lógico sem o
  `run_id`, grava em `out` novo e recusa o confirmatório (ver PQ-11 e a alegação AL-22).

### EN-19 — Identidade das execuções: run_id e versão do código

- **Itens:** T14-11 (decisão: run_id do validate e a versão do código); T07-i21 (o run_id do
  --ingest depende dos caminhos da config)
- **Ferramenta pronta:** `evaluate_rules` (`src/sustemporal/rules/engine.py`), que compara o
  `codigo` do `run_result.json` existente com `versao_codigo` (`src/sustemporal/runtime_info.py`).
- **Runbook:** —
- **Estado:** fechada (opção (b): o motor recusa regravar `out/<run_id>` com outro código; PR #36)
- **Nota:** Ver ORQ-05 e `docs/pendencias/T14.md` item 11; o método está em
  `docs/method/model.md` §7 ("Execução imutável"). O `reproduce` compara as saídas sem a
  coluna `run_id` (ORQ-29).

### EN-20 — Conferência das execuções e da cobertura no `evaluate` (T11)

- **Itens:** T11-24 (cobertura dos resultados: extras sem conferir a partição); T11-25
  (`evaluate --exploratory` escolhe execuções pelo config_hash e não aceita --runs); T11-28
  (entrada_validacao.json ligada ao RunResult só por SnapshotSet e conjuntos não populacionais);
  T11-29 (execucao_ambigua recusa a avaliação inteira)
- **Ferramenta pronta:** `evaluate_runs` (`src/sustemporal/evaluation/metrics.py`) e
  `sustemporal evaluate` (`src/sustemporal/evaluation/cli.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §4.5 e §6.
- **Estado:** aberta
- **Nota:** O exploratório registra as contagens nas notas e ignora a execução ilegível; o
  confirmatório recusa. Decisões do S5 e do orquestrador (donos de `evaluation/`).

### EN-21 — Relatório, split e retomada do `evaluate` (T11)

- **Itens:** T11-19 (retomada após falha entre gravar o relatório e registrar a rodada); T11-20
  (estratos por estabelecimento: relatório grande e razões instáveis); T11-21 (split_id sem
  validação de conteúdo)
- **Ferramenta pronta:** `sustemporal evaluate`, `EvaluationReport.tabelas` e `SplitManifest`
  (`src/sustemporal/contracts/experiment.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §7.8 (escala).
- **Estado:** aberta
- **Nota:** Ver ORQ-15 e ORQ-22. O `reproduce` compara o `split_id` refeito com o congelado.

### EN-22 — Preparo do protocolo e catálogos congelados (T11 e T14)

- **Itens:** T11-8 (convenção de entradas da CLI e lista completa de catálogos congelados); T11-27
  (insumos congelados preparados à mão, sem comando); T14-14 (nenhum comando prepara união,
  rótulos, partições e insumos)
- **Ferramenta pronta:** `src/sustemporal/reporting/reproduce_etapas.py` (`janela_do_ingest`,
  `derivar_protocolo` e `validar_janela`) e `build_splits` (`src/sustemporal/evaluation/split.py`).
- **Runbook:** `docs/runbooks/reproducao.md` §4.5 e §6 ("Entradas do `freeze` e do `evaluate`").
- **Estado:** aberta (decisão do orquestrador: `src/sustemporal/cli.py` é dele)
- **Nota:** As etapas valem para o fluxo pequeno e para o `reproduce`; com dados reais falta o
  comando e a conferência dos insumos contra o registro temporal e o corte congelados.

### EN-23 — Ablações sobre o `evaluate_runs` (T11 e T13)

- **Itens:** T11-9 (ablações de CNES ou SIGTAP ficam fora do PR do T11)
- **Ferramenta pronta:** `evaluate_runs` e `src/sustemporal/evaluation/ablation.py`.
- **Runbook:** —
- **Estado:** aberta
- **Nota:** Reusar `evaluate_runs` com as execuções de ablação (S8, T13).

### EN-24 — Padrões relativos ao diretório de trabalho

- **Itens:** T14-15 (padrões relativos ao cwd: selecao_versoes.yaml, config/splits.yaml,
  experiments/decisions e config/runtime.yaml)
- **Ferramenta pronta:** `temporal/lote.py`, `evaluation/split.py`, `gates.py` e `cli.py` (em
  `src/sustemporal/`); o teste `tests/integration/test_reproduce_offline.py` roda de um diretório
  com cópias de `catalog/` e `config/`.
- **Runbook:** `docs/runbooks/reproducao.md` §5.3.
- **Estado:** aberta (donos dos módulos e orquestrador)
- **Nota:** Resolver a partir do pacote ou de um campo do `RunConfig`.

## 5. Pendências de engenharia registradas pelo orquestrador

Itens da nota do orquestrador para a S9, todos abertos, salvo ORQ-02 (esquemas promovidos no PR
#35), ORQ-05 (execução imutável, PR #36), ORQ-21, ORQ-23, ORQ-24 e ORQ-25 (resolvidos no #34, com
o que resta nos itens novos), ORQ-28 (resolvido no #29), ORQ-26, ORQ-29 e ORQ-31 (tratados na
parte B da T14) e ORQ-30 (escolha aceita). Cada linha traz a tarefa, o PR de origem, a ferramenta pronta e o passo do runbook (`—`
quando não há passo: é mudança de código). Os números de comentário e de P2 são os do GitHub
nos PRs indicados.

| ID | Tarefa | PR de origem | Pendência | Ferramenta pronta | Runbook |
|---|---|---|---|---|---|
| ORQ-01 | T13b | #25 (comentário 4179959486) | Comparar, por `row_id`, o conjunto de regras avaliadas com o catálogo congelado do run antes de aceitar o agregado (endurecimento contra saída forjada coerente com o `RunResult`). Recusado no #25 por estar fora do modelo de ameaça pré-G0. | `summarize_values` (`src/sustemporal/evaluation/values.py`) e `carregar_regras` (`src/sustemporal/rules/catalog.py`) | — |
| ORQ-02 | T05 | #31 (comentário 4179930704) | Promover os esquemas `piloto_*.v1` a `catalog/schemas/` (depende do mapa de propriedade; junto com `valores_p3.v1` da S8, pendência b2 de T13). Feita no PR #35 (ver EN-07). | `carregar_esquema` (`src/sustemporal/rules/catalog.py`) e `TABELAS_RELATORIO` (`src/sustemporal/reporting/report_publicacao.py`) | — |
| ORQ-03 | T07/T05 | #31 | Alinhar o `validate --ingest` ao instantâneo do manifesto gravado pelo `ingest` (`manifesto_lido.json`, #31), como o `pilot-report`. | `manifesto_lido.json` gravado pelo `ingest` e a leitura dele em `src/sustemporal/reporting/cli.py` | `docs/runbooks/piloto_local.md` §3 |
| ORQ-04 | T09/T08 | #28 | Consolidar `_publicar` e `_validar_argumentos` dos CLIs `explain` e `counterfactual` num helper comum (duplicação apontada pelo SonarCloud). | `_publicar` e `_validar_argumentos` em `src/sustemporal/explanation/cli.py` e em `src/sustemporal/explanation/counterfactual_cli.py` | — |
| ORQ-05 | T07 | #27 (a nota não cita o número; é o PR do `validate --ingest`) | O `run_id` do `validate` não inclui a versão do código; o motor grava em `outputs/runs/<run_id>/` com `exist_ok=True`. Decidir (T14) entre incluir o código no `run_id` ou recusar a sobrescrita de run com código diferente (opções e preferência em `docs/pendencias/T14.md`, item 11). Resolvida no PR #36 (ver EN-19): o motor recusa regravar `out/<run_id>` quando o `codigo` do `run_result.json` existente difere ou o arquivo é ilegível. | `versao_codigo` (`src/sustemporal/runtime_info.py`) e o `run_result.json` de cada run | — |
| ORQ-06 | T01 | #32 (comentário 4180023928) | `versao_codigo`: passar `--ignore-submodules=none` na listagem de caminhos alterados; conferir `S_ISREG` antes de abrir (um FIFO no lugar de arquivo rastreado travaria); caminho sob diretório rastreado que virou link simbólico é lido através do link. | `versao_codigo` (`src/sustemporal/runtime_info.py`) e os testes de `diff_sha256` | — |
| ORQ-07 | T07 | #27 (comentário 4180014336) | A igualdade estrita entre as partes da pasta e as partes selecionadas recusa (saída 2) também quando a ingestão marcou a competência com `sia_pa_incompleto` (parte com normalização falha). Refinamento: a marca isentar a parte ausente, registrando a incompletude da população e mantendo as células INSUFICIENTE, em vez de recusar a execução inteira. | `marcas_sia_pa_incompleto` (`src/sustemporal/ingest/coverage.py`) e `src/sustemporal/rules/validate_ingest.py` | — |
| ORQ-08 | T07 | #27 (a nota não cita o número) | Competência do piloto sem nenhum artefato na pasta não passa pelo guard de partes; hoje fica visível só pela cobertura recalculada (`sia_pa_ausente`). Conferir também as competências do piloto ausentes da pasta contra o seletor. | `src/sustemporal/rules/validate_ingest.py` e `selecionar_lote` (`src/sustemporal/temporal/lote.py`) | — |
| ORQ-09 | T07 | #27 | O caminho direto `validate --entrada` (`exigir_sem_deletados`) ainda aceita produção sem a coluna `deletado` ou com `deletado` nulo (os cenários do motor em `tests/fixtures/regras_cenario.py` não trazem a coluna); estender a conformidade de esquema do `--ingest` (`rules/ingest_conformidade.py`) ao caminho direto. | `exigir_sem_deletados` (`src/sustemporal/rules/ingest.py`) e `src/sustemporal/rules/ingest_conformidade.py` | — |
| ORQ-10 | T11 | #29 (comentário 4180171135) | O registro append-only do congelamento não detecta truncamento do sufixo; mitigação atual: versionamento em Git; ancorar a cabeça (contagem e hash) em local confiável. | `EstadoManifesto.cabeca_sha256` (`src/sustemporal/acquisition/manifest.py`) como modelo de âncora | — |
| ORQ-11 | T05 | #31 (comentário 4180119200) | A ausência dos campos-chave da coorte (`competencia_processamento`, `municipio_estabelecimento`, `instrumento`) aparece só nas exclusões por motivo (`piloto_exclusoes.v1`); medir também sobre a população antes das exclusões. | `piloto_exclusoes.v1` e `piloto_campos.v1` (`sustemporal pilot-report`) | `docs/runbooks/piloto_local.md` §3 |
| ORQ-12 | T07/T04 | #27 | O catálogo padrão não declara `partes_esperadas` do SIA-PA (SP tem partes a, b, c e d). Enquanto o pesquisador não declarar as partes no catálogo, a competência multipartes fica INSUFICIENTE e as linhas dependentes saem INCONCLUSIVO, no `ingest` e no `validate`. Pôr no runbook do piloto. | `catalog/sources.yaml` (`partes_esperadas`) e `partes_esperadas_do_catalogo` (`src/sustemporal/temporal/selector.py`) | `docs/runbooks/reproducao.md` §7.2 (o `piloto_local.md` é da S3 e ainda não traz o passo) |
| ORQ-13 | T07 | #27 | A marca derivada do seletor cobre só INCOMPLETA. EM_QUARENTENA e AUSENTE dependem da marca da ingestão (`marcar_tentativas_sem_versao`); uma pasta com cobertura sem marca ficaria sem essa proteção. | `marcar_tentativas_sem_versao` (`src/sustemporal/ingest/cli.py`) e `src/sustemporal/rules/validate_ingest.py` | — |
| ORQ-14 | T05 | #31 | O P2 4180359787 (`observacoes=None` tratada como `ausente_sem_tentativa`) foi pedido junto com o P1 de republicações. Se não entrar, registrar. | `build_pilot_report` (`src/sustemporal/reporting/report.py`) e `piloto_inconclusivos.v1` | — |
| ORQ-15 | T11 | #29 | Retomada após falha entre gravar o relatório e registrar a rodada (P2 4180340957). | `sustemporal evaluate` e o registro de rodadas do T11 (no PR #29) | — |
| ORQ-16 | T05 | #31 (P2 4180502304) | Derivar `sia_pa_presente_em` também das chaves dos datasets e artefatos ingeridos. Hoje um SIA-PA com zero linhas, ou só com linhas deletadas, vira `sia_pa_ausente`. | `build_coverage` (`src/sustemporal/ingest/coverage.py`) e `src/sustemporal/reporting/report_cobertura.py` | — |
| ORQ-17 | T05 | #31 (P2 4180502308) | Validar `datasets.jsonl` em `_ultima_ingestao`. Hoje um índice truncado ou malformado escapa como traceback, sem `ConfigInvalida`; o certo é cair para a execução válida anterior. | `_ultima_ingestao` (`src/sustemporal/reporting/cli.py`) | `docs/runbooks/piloto_local.md` §3 |
| ORQ-18 | T05 | #31 (P2 4180502312) | O `report_id` deve vir dos ids das tabelas publicadas, ou incluir o hash do mapa de observações e do conteúdo do arquivo de território. | `build_pilot_report` (`src/sustemporal/reporting/report.py`) | — |
| ORQ-19 | T05 | #31 | `build_pilot_report` chamada como biblioteca sem `chaves` não detecta versões concorrentes. A CLI sempre passa `chaves`. | `sustemporal pilot-report` (a CLI passa `chaves`) | `docs/runbooks/piloto_local.md` §3 |
| ORQ-20 | T07 | #27 (P2 4180512815) | Normalizar as colunas anuláveis ausentes (`instrumento`, `competencia_atendimento`) antes do recálculo da cobertura no `validate --ingest`, ou conferir antes de `_gravar`. Hoje o resultado são saídas parciais. | `src/sustemporal/rules/validate_ingest.py` e `src/sustemporal/rules/ingest_conformidade.py` | — |
| ORQ-21 | T07/T11 | #27 e #29 (integração; a nota não cita um PR) | **Resolvida no #34**: o `validate` grava em `<raiz_saidas>/runs` nos dois modos (`--saida` desvia a gravação) e o `explain` e o `counterfactual` leem só ali, pelo leitor comum. A troca no `evaluate` (`raiz_execucoes(config)`) entrou com o #29 (ORQ-28). Texto original: o `validate` gravava por padrão em `<raiz_saidas>/validacao` (modo `--entrada`) e o `evaluate` procura execuções em `<raiz_saidas>/runs`. | `raiz_execucoes` (`src/sustemporal/execucoes.py`) e `validate --saida` (`src/sustemporal/rules/cli.py`) | `docs/runbooks/reproducao.md` §6 |
| ORQ-22 | T11 | #29 | Pendências #20 (relatório grande e razões instáveis com muitos estabelecimentos no teste de escala de SP; sem intervalo por estrato) e #21 (`split_id` sem validação de conteúdo no contrato `SplitManifest`). | `evaluate_runs` (`src/sustemporal/evaluation/metrics.py`, T11 no PR #29) e `SplitManifest` (`src/sustemporal/contracts/experiment.py`) | `docs/runbooks/reproducao.md` §7.8 (escala) |
| ORQ-23 | T09 | #28 (P2 4182986818) | **Resolvida no #34**: o `counterfactual` lê pelo leitor comum e só procura em `<raiz_saidas>/runs`; uma execução gravada com `validate --saida <dir>` não é achada, por desenho (documentado no runbook). Texto original: o `counterfactual` procurava execuções só em `<raiz_saidas>/runs` e `<raiz_saidas>/validacao` e não achava as gravadas com `--saida`. | `ler_execucao` (`src/sustemporal/execucoes.py`) | `docs/runbooks/reproducao.md` §6 |
| ORQ-24 | T07/T09 | #28 | **Resolvida no #34**: o `validate --ingest` grava o CNES ST no contexto da execução quando o registro temporal e o corte de observação o confirmam (`CADASTROS_DO_CONTEXTO`); sem ele a busca segue `SEM_OPERACAO_ADMISSIVEL`. O CNES ST multipartes completo resta (ORQ-27). Texto original: o `validate --ingest` não gravava o CNES ST no contexto e a busca contrafactual sobre execuções `--ingest` saía vazia. | `CADASTROS_DO_CONTEXTO` (`src/sustemporal/rules/ingest_cadastros.py`) e `entrada_validacao.json` | `docs/runbooks/reproducao.md` §4.4 |
| ORQ-25 | T08 | #28 | **Resolvida no #34**: `explain` e `counterfactual` leem pelo leitor comum, e um `run_result.json` que não é UTF-8 sai com 2 nos dois. Texto original: `explanation/cli.py::localizar_execucao` deixava escapar `UnicodeDecodeError`. | `ler_execucao` (`src/sustemporal/execucoes.py`) | — |
| ORQ-26 | T14 | #33 (P2 4183881393) | **Feita na parte B**: `PROIBIDAS` ganha a chave `altera competência encerrada`, com casos de afirmação e de redação alternativa como regressão (P2 4183881393 do #33). | `PROIBIDAS` (`tests/unit/test_alegacoes.py`) e `docs/method/claims.md` | `docs/runbooks/reproducao.md` §3 |
| ORQ-27 | T09 | #34 (P2 4184603142) | CNES ST multipartes completo no contexto: `_artefato` exige candidato único, então as operações dependentes do CNES saem inadmissíveis com um CNES ST em várias partes. Tratar a seleção completa como uma versão lógica editável. | `_artefato` (`src/sustemporal/explanation/counterfactual_sobreposicao.py`) e `CADASTROS_DO_CONTEXTO` (`src/sustemporal/rules/ingest_cadastros.py`) | — |
| ORQ-28 | Integração | #34 (PR final do orquestrador) | **Resolvida no #29**: `executar_evaluate` procura as execuções em `raiz_execucoes(config)`. Texto original: depois do merge do #29, trocar `raiz / "runs"` em `evaluation/cli.py::executar_evaluate` por `raiz_execucoes(config)`. | `raiz_execucoes` (`src/sustemporal/execucoes.py`) e `executar_evaluate` (`src/sustemporal/evaluation/cli.py`) | `docs/runbooks/reproducao.md` §6 |
| ORQ-29 | T07/T14 | #34 | O `run_id` do `--ingest` depende dos caminhos da config (`piloto.territorio`, `catalogos`), o que afeta a comparação entre ambientes no `reproduce`. **Tratada na parte B**: o `reproduce` compara por hash lógico, contagens e métricas e não usa o `run_id` (as saídas se comparam sem essa coluna). A identidade do `run_id` segue em ORQ-05 e T07-i21. | `comparar_saida` (`src/sustemporal/reporting/reproduce_comparacao.py`) | `docs/runbooks/reproducao.md` §5.2 |
| ORQ-30 | T07 | #34 | Escolhas conservadoras aceitas pelo orquestrador: o cadastro do contexto só entra com a seleção SELECIONADA, conferido por competência (duas versões do CNES ST da mesma competência tiram a competência do contexto), e o motivo do cadastro ignorado vai só para o log (`cadastro_do_contexto_ignorado`). | `CADASTROS_DO_CONTEXTO` (`src/sustemporal/rules/ingest_cadastros.py`) | — |
| ORQ-31 | T14 | #34 (a nota não cita o número; vem das mudanças de T07, T08 e T09) | **Feita na parte B**: reconsolidar T07, T08 e T09 em `docs/PENDENCIAS.md` (o teste avisa `pendencia_nao_reconsolidada`); a base inclui agora T10, T11 e T14 atualizados. | `tests/unit/test_pendencias.py` | `docs/runbooks/reproducao.md` §3 |
| ORQ-32 | Catálogo | #35 | `SCHEMA_PREDICOES` (`evaluation/baselines.py`, S5) segue como constante em código; o YAML em `catalog/schemas/` tem a mesma estrutura, conferida por teste. Trocar a constante por `carregar_esquema` (EN-07, parcial). | `carregar_esquema` (`src/sustemporal/rules/catalog.py`) e `SCHEMA_PREDICOES` (`src/sustemporal/evaluation/baselines.py`) | — |
| ORQ-33 | T07/T05 | #27 e #31 (a nota não cita o número) | O `validate --ingest` ainda constrói o registro temporal do manifesto atual, e não do `manifesto_lido.json` da ingestão; hoje o descompasso só leva a recusa, nunca a resultado errado. Alinhar ao `pilot-report` (ver ORQ-03). | `manifesto_lido.json` gravado pelo `ingest` e `src/sustemporal/rules/validate_ingest.py` | `docs/runbooks/piloto_local.md` §3 |

## 6. Fechadas, aceitas ou resolvidas (histórico)

### FE-01 — Corrigidas ou resolvidas, com teste de regressão

- **Itens:** T02-i1 (larguras dos descritores DBF somando R − 1, corrigida); T02-i2 (4 bytes
  pós-cabeçalho do DBC no manifesto, corrigida); T02-i3 (IncompleteRead e HTTPException, corrigida);
  T02-i4 (filho da descompressão gravava .pyc truncado, corrigida); T03-10 (fidelidade com cabeçalho
  divergente, corrigido); T03-18 (origem dos dados SINTETICO por padrão, resolvido); T03-26 (P2 do
  Codex sobre o perfil, resolvidos); T04-39 (território no relatório do piloto, resolvido); T04-41
  (P2 do PR #21 resolvidos no PR3); T06-9 (intervalos() quebra em NAO_ENCONTRADO, fechada); T06-11
  (INTERROMPIDO com bytes não cai em AUSENTE, fechada); T07-i10 (validate --ingest lê a pasta do
  ingest, resolvido); T08-i11 (OSError ao publicar falha.json, resolvido); T08-i12 (registro fora do
  sia_pa.v1 recusado, resolvido); T09-i7 (CLI do counterfactual lê entrada_validacao.json, resolvido
  no #27 e testado no #28); T09-i8 (validate --ingest grava o CNES ST no contexto quando o registro
  e o corte o confirmam, resolvido no #34); T09-i10 (explain e counterfactual leem pelo leitor
  comum, resolvido no #34); T09-i17 (precondição fora das admitidas pelo op_id é recusada, resolvido
  no PR2); T12-i7 (rótulos que não cobrem a partição, resolvido); T13-5 (comparação que não
  normaliza vira INCONCLUSIVO, fechada); T13-8 (listagem ilegível e revisão só em deletadas,
  fechada); T13-b3 (rótulo contraditório no denominador da P3, fechada); T10-8 (fit_baseline em CONFIRMATORIO confere o FreezeManifest, fechada no PR2 do
  T11); T10-9 (coorte esparsa com partições vazias, fechada); T10-10 (coluna de origem repetida
  recusada, fechada); T11-10 (evaluate aceita --corrige e --declaracao, fechada); T11-12 (resultado
  duplicado do mesmo row_id, fechada); T11-13 (política resolvida na entrada_validacao.json,
  fechada); T11-14 (insumos das execuções de regras no manifesto, fechada); T11-16 (bootstrap do
  manifesto no confirmatório, fechada); T11-26 (integridade na entrada congelada, fechada)
- **Ferramenta pronta:** os testes dos PRs citados em cada arquivo de `docs/pendencias/`.
- **Runbook:** —
- **Estado:** fechada
- **Nota:** Ficam aqui só para a consolidação não perder o histórico.

### FE-02 — Aceitas ou integradas

- **Itens:** T01-3 (brechas restantes da guarda do Bash, aceitas); T07-i9 (integração com a seleção
  em lote, integrado)
- **Ferramenta pronta:** `.claude/hooks/bloquear_push_perigoso.py` e `.githooks/pre-push` (segunda
  camada); `src/sustemporal/rules/lote.py::avaliar_com_registro`.
- **Runbook:** —
- **Estado:** aceita ou integrada
- **Nota:** A guarda do Bash protege contra acidente; o `pre-push` é a segunda camada.

### FE-03 — Entregas da parte B da T14

- **Itens:** T14-1 (reproduce e executar_reproduce); T14-2 (teste ponta a ponta offline pela CLI);
  T14-3 (runbook, claims e reconsolidação das pendências)
- **Ferramenta pronta:** `sustemporal reproduce` e `tests/integration/test_reproduce_offline.py`.
- **Runbook:** `docs/runbooks/reproducao.md` §4.5 e §5.
- **Estado:** fechada
- **Nota:** O que a parte B deixou aberto está em EN-18, EN-22 e EN-24.

## Base da consolidação

Itens e SHA-256 de cada arquivo de `docs/pendencias/` na data da consolidação. Enquanto o arquivo
for o mesmo, o teste exige que os itens dele sejam exatamente estes.

| Arquivo | Itens | Total | SHA-256 |
|---|---|---|---|
| T01 | 1-3 | 3 | 90caf7eaba5b8cc5b5a19ef41709040351b016484fa0eece1afdde3d25e02c94 |
| T02 | 1-14, i1-i4 | 18 | c6675eef2165d854ebdd1b47858e51b9f96a225cd98750d00ec546732057499c |
| T03 | 1-26 | 26 | 96985a43e3007b4a83405b71ca534306b7f07971af1a31fda453e617e8c9efe6 |
| T04 | 1-41 | 41 | 4f8f5c22697aebf8353393237c39c5937cd45b92ea05b00fc30a8abe0f59cf08 |
| T05 | 1-20 | 20 | 7644b9cbf2147643a7b670bbbdb2f99b50f5abc0696aa73595867b81aa11423d |
| T06 | 1-11 | 11 | a2455e84a8448014a82fb5f3d590841666ec9cce32dbcc9c2be4552f079ac507 |
| T07 | i1-i21 | 21 | 05f05372f5129f16540a00076f07c38748c700f5e165c93c3787adfc5b0d3b5e |
| T08 | i1-i13 | 13 | 99e9ab502bd9e767bcd3163b954dd7fd7bf86a03bfa1bae7d7bd9a888d245af3 |
| T09 | i1-i18 | 18 | 5c1cd767168e80543a75299aee2349ae0076f0a3056f099fe430ac8ea767c7a6 |
| T10 | 1-10 | 10 | 7a8463fc7a1040d43b621c45f97bdb4fb2c2502979d33532807fbc53c49abbf4 |
| T11 | 1-30 | 30 | b12f79f362d973e24a411a6726e201c5a5d6c06627dac5dd10bbabe96a3fd00a |
| T12 | i1-i7 | 7 | f6454780722eb379be317e9853861ef3bbf5ca3f8889802fcfa48f35ada1543c |
| T13 | 1-6, 8, b1-b5 | 12 | 73d222a03774e97c9698daad4678de33e52906d918061b7b3ba751f12fd0ba15 |
| T14 | 1-15 | 15 | 3682caca4ee3f69e137c1bbcadb1dcc99b9830e3d6255e0cd707648d11de3e48 |
