# Observabilidade do piloto (T05)

Método do relatório do piloto (`sustemporal pilot-report`, `reporting/report.py`). Este documento
descreve **o que se mede e como**; não traz resultado. Nenhum dado real foi processado neste
repositório. O relatório gerado com fixtures é `SINTETICO`, fica exploratório e traz o aviso
`dados_sinteticos_exploratorio`.

## Pergunta

O que as fontes públicas permitem observar no DRS XI, por competência de processamento, para as
famílias de regras candidatas (`CANDIDATA_PRE_G0`)? O piloto não estima desempenho de
classificador e não exige ganho positivo. Ele subsidia a decisão humana G0
(`experiments/decisions/MODELO_G0.yaml`).

## Entradas

- A execução mais recente do `ingest` (`<raiz_saidas>/ingest/execucao_*/datasets.jsonl`): um
  `sia_pa.v1` por versão de conteúdo, os auxiliares (CNES, SIGTAP) e a `cobertura.v1`.
- O manifesto de aquisição (`<raiz_manifestos>/aquisicao.jsonl`), lido pelo registro temporal.
- A coorte: `coorte` da configuração ou, sem ela, a derivada do `piloto` (UF, território e o
  intervalo entre a menor e a maior competência de processamento pedida).

Os conjuntos são conferidos contra o `DatasetRef` (estrutura, contagem e hash lógico) antes de
qualquer contagem. Conjuntos de origens diferentes (`SINTETICO` e `REAL`) são recusados.

A `cobertura.v1` é obrigatória. Sem ela o relatório recusa a entrada (`ConfigInvalida`
`relatorio_sem_cobertura`, saída 2 pela CLI) e não publica nada: uma `piloto_disponibilidade.v1`
vazia seria lida como resultado, e o consumidor do G0 não a distinguiria de evidência ausente.

## Recorte e reconciliação

Cada linha física do SIA-PA recebe no máximo um motivo de exclusão, na ordem:

| Motivo | Condição |
|---|---|
| `deletado` | marcador de exclusão do DBF |
| `municipio_estabelecimento_ausente` | município do estabelecimento nulo após a normalização |
| `fora_do_territorio` | município fora de `municipios_ibge6` do território da coorte |
| `competencia_processamento_ausente` | competência de processamento nula |
| `fora_do_intervalo_da_coorte` | competência de processamento fora de `[inicio, fim]` |
| `instrumento_fora_da_coorte` | coorte com `instrumentos` e instrumento fora da lista ou nulo |

O critério geográfico é o município do estabelecimento (`criterio_geografico` da coorte). A
pertença fixa ou histórica (`pertenca`) segue `A_DEFINIR` e fica citada na nota
`recorte_territorial`. Incluídas mais excluídas somam as linhas físicas dos conjuntos canônicos
(`fracao_registros_incluidos`, numerador = incluídas, denominador = físicas).

## Tabelas

Todas sobre as linhas incluídas, gravadas em Parquet com `DatasetRef` (hash lógico; linhagem: os
artefatos das entradas):

| Esquema | Conteúdo |
|---|---|
| `piloto_contagens.v1` | linhas por competência de processamento, instrumento e estabelecimento (CNES) |
| `piloto_exclusoes.v1` | linhas excluídas por motivo |
| `piloto_campos.v1` | ausentes e denominador por campo exigido pelas famílias e pelo G0 |
| `piloto_defasagem.v1` | linhas por defasagem em meses (processamento − atendimento); nula quando falta uma |
| `piloto_rotulos.v1` | `ANTES`: PA_INDICA bruto; `DEPOIS`: rótulo do codebook; aprovações incluídas |
| `piloto_inconclusivos.v1` | classe e linhas da seleção por regra, fonte, base e estado |
| `piloto_disponibilidade.v1` | a cobertura recalculada (abaixo) no intervalo e nos instrumentos da coorte |

Os rótulos aqui servem só para descrever a distribuição antes e depois do pré-processamento. O
classificador nunca recebe rótulo, campos de erro nem quantidades ou valores aprovados.

### Campos verificados

`piloto_campos.v1` e a razão `taxa_ausencia_campo` (um estrato por campo) contam o valor nulo sobre
as linhas incluídas, com numerador e denominador. Os campos são os que as famílias exigem (`cnes`,
`municipio_estabelecimento`, as duas competências, `procedimento`, `instrumento`, `cbo`) e os que o
plano manda verificar antes do G0: `quantidade_apresentada`, `quantidade_aprovada`,
`valor_apresentado`, `valor_aprovado`, `pa_indica` e os campos de erro `pa_codoco`, `pa_flqt` e
`pa_fler`. Campo de erro entra só nessa tabela de observabilidade, nunca em contagem nem em atributo.

Nos campos normalizados, nulo é ausência, vazio ou valor inválido (o motivo fica no conjunto
canônico). Em `pa_indica` e nos de erro, sem normalização, nulo é a coluna fora do arquivo; texto em
branco é valor lido e não conta como ausente, pois o domínio deles é desconhecido
(`docs/references/inventario_campos.md`). O leiaute atual os exige: arquivo sem a coluna vai para
`QUARENTENA_LEIAUTE` e aparece como `sia_pa_incompleto` na disponibilidade, não nesta tabela; a taxa
de coluna ausente só vale para leiaute que os declare opcionais depois da conferência com cabeçalhos
reais.

## Disponibilidade das tabelas

A cobertura da ingestão é estadual: um registro de outro município com atendimento nulo deixaria a
célula INSUFICIENTE para todo o DRS XI. O relatório publica um `sia_pa.v1` só com as linhas
incluídas (a mesma população dos denominadores) e recalcula a `cobertura.v1` com o
`build_coverage` público, os mesmos auxiliares e as competências da cobertura da ingestão no
intervalo da coorte. As marcas `sia_pa_incompleto competencia=… motivo=…` da ingestão (lidas por
`marcas_sia_pa_incompleto`) continuam valendo. A cobertura recalculada entra nas tabelas do
relatório. É o mesmo recálculo que o `validate --ingest` (#27) faz.

Competência com linha de produção nos conjuntos `sia_pa.v1` da ingestão (ao menos uma linha não
deletada com aquela competência de processamento) e nenhuma linha incluída (todas fora do
território, do intervalo ou dos instrumentos) não vira fonte ausente: a célula fica INSUFICIENTE
com `populacao_vazia_no_recorte competencia=…` (`build_coverage(..., sia_pa_presente_em=...)`). É
limitação amostral do recorte, não ausência estrutural; as exclusões ficam em
`piloto_exclusoes.v1`.

A presença sai dos conjuntos ingeridos, nunca do texto do motivo da cobertura. Competência sem
conjunto legível (arquivo ausente, truncado ou em quarentena) continua AUSENTE, com o motivo
original: `sia_pa_incompleto competencia=…; sia_pa_ausente competencia=…`.

## Instantâneo do manifesto

O `ingest` grava `manifesto_lido.json` (número de linhas e hash encadeado da última linha do
manifesto que leu). O `pilot-report` monta o registro temporal só com esse prefixo e confere o
hash: versão obtida depois da ingestão não entra na seleção, então seleção e disponibilidade
descrevem o mesmo retrato. Posição ausente (pasta de ingestão antiga), além do manifesto atual ou
com hash divergente (manifesto reescrito) recusa a execução (saída 2), nunca cai no manifesto
atual.

## Inconclusivos

A seleção temporal em lote (`selecao_versoes.v1`) roda para as políticas `B_PROC` e `B_ATEND`
(M_TEMP segue `NAO_RESOLVIDA` até o G0). Cada linha da seleção de um registro incluído entra no
denominador do estrato `regra|fonte|base` (`taxa_inconclusivo`). As classes:

| Classe | Estado da seleção e observações citadas |
|---|---|
| `selecionada` | `SELECIONADA` (não é inconclusiva) |
| `ausente_nao_encontrado_na_listagem` | `AUSENTE` com observação `NAO_ENCONTRADO` |
| `ausente_tentativa_sem_bytes` | `AUSENTE` com `FALHA_TRANSPORTE`, `RECUSADO_OFFLINE`, `INTERROMPIDO` ou `FALHA_ARMAZENAMENTO` |
| `ausente_sem_tentativa` | `AUSENTE` sem observação |
| `em_quarentena_<motivo>` | `EM_QUARENTENA` com o motivo do seletor (`conteudo_em_quarentena`, `falha_de_coleta_com_bytes`, `observacao_integra_sem_versao`) |
| `incompleta`, `ambigua`, `fora_do_corte`, `nao_resolvida` | o estado da seleção |

Quando a mesma seleção cita `NAO_ENCONTRADO` e uma tentativa sem bytes, vale a primeira linha da
tabela. Tentativa sem bytes e quarentena por falha de coleta são falha de coleta, não ausência da
fonte: refazem-se antes do G0.

## Limitação amostral × ausência estrutural

O relatório não decide; separa os sinais com denominadores:

- **limitação amostral**: fonte e campo existem, mas o estrato tem poucos registros incluídos;
- **ausência estrutural**: fonte, campo ou versão não existe publicamente (classe
  `ausente_nao_encontrado_na_listagem` persistente, campo sempre ausente, cobertura `AUSENTE` em
  todas as competências).

## Limites

- Relatório sempre `EXPLORATORIO`; não é decisão G0 e não libera portão (nota `pre_g0_exploratorio`).
- Leiautes `A_CONFIRMAR` mandam arquivos reais para quarentena até a confirmação contra cabeçalhos
  reais (`docs/runbooks/piloto_local.md`).
- A defasagem não escolhe o mês vizinho: só é contada.
- Bytes, tempo e versões observadas das seis competências de desenvolvimento ficam para a execução
  real (`docs/pendencias/T05.md`).
