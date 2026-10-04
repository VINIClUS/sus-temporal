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
| `piloto_campos.v1` | ausentes e denominador por campo exigido pelas famílias |
| `piloto_defasagem.v1` | linhas por defasagem em meses (processamento − atendimento); nula quando falta uma |
| `piloto_rotulos.v1` | `ANTES`: PA_INDICA bruto; `DEPOIS`: rótulo do codebook; aprovações incluídas |
| `piloto_inconclusivos.v1` | classe e linhas da seleção por regra, fonte, base e estado |
| `piloto_disponibilidade.v1` | a `cobertura.v1` no intervalo e nos instrumentos da coorte |

Os rótulos aqui servem só para descrever a distribuição antes e depois do pré-processamento. O
classificador nunca recebe rótulo, campos de erro nem quantidades ou valores aprovados.

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
