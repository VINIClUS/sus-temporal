# Reprodução por um terceiro (T14)

Roteiro para reproduzir o fluxo documentado em ambiente limpo, sem dados reais e sem rede depois
da instalação. Tudo aqui usa dados sintéticos gerados por código (`origem_dados: SINTETICO`): o
resultado verifica o software e **não é resultado empírico** (`docs/method/claims.md`). Dados
reais nunca entram no Git; as etapas que exigem rede ou dados reais estão na seção 7. O piloto
real tem o roteiro próprio em `docs/runbooks/piloto_local.md`.

## 1. Escopo e limites

- Reproduz-se: instalação travada, verificação do repositório (seção 3), fluxo da CLI sobre dados
  sintéticos, do `acquire` ao `freeze` (seção 4), e a reprodução offline de um congelamento
  (seção 5).
- Não se reproduz aqui: aquisição das fontes oficiais, piloto G0, comparações do teste, anotação
  humana e escala (seção 7), nem o congelamento confirmatório real (limite da seção 5).
- Estado do repositório: pré-G0. Nenhuma decisão G0, G1 ou G2 existe em `experiments/decisions/`;
  por isso `freeze` é recusado no repositório e nenhuma execução sintética é confirmatória. O
  fluxo da seção 4.5 escreve uma decisão G0 **de teste**, só no diretório temporário do mundo
  sintético, para exercitar o `freeze` exploratório; ela não vale como decisão.
- Verificado em 2026-10-05, em Linux x86_64, sobre `main` no commit `3fec351` (#29): as seções 2, 4
  e 5 num clone novo do branch da parte B da T14 e a seção 3 (`bash scripts/ci.sh`) no mesmo
  commit.

## 2. Ambiente limpo

Requisitos: Linux ou macOS (a descompressão limitada usa `RLIMIT_FSIZE`, só POSIX), `git`, `uv`
(o CI usa 0.8.17) e Python 3.12 (`requires-python = "==3.12.*"`; o `uv` instala se faltar).

```bash
git clone <URL do repositório> sus-temporal
cd sus-temporal
uv sync --locked
uv run sustemporal --help
```

`uv sync --locked` recusa um `uv.lock` que não corresponda ao `pyproject.toml` e instala as
versões travadas, com hashes. É o único passo que usa a rede (Python 3.12 e as dependências);
com o cache do `uv` preenchido, `uv sync --locked --offline` repete a instalação sem rede.

## 3. Verificação do repositório

```bash
bash scripts/ci.sh
```

Roda, nesta ordem, `ruff check`, `ruff format --check`, `mypy` (estrito), `python -m
scripts.check_ownership` e `pytest -q` com o perfil Hypothesis `ci` (determinístico). A
propriedade de arquivos só julga branch `claude/*` e PR contra `docs/process/propriedade.yaml`:
num clone normal de `main` (com a referência `origin/main`) ela registra
`propriedade_ignorada motivo=fora_de_pr` e passa; numa cópia sem `origin/main` sai com
`propriedade_erro base_ausente`. A execução completa passou na máquina de desenvolvimento em
cerca de 22 minutos, com 4.076 testes (medido em 2026-10-05, depois da parte B da T14); o tempo
varia com a máquina.

Recortes úteis: `uv run pytest tests/unit -q` (rápido) e `uv run pytest tests/integration -q`
(CLI e FTP local). O `pytest` exclui por padrão os marcadores `network`, `real_data` e `perf`, e o
`pytest-socket` só permite loopback: nenhum teste acessa a rede externa nem dados reais.

O `pytest` também audita o registro de alegações (`docs/method/claims.md`,
`tests/unit/test_alegacoes.py` e `tests/unit/test_alegacoes_decisoes.py`): todo estado diferente de
PENDENTE exige a decisão humana que cite a alegação, em `experiments/decisions/alegacoes/`
(só de humanos no mapa de propriedade). Hoje todas as alegações estão PENDENTE e o diretório não
existe.

## 4. Fluxo sintético pela CLI

Os dados vêm de fábricas de `tests/fixtures/` (um SIA-PA, um CNES PF e um SIGTAP mínimos, com
dois registros de produção, um deles fora do DRS XI). Nada disso é a distribuição de nenhuma
fonte oficial. Trabalhe num diretório fora do repositório.

### 4.1 Gerar as entradas sintéticas

```bash
export WORK="$(mktemp -d)"
CFG="$(uv run python - "$WORK" <<'PY'
import sys
from pathlib import Path

from tests.fixtures.cnes_dbc import artefato_cnes, dbc_cnes, registro_pf
from tests.fixtures.piloto_conjuntos import registro
from tests.fixtures.piloto_ingest import config_ingest, fontes_ingest
from tests.fixtures.piloto_manifesto import registrar_versoes
from tests.fixtures.sia_pa_fixtures import artefato_pa, dbc_pa
from tests.fixtures.sigtap_zip import artefato_sigtap, pacote_padrao, zip_sigtap

from sustemporal.contracts import FamiliaFonte

pasta = Path(sys.argv[1])
store = pasta / "dados" / "raw"
registros = [
    registro("C", "201801", "201801"),
    registro("C", "201801", "201801", PA_UFMUN="355030"),
]
pf = dbc_cnes(FamiliaFonte.CNES_PF, [registro_pf("0012345", "225125")])
versoes = [
    artefato_pa(store, dbc_pa(registros)),
    artefato_sigtap(store, zip_sigtap(pacote_padrao())),
    artefato_cnes(store, pf, FamiliaFonte.CNES_PF),
]
(pasta / "manifestos").mkdir(parents=True, exist_ok=True)
registrar_versoes(pasta / "manifestos" / "aquisicao.jsonl", versoes)
print(config_ingest(pasta, fontes_ingest(pasta, None)))
PY
)"
echo "$CFG"
```

O script grava os originais sintéticos no armazenamento por conteúdo (`dados/raw`) e as
observações no manifesto (`manifestos/aquisicao.jsonl`), como se uma aquisição tivesse ocorrido,
e imprime o caminho da configuração (`ingest.yaml`), com `origem_dados: SINTETICO`. O comando
`acquire` contra um servidor FTP local é exercitado pelos testes `tests/integration/test_acquisition*.py`.

### 4.2 Ingestão e relatório do piloto

```bash
uv run sustemporal --nivel-log WARNING ingest --config "$CFG"
uv run sustemporal --nivel-log WARNING pilot-report --config "$CFG"
```

Os dois terminam com saída 0. O `ingest` grava `saidas/ingest/execucao_<instante>_<id>/` (Parquet
por conjunto, `datasets.jsonl`, `resultados.jsonl`, `manifesto_lido.json`,
`configuracao_ingest.json`); o `pilot-report` grava `saidas/pilot/execucao_<instante>_<id>/` com
`relatorio.json` e as tabelas `piloto_*.v1`. O relatório é `SINTETICO` e exploratório.

### 4.3 Validação com as três políticas e explicação

```bash
INGEST="$(ls -d "$WORK"/saidas/ingest/execucao_* | tail -n 1)"
for POLITICA in documented atendimento processamento; do
  uv run sustemporal --nivel-log WARNING validate --config "$CFG" --policy "$POLITICA" \
    --ingest "$INGEST"
done
ls "$WORK/saidas/runs"
```

Cada política grava `saidas/runs/val_<hash>/` (`run_result.json`, `entrada_validacao.json`,
`avaliacoes.parquet`, `agregados_registro.parquet`, `evidencias.parquet`, `falhas.parquet`,
`selecao_versoes.parquet`, `recorte_territorial.json`); `saidas/runs/entradas/` e
`saidas/runs/selecoes/` guardam os conjuntos de entrada e as seleções compartilhados. A política
`documented` se abstém de escolher versão enquanto o critério documental estiver pendente
(`M_TEMP_PADRAO` é `NAO_RESOLVIDA`); `atendimento` e `processamento` são os comparadores `B_ATEND`
e `B_PROC`.

```bash
RUN="$(basename "$(grep -l '"B_ATEND"' "$WORK"/saidas/runs/val_*/run_result.json | head -n 1 \
  | xargs dirname)")"
ROW="$(uv run python - "$WORK/saidas/runs/$RUN/avaliacoes.parquet" <<'PY'
import sys

import pyarrow.parquet as pq

print(pq.read_table(sys.argv[1]).column("row_id")[0].as_py())
PY
)"
uv run sustemporal --nivel-log WARNING explain --config "$CFG" --run "$RUN" --row "$ROW"
ls "$WORK"/saidas/explicacoes/"$RUN"/*
```

A explicação sai em `saidas/explicacoes/<run_id>/row_<hash>/` (`bundle.json`, `explicacao.txt`,
`prov.json`, `prov.provn`, `reexecucoes.json`). O texto traz as limitações (dados sintéticos,
ausência não prova inexistência, retrato mensal, abstenção que não equivale a aprovação) e não
atribui causa à decisão oficial.

### 4.4 Contrafactual, portões e o limite do fluxo pequeno

```bash
uv run sustemporal --nivel-log WARNING counterfactual --config "$CFG" --run "$RUN" --row "$ROW"
echo "counterfactual: $?"
uv run sustemporal --nivel-log WARNING freeze --config "$CFG"; echo "freeze: $?"
```

O `counterfactual` sai com **2** (`contrafactual_sem_violacao`): a busca exige um registro com
regra em `VIOLACAO`, e o registro sintético deste fluxo só tem `CONFORME` e `INCONCLUSIVO`. A
seção 4.5 usa linhas com violação. Com violação, a busca precisa do CNES ST da competência no
contexto da execução: o `validate --ingest` o grava quando o registro temporal e o corte de
observação o confirmam; sem ele, toda operação fica inadmissível e a busca sai
`SEM_OPERACAO_ADMISSIVEL`, nunca com operação suposta.

O `freeze` sai com **4** (`portao_sem_decisao portao=G0`): congelar exige uma decisão G0 humana
em `experiments/decisions/`, que nenhum agente cria; é o comportamento esperado. Uma execução
sintética nunca é confirmatória: `evaluate` sem `--exploratory` exige configuração confirmatória,
que exige dados reais e G2.

`evaluate`, `annotation-export` e `reproduce` pedem um congelamento existente e saem com **2**
(`congelamento_ausente`) sem ele. Congelar também exige as partições do protocolo
(DESENVOLVIMENTO, CALIBRACAO e TESTE) em `<raiz_saidas>/split` e, por política, os insumos de
validação em `<raiz_saidas>/split/insumos/<politica_id>.json` (a `EntradaValidacao` inteira, que o
manifesto congela por política; seção 6), e nenhum comando da CLI os prepara (pendência T11 #27,
em `docs/pendencias/T11.md`): o fluxo pequeno, de um só mês, não os tem. A seção 4.5 os produz com
`sustemporal.reporting.reproduce_etapas`, o mesmo código que o `reproduce` usa para as partições.

### 4.5 Fluxo completo sintético: do `acquire` ao `freeze`

Um mundo sintético maior, em diretório próprio, percorre os comandos até o congelamento. Os
originais são arquivos de SIA-PA, CNES (PF e ST) e SIGTAP gerados por código e servidos por um
servidor FTP local (`pyftpdlib`, só em loopback); as competências de processamento formam três
janelas, que o protocolo separa em partições: DEV (201801 e 201803), CAL (202301) e TESTE
(202401). Os arquivos auxiliares de 201712 e 201802 **não existem de propósito**: o `acquire` da
passada auxiliar os pede, registra a ausência e sai com 5. Em DEV há uma linha de cada situação:

| Linha | Atendimento e processamento | O que o fluxo mostra |
|---|---|---|
| ausência | 201801 e 201801 | CBO fora do CNES de 201801: `B_ATEND` tem regra em `VIOLACAO`; o `counterfactual` sobre essa execução encontra a inclusão do CBO no estabelecimento, sem garantia de aprovação |
| mês faltante | 201802 e 201803 | sem arquivos de 201802: `B_ATEND` fica `INCONCLUSIVO` (o mês vizinho nunca substitui) e `B_PROC`, que usa 201803, fica `CONFORME`; o `counterfactual` recusa (`contrafactual_sem_violacao`) |
| borda de 2018 | 201712 e 201801 | sem arquivos de 201712: `B_ATEND` fica `INCONCLUSIVO` e `B_PROC`, que usa 201801, tem regra em `VIOLACAO`; o `counterfactual` sobre a execução `B_ATEND` recusa (`contrafactual_sem_violacao`) |

A política `documented` fica `INCONCLUSIVO` em todas (`M_TEMP_PADRAO` é `NAO_RESOLVIDA`). O
`explain` das três linhas e o `counterfactual` estão em `tests/integration/test_reproduce_offline.py`.

```bash
REPO="$(pwd)"
export MUNDO="$(mktemp -d)"
RESULTADO="$(uv run python - "$MUNDO" 2>"$MUNDO.log" <<'PY'
import json
import sys
from pathlib import Path

import pytest
from tests.fixtures.reproducao_fluxo import (
    adquirir_e_ingerir,
    congelar_e_avaliar,
    derivar,
    iniciar,
    validar_janelas,
)

with pytest.MonkeyPatch.context() as mp:
    fluxo = iniciar(Path(sys.argv[1]), mp)
    adquirir_e_ingerir(fluxo)
    validar_janelas(fluxo)
    derivar(fluxo)
    congelar_e_avaliar(fluxo)
    print(fluxo.freeze_id)
    print(json.dumps(fluxo.codigos))
PY
)"
FRZ="$(printf '%s\n' "$RESULTADO" | sed -n 1p)"
printf '%s\n' "$RESULTADO"
```

Leva cerca de 35 segundos; o registro dos comandos (inclusive do servidor FTP local) fica em
`$MUNDO.log`. O `MUNDO` é uma cópia limpa de `catalog/` e `config/` com as configurações do
fluxo (`config_dev.yaml`, `config_cal.yaml` e `config_teste.yaml`, a do protocolo); os comandos
rodam de dentro dele porque alguns padrões do código são relativos ao diretório de trabalho
(`config/splits.yaml`, `catalog/schemas/selecao_versoes.yaml` e `experiments/decisions`). O script
imprime o `freeze_id` e o código de saída de cada comando:

- `acquire_primaria` 0 e `acquire_auxiliar` **5** (ausência de 201712 e 201802, registrada);
- `ingest` 0 e os nove `validate_*` (três janelas, três políticas) 0;
- `freeze_sem_g0` **4** (sem decisão G0) e `freeze` 0, depois que `congelar_e_avaliar` grava uma
  decisão G0 **de teste** em `$MUNDO/experiments/decisions/`; o congelamento é exploratório;
- `evaluate_sem_exploratory` **4** (sintético nunca é confirmatório), `evaluate` (com
  `--exploratory`) 0 e `annotation_export` 0.

A união do SIA-PA, os rótulos e as partições vêm de `derivar_protocolo` e os `validate --ingest`
rodam sobre a janela de cada partição (`janela_do_ingest`); o `validate --ingest` exige que toda
a produção da pasta seja do recorte do piloto, e a janela é a pasta do `ingest` só com o SIA-PA
dos arquivos das competências pedidas. Os insumos que o `freeze` exige ficam em
`$MUNDO/saidas/split/insumos/<politica_id>.json`, um por política (seção 6): o script copia para lá
a `entrada_validacao.json` das execuções sobre a janela TESTE. O código do `freeze` lê a versão do código por `git`, e o
mundo não é um repositório: o script usa a versão de código de teste (`CODIGO_LIMPO`), que o
`reproduce` reporta como observação (seção 5).

### 4.6 Aceite da reprodução

1. `bash scripts/ci.sh` termina com 0.
2. Os passos 4.2 e 4.3 terminam com 0 e deixam `relatorio.json`, os três `run_result.json` e o
   `explicacao.txt` descritos acima.
3. O `counterfactual` da seção 4.4 sai com 2 e o `freeze`, com 4.
4. O script da seção 4.5 imprime os códigos listados e o `reproduce` da seção 5 sai com 0 e
   `resultado` IGUAL.

## 5. Reprodução offline de um congelamento (`sustemporal reproduce --freeze ID --offline`)

```bash
cd "$MUNDO"
uv run --project "$REPO" sustemporal --nivel-log WARNING reproduce \
  --config config_teste.yaml --freeze "$FRZ" --offline
echo "reproduce: $?"
uv run --project "$REPO" python -m json.tool "saidas/reproducao/$FRZ/reproducao.json" | head -n 30
```

Com o mundo da seção 4.5 o comando leva cerca de 25 segundos, sai com **0** e grava
`saidas/reproducao/<freeze_id>/reproducao.json` com `resultado` `IGUAL` nos 29 itens comparados. A
observação `codigo_diferente_do_congelado` aparece porque o mundo não é um repositório e o
congelamento usou a versão de código de teste (seção 4.5); ela não é divergência.

### 5.1 O que o comando faz

- O `freeze_id` resolve o manifesto exato `<runtime.dir_congelamentos>/<freeze_id>.json`, nunca um
  diretório "latest". Manifesto ausente, adulterado ou de outro id sai com 2 (`congelamento_*`),
  sem criar o destino.
- `--offline` é obrigatório (sem ele, saída 2). A config com `runtime.rede_permitida: true` sai com
  6 antes de abrir qualquer arquivo, e, durante a reprodução, toda conexão e toda resolução de
  nome, inclusive para a máquina local, falha com `RedeProibida` (saída 6): a guarda substitui
  `connect`, `connect_ex`, `create_connection` e `getaddrinfo` do `socket` e os restaura ao sair
  (`sustemporal.reporting.reproduce_rede`).
- O fluxo é refeito em um diretório novo (`--saida DIR`; padrão
  `<raiz_saidas>/reproducao/<freeze_id>`; um destino que já tem conteúdo, ou que é um arquivo, sai
  com 2): `ingest` dos originais do manifesto de aquisição, conferência do ingest (artefato do
  SIA-PA congelado que não foi normalizado torna a reprodução inconclusiva e para aqui), união do
  SIA-PA, rótulos, partições do split (com a especificação gravada no congelamento), as três
  políticas de `validate --ingest` sobre a janela da partição avaliada (CALIBRACAO) e da partição
  TESTE, e a avaliação (`evaluate_runs`, com o `bootstrap` do manifesto). Nada é gravado nas
  saídas originais nem no registro de rodadas; o `reproduce` não registra rodada.
- O refeito é comparado com o congelado e com a rodada registrada do mesmo congelamento e modo (a
  última de `registro_execucoes.jsonl`, com o relatório `avaliacao/<freeze_id>/rep_*.json` e as
  execuções em `runs/`).

### 5.2 O que é comparado

| Item de `reproducao.json` | Compara | Contra |
|---|---|---|
| `conjunto:sia_pa.v1` e `conjunto:sia_pa_rotulos.v1` | linhas e hash lógico da união e dos rótulos refeitos | o declarado no manifesto e, se o arquivo original existe, o arquivo |
| `split:split_id`, `split:particao:<P>` e `split:rotulos:<P>` | id do split e linhas e hash lógico de cada partição e dos rótulos dela | o split do manifesto |
| `insumos:<politica>` | cada campo da `EntradaValidacao` do TESTE refeita (`dataset`, `snapshots`, `auxiliares`, `selecoes`, `cobertura`, `integridade`, `politica_documentada`, `politica` e `identidade_adicional`), pela identidade de cada campo | `entradas_validacao` do manifesto, gravada de `split/insumos/<politica_id>.json` |
| `saida:<METODO>:<esquema>` | linhas e hash lógico das cinco saídas de cada método, **sem a coluna `run_id`** | as saídas da execução original |
| `metricas` | cada métrica por nome e estrato (numerador, denominador, valor e intervalo) | o relatório da rodada registrada |
| `notas` | as notas do relatório (recorte, especificação do bootstrap e cobertura dos resultados), como multiconjunto | as notas do relatório da rodada registrada |

O hash lógico (`lh1`) é do multiconjunto de linhas, nas colunas do esquema, e não depende da ordem
das linhas nem da compressão. O hash do refeito é sempre recalculado do arquivo, nunca lido do
contrato. O `run_id` não entra na comparação: o do `validate --ingest` depende dos caminhos da
config (`piloto.territorio`, `catalogos`), então a mesma entrada em outro diretório ou máquina dá
outro `run_id`; por isso as saídas se comparam sem essa coluna.

| Situação | Significa | Saída |
|---|---|---|
| `IGUAL` | linhas e hash lógico coincidem (e os bytes, se há arquivo original legível; sem ele, `detalhe` `original_ausente` ou `original_ilegivel` e vale o hash declarado no manifesto) | 0 |
| `BYTES_DIFERENTES_HASH_LOGICO_IGUAL` | mesmo conteúdo, bytes de Parquet diferentes (compressão, ordem ou metadados); é relatado e não é falha | 0 |
| `DIVERGENTE` | conteúdo diferente; inclui original que não confere com o declarado | 5 (`reproducao_divergente`) |
| `INCONCLUSIVO` | falta o original para comparar (relatório, execução ou saída ausente, truncada ou fora do contrato) ou o ingest refeito não normalizou um artefato do SIA-PA congelado (`originais_indisponiveis`: arquivo ausente, truncado ou com leiaute incompatível); nunca é violação, mas também não conta como reproduzido | 5 (`reproducao_inconclusiva`) |

O `resultado` geral é a pior situação dos itens. `reproducao.json` é gravado antes da falha
(`freeze_id`, `modo`, `origem_dados`, `resultado`, `relatorio_refeito`, `observacoes` e as
`comparacoes`, cada uma com `item`, `situacao`, `esperado`, `obtido` e `detalhe`), e a mensagem de
erro traz a contagem e os primeiros itens. Códigos de saída: 0 reproduzido; 2 config sem
`freeze_id` ou com outro, sem `--offline`, confirmatória, destino em uso, manifesto ou entradas
locais ausentes ou inválidas; 5 divergência ou item inconclusivo; 6 rede.

`observacoes` registra o que difere sem ser, por si, divergência de conteúdo:
`ingest_sem_tabela artefatos=N estados=...` (o ingest refeito deixou artefatos sem tabela: arquivo
ausente, quarentena ou falha; explica, por exemplo, um arquivo auxiliar do CNES ou do SIGTAP que
falta e aparece como `DIVERGENTE` nos insumos e nas saídas), `config_diferente_da_congelada` (o
hash do protocolo da config usada difere do congelado, por exemplo com outro número de threads ou
outros caminhos de `runtime`), `codigo_diferente_do_congelado congelado=<commit> atual=<commit>` e
`pacotes_diferentes_do_congelado pacotes=<lista>`. Leia-as junto do resultado.

### 5.3 Limites

- Só a rodada **exploratória** é reproduzida. Uma config confirmatória sai com 2
  (`reproduce_confirmatorio_nao_suportado`): o confirmatório exige dados reais e o G2 humano, a
  conferência do manifesto compara a config inteira, inclusive os caminhos de `runtime`, e
  reproduzir sem abrir nova rodada confirmatória pede uma decisão que ainda não existe (T14-9 e
  T14-13 em `docs/PENDENCIAS.md`). A alegação AL-22 continua PENDENTE.
- Os caminhos de `DatasetRef` no manifesto são absolutos (T08-i6): sem o arquivo original no
  caminho gravado, ou com o arquivo truncado, a união e os rótulos ainda são conferidos pelo hash
  declarado (`detalhe` `original_ausente` ou `original_ilegivel`), mas as saídas, o relatório e as
  notas ficam `INCONCLUSIVO`. O arquivo refeito ilegível, que é saída da própria reprodução, segue
  sendo falha (`arquivo_ilegivel`).
- Os comandos rodam da raiz do clone (ou de um diretório com cópia de `catalog/` e `config/`):
  `config/splits.yaml`, `catalog/schemas/selecao_versoes.yaml` e `experiments/decisions` são
  relativos ao diretório de trabalho.
- Não há comando de CLI que prepare a união, os rótulos, as partições e os insumos por política
  (`<raiz_saidas>/split/insumos/<politica_id>.json`) antes do `freeze` com dados reais (T11 #27,
  T14-14); `reproduce_etapas` refaz as partições e as entradas do TESTE para o fluxo pequeno.
- A guarda de rede vale para o processo inteiro: a reprodução não convive com outro trabalho de
  rede no mesmo processo.
- Nada aqui mede escala (SP) nem é resultado empírico: a reprodução sintética é teste de software.

### 5.4 Propriedades verificadas e os testes

`uv run pytest tests/integration/test_reproduce_offline.py -q` leva cerca de 2 minutos (marcador
`slow`, que roda no CI) e usa só dados sintéticos e o FTP local em loopback.

| Propriedade | Teste |
|---|---|
| 29 itens `IGUAL` e `resultado` `IGUAL`, com o `freeze` recusado sem G0 e exploratório com a decisão de teste | `test_reproduce_offline_reproduz_com_hashes_logicos_iguais` e `test_freeze_e_recusado_sem_g0_e_com_a_decisao_de_teste_fica_exploratorio` |
| Diretório novo e nenhum original alterado | `test_reproduce_refaz_o_fluxo_inteiro_no_diretorio_novo` e `test_reproduce_nao_altera_nenhum_original` |
| 4 threads dão as mesmas saídas e métricas; bytes diferentes com hash lógico igual saem como tais | `test_reproduce_com_4_threads_e_bytes_diferentes_nos_originais_segue_igual` |
| Divergência de conteúdo falha (saída 5) e nomeia os itens | `test_reproduce_falha_e_nomeia_os_itens_quando_o_conteudo_original_diverge` |
| Original do SIA-PA ausente é inconclusão (saída 5), não divergência nem reprodução | `test_reproduce_com_original_do_sia_pa_ausente_e_inconclusivo_e_nao_divergente` |
| Recusas: destino em uso ou arquivo, sem `--offline`, rede permitida, congelamento inexistente, confirmatório | os testes `test_reproduce_recusa_*`, `test_reproduce_exige_offline`, `test_reproduce_de_congelamento_inexistente_*` e `test_reproduce_nao_reproduz_congelamento_confirmatorio`, e `tests/unit/test_reproduce_recusas.py` |
| Nenhuma conexão sai do processo | `test_reproduce_roda_sob_a_guarda_de_rede` e `tests/unit/test_reproduce_rede.py` |
| Comparação por hash lógico, contagens e métricas; inconclusivo falha | `tests/unit/test_reproduce_comparacao.py` e `tests/unit/test_reproduce_conferencia.py` (split, originais, notas, ambiente e rodada registrada) |
| Sintético nunca é confirmatório | `test_sintetico_nunca_e_confirmatorio` |

## 6. Onde ficam saídas e manifestos

Os caminhos vêm de `runtime` na configuração; os padrões (`RuntimeConfig`) são relativos ao
diretório de trabalho e ficam fora do Git (`.gitignore`: `data/*`, `outputs/*`).

| Conteúdo | Chave | Padrão | Observação |
|---|---|---|---|
| Originais imutáveis | `raiz_dados` | `data/` | `raw/sha256/<2 primeiros>/<sha256>.<ext>`, endereçados pelo hash |
| Manifestos | `raiz_manifestos` | `manifests/` | `aquisicao.jsonl` (append-only), `.ancora`, `.trava`; `vigilancia.jsonl` |
| Saídas | `raiz_saidas` | `outputs/` | `ingest/`, `pilot/`, `runs/`, `explicacoes/`, `contrafactuais/`, `split/`, `avaliacao/`, `anotacao/`, `reproducao/` |
| Congelamentos | `dir_congelamentos` | `experiments/frozen/` | `<freeze_id>.json`, resolvido pelo id |
| Decisões G0, G1, G2 | fixo | `experiments/decisions/` | só humanos; `MODELO_*` nunca libera portão |
| Decisões sobre alegações | fixo | `experiments/decisions/alegacoes/` | só humanos; vale a decisão mais recente de cada alegação |

Cada execução grava sob um id que resolve artefatos exatos (`execucao_<instante>_<id>`,
`val_<hash>`), sem diretório "latest" mutável. O manifesto de aquisição guarda cada observação,
inclusive a repetida; os hashes lógicos dos conjuntos ficam em `datasets.jsonl` e nos
`run_result.json`.

**Destino do `validate`.** `validate` (`--entrada` e `--ingest`) grava em
`<raiz_saidas>/runs/<run_id>/`, o único lugar em que `explain`, `counterfactual` e `evaluate`
procuram execuções (leitor comum `sustemporal.execucoes`, que exige o `run_id` exato). `--saida
DIR` desvia a gravação, e então a execução não é achada por eles. O `evaluate` usa a mesma pasta por
constante própria; trocá-la por `raiz_execucoes(config)` é do PR de integração do orquestrador
(ORQ-28 em `docs/PENDENCIAS.md`).

**Entradas do `freeze` e do `evaluate`.** Eles leem as partições em `<raiz_saidas>/split`
(`spl_*.json` e `<split_id>.entradas.json`). O `freeze` lê também, **por política**,
`<raiz_saidas>/split/insumos/<politica_id>.json`: a `entrada_validacao.json` da execução de regras
daquela política sobre a partição TESTE (`EntradaValidacao`: `dataset`, `snapshots`, `auxiliares`,
`selecoes`, `cobertura`, `integridade`, `politica_documentada`, `politica` e
`identidade_adicional`). O manifesto congela a entrada inteira por `politica_id`
(`entradas_validacao`: a identidade de cada campo, sem caminhos) e a conferência compara cada
campo. Sem a pasta o `freeze` sai com 2 (`freeze_sem_insumos_das_execucoes`), e arquivo ilegível ou
de outra população também sai com 2 (`freeze_insumos_ilegiveis`,
`congelamento_insumos_de_outra_populacao`). Nenhum comando da CLI produz as partições nem os
insumos: são preparados à mão antes do G2 (T11 #27, em `docs/pendencias/T11.md`; detalhe em
`experiments/frozen/README.md`, seção "Entrada de validação das execuções de regras").

No fluxo sintético da seção 4.5, `derivar_protocolo` (`sustemporal.reporting.reproduce_etapas`)
grava as partições em `<raiz_saidas>/split`, e a etapa `derivar`, em
`tests/fixtures/reproducao_fluxo.py`, copia para `split/insumos/<politica_id>.json` a
`entrada_validacao.json` (`<raiz_saidas>/runs/<run_id>/entrada_validacao.json`) de cada uma das
três políticas (`m_temp_nao_resolvida`, `b_atend_exploratoria` e `b_proc_exploratoria`),
escolhendo a execução de `validate --ingest` cuja entrada é a população da partição TESTE. O
`reproduce` refaz as partições em `<saida>/split` e as entradas do TESTE em `<saida>/runs`, e
compara cada política com o congelado (`insumos:<politica_id>`, seção 5.2).

## 7. O que exige rede ou dados reais

Só `uv sync` (uma vez) e os comandos `acquire` e `watch` usam a rede, e só com
`runtime.rede_permitida: true` (sem isso, saída 6). Todo o resto roda offline. Dados reais ficam
fora do Git, sob `SUSTEMPORAL_REAL_DATA_DIR` ou nas raízes de `runtime` da configuração do
pesquisador. Os passos abaixo são executados na máquina do pesquisador; cada um tem o comando e
onde fica o detalhe.

### 7.1 Aquisição real

`uv run sustemporal acquire --config "$CFG"` (passada primária) e, em seguida, `--passada
auxiliar --competencias-atendimento ARQUIVO`. Antes, compare a listagem observada com
`catalog/sources.yaml` e registre a conferência em `docs/references/fontes.md`. Detalhe:
`docs/runbooks/piloto_local.md`, seção 1. Temporários `store/tmp/baixando_*` deixados por
interrupção forçada são removidos à mão, sem nenhuma aquisição em curso. O manifesto grava
`bytes_recebidos` de cada observação: o maior arquivo real calibra os tetos de ZIP, de DBF
descomprimido e de membro (`LimitesZip`, `LIMITE_DBF_PADRAO`, `limite_membro_bytes`).

### 7.2 Partes esperadas por competência

O catálogo não declara `partes_esperadas` do SIA-PA (SP tem partes a, b, c e d). Enquanto o
pesquisador não as declarar em `catalog/sources.yaml`, com a fonte, a competência multipartes fica
INSUFICIENTE e as linhas dependentes saem INCONCLUSIVO, no `ingest` e no `validate`. A declaração
entra por PR de humano e vale antes do `ingest` (o `pilot-report` recusa um catálogo diferente do
usado na ingestão).

### 7.3 Leiautes contra os cabeçalhos reais

Conferência dos cabeçalhos de SIA-PA, CNES e SIGTAP contra `catalog/layouts/` e atualização do
catálogo por PR: `docs/runbooks/piloto_local.md`, seção 2 e "Atualizar o catálogo por PR".

### 7.4 Fidelidade da leitura DBC

O `ingest` roda `verificar_fidelidade` em cada DBC (`runtime.verificacao_fidelidade`, padrão
`COMPLETA`): descompressão do `datasus-dbc` contra a do `dbc-to-dbf` e parser próprio contra o
`dbfread`. Divergência manda o arquivo para quarentena (`fidelidade_reprovada`). O relatório de
fidelidade só vai para o log: guarde a saída do `ingest` e o `resultados.jsonl` junto com o SHA-256
de cada original. O modo `AMOSTRAL` reduz o custo em arquivos estaduais.

### 7.5 Ingestão, relatório do piloto e perfil de rótulos

`ingest` e `pilot-report` sobre as seis competências (`config/pilot.yaml`): `docs/runbooks/
piloto_local.md`, seção 3. A amostra manual estratificada (competência, instrumento, `PA_INDICA`)
compara o bruto com o canônico, sobretudo as linhas com `CODIFICACAO_INVALIDA` e as contradições
de rótulo. Revise `resultados.jsonl` antes de ler o relatório: arquivo que excede um teto,
leiaute divergente ou competência incompleta aparece ali como quarentena, `FORA_DO_RECORTE` ou
`FORA_DO_CORTE`, com o motivo.

### 7.6 Registro da execução e decisão G0

Registro fora do Git de fontes, bytes, tempos e defasagens, e a decisão humana G0 (cópia de
`experiments/decisions/MODELO_G0.yaml` por PR de humano): `docs/runbooks/piloto_local.md`, seções
4 e 5. G1 e G2 também são registros humanos nesse diretório.

### 7.7 Vigilância de republicações

`uv run sustemporal watch --config config/watch.yaml` uma vez por semana durante doze meses, por
cron ou systemd (exemplo em `docs/method/temporal.md`, seção 6). Preserve
`manifests/aquisicao.jsonl` e `manifests/vigilancia.jsonl`.

### 7.8 Escala e desempenho

Medição de tempo, memória e armazenamento no DRS XI e em SP, com cache frio e quente e ao menos
três repetições, pelo harness `sustemporal.evaluation.performance` (`medir` e
`gravar_relatorio`), montando as etapas do fluxo sobre artefatos reais. O relatório JSON fica
fora do Git. Detalhe: `docs/method/valores.md`, seção "Desempenho".

### 7.9 Anotação humana cega

`uv run sustemporal annotation-export --config "$CFG" --freeze FREEZE_ID` gera o pacote cego do
congelamento; avaliadores, treino, concordância e adjudicação seguem `docs/method/annotation.md`
(seção "Execução"). Exige dados reais, G2 e um congelamento.

## 8. Redistribuição

O repositório publica código, catálogo, procedimentos, manifestos e fixtures geradas por código.
Não publica dados reais, saídas volumosas nem os arquivos oficiais: documentos oficiais entram só
por referência, hash ou trecho curto (`docs/references/fontes.md`). Duas auditorias rodam no CI:

- `tests/unit/test_licencas.py`: nenhuma dependência de runtime com licença GPL, AGPL ou LGPL
  nos metadados instalados, e licença desconhecida reprova;
- `tests/unit/test_redistribuicao.py`: nenhum arquivo rastreado (nem no histórico de `origin/main`)
  em `data/` ou `outputs/`, nenhum `.dbc`, `.dbf`, `.parquet`, `.zip` ou `.pdf` e nenhum arquivo
  acima de 200 KB sem justificativa; o PDF do esboço só entra com o SHA-256 do manifesto.

Quando uma fonte não puder ser redistribuída, quem reproduz a reconstrói pela seção 7 e confere o
SHA-256 do original contra o manifesto de aquisição.
