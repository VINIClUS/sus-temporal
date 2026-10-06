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
  e 5 num clone novo do branch da parte B da T14 e a seção 3 (`bash scripts/ci.sh`) sobre o
  mesmo código e os mesmos testes.

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
28 min 33 s, com 4.221 testes passando e 1 desmarcado (medido em 2026-10-06 numa máquina de 4
núcleos, depois da rodada 4 do #37; a rodada 5 acrescentou testes, e o tempo e a contagem dela estão
no corpo do PR); o tempo varia com a máquina e a carga. O CI do GitHub tem
limite de 45 minutos (30 até o #39) e já levou 27 min 53 s (#37, rodada 2), 24 min 12 s (rodada 3),
28 min 32 s (rodada 4) e 20 min 52 s (rodada 8): a suíte tem folga, mas cada teste novo que refaz o
fluxo todo (cerca de 25 s) pesa.

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
observação o confirmam (só com a seleção `SELECIONADA`, conferida por competência: duas versões da
mesma competência tiram o cadastro do contexto, ORQ-30, e o CNES ST em várias partes segue aberto,
ORQ-27); sem ele, toda operação fica inadmissível e a busca sai `SEM_OPERACAO_ADMISSIVEL`, nunca
com operação suposta.

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
(o arquivo de 202401, cujas linhas foram processadas em 202402: a competência do arquivo difere da
das linhas, caso que o `ingest` aceita, e por isso o piloto da janela TESTE lista as duas). Os
arquivos auxiliares de 201712 e 201802 **não existem de propósito**: o `acquire` da passada
auxiliar os pede, registra a ausência e sai com 5. Em DEV há uma linha de cada situação:

| Linha | Atendimento e processamento | O que o fluxo mostra |
|---|---|---|
| ausência | 201801 e 201801 | CBO fora do CNES de 201801: `B_ATEND` tem regra em `VIOLACAO`; o `counterfactual` sobre essa execução encontra a inclusão do CBO no estabelecimento, com `aprovacao_garantida` falso |
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
    artefatos_do_sia_pa,
    congelar_e_avaliar,
    derivar,
    iniciar,
    validar_janelas,
)

with pytest.MonkeyPatch.context() as mp:
    fluxo = iniciar(Path(sys.argv[1]), mp)
    adquirir_e_ingerir(fluxo)
    validar_janelas(fluxo)
    derivar(fluxo, inspecionados=artefatos_do_sia_pa(fluxo, "dev"))
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
dos arquivos das competências pedidas. O split original marca como inspecionados
(`artefatos_inspecionados`) os dois arquivos do SIA-PA da janela DEV, como quem já os olhou no
desenvolvimento; eles entram no `split_id`, e o `reproduce` refaz o split com os que o
congelamento registrou. Os insumos que o `freeze` exige ficam em
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
`saidas/reproducao/<freeze_id>/reproducao.json` com `resultado` `IGUAL` nos 31 itens comparados. A
observação `codigo_diferente_do_congelado` aparece porque o mundo não é um repositório e o
congelamento usou a versão de código de teste (seção 4.5); ela não é divergência.

### 5.1 O que o comando faz

- O `freeze_id` resolve o manifesto exato `<runtime.dir_congelamentos>/<freeze_id>.json`, nunca um
  diretório "latest". Manifesto ausente, adulterado ou de outro id sai com 2 (`congelamento_*`),
  sem criar o destino.
- `--offline` é obrigatório (sem ele, saída 2). A config com `runtime.rede_permitida: true` sai com
  6 antes de abrir qualquer arquivo, e, durante a reprodução, uma guarda no módulo `socket` do
  Python recusa com `RedeProibida` (saída 6), inclusive para a máquina local: criar socket que não
  seja `AF_UNIX`; conectar e enviar (`connect`, `connect_ex`, `sendto`, `sendmsg`, `send`, `sendall`
  e `sendfile`, o datagrama sem conexão inclusive) em socket de rede criado antes dela;
  `create_connection`; e a resolução de nome (`getaddrinfo`, `gethostbyname`, `gethostbyname_ex`,
  `gethostbyaddr` e `getnameinfo`). `AF_UNIX` (comunicação local, como o `socketpair`) é permitido, e
  a guarda restaura tudo ao sair, com ou sem exceção (`sustemporal.reporting.reproduce_rede`). Ela
  vale para o módulo `socket` do Python no processo: extensão em C que abra socket nativo, o
  `_socket` usado direto, o descritor cru de um socket aberto (`os.write`, `os.sendfile`), o socket
  TLS (`ssl.SSLSocket`) aberto antes da guarda, que escreve pelo OpenSSL sem passar pelos métodos
  de `socket.socket`, e subprocesso ficam fora, e o DuckDB não instala nem carrega extensões sozinho
  (`sustemporal.duck.conectar`). Isolamento de verdade é do ambiente (seção 5.5, T14-16).
- O fluxo é refeito em um diretório novo (`--saida DIR`; padrão
  `<raiz_saidas>/reproducao/<freeze_id>`; um destino que já tem conteúdo, ou que é um arquivo, sai
  com 2): resolução da posição do manifesto de aquisição e das entradas originais (abaixo),
  `ingest` dos originais do manifesto até essa posição, conferência do ingest (artefato do
  SIA-PA congelado, ou dos auxiliares CNES e SIGTAP das entradas congeladas, que não foi
  normalizado torna a reprodução inconclusiva e para aqui, antes de refazer), união do
  SIA-PA, rótulos, partições do split (com a especificação e os artefatos inspecionados gravados
  no congelamento), os três
  métodos de `validate --ingest` sobre a janela da partição avaliada (CALIBRACAO) e da partição
  TESTE, cada um com a política da execução congelada dele (abaixo), e a avaliação
  (`evaluate_runs`, com o `bootstrap` do manifesto). Nada é gravado nas
  saídas originais nem no registro de rodadas; o `reproduce` não registra rodada.
- O manifesto de aquisição é o que o `ingest` original leu. O `reproduce` acha, em
  `<raiz_saidas>/ingest`, as execuções (`execucao_*`) cujo SIA-PA (a união dos `artifact_ids` dos
  conjuntos `sia_pa.v1` do `datasets.jsonl`) é o do conjunto `sia_pa.v1` congelado, e lê delas a
  posição que o `ingest` gravou em `manifesto_lido.json` (`linhas` e o hash da última).
  `<saida>/manifestos/aquisicao.jsonl` é o prefixo do manifesto atual até essa posição, com a
  mesma cadeia e a âncora; o `ingest`, a janela, as fontes do split e o registro temporal do
  `validate` da reprodução leem essa cópia (`sustemporal.reporting.reproduce_manifesto`). Coleta
  nova, republicação, recoleta ou ausência registradas depois do `ingest` ficam de fora, seja qual
  for o instante da observação (a coleta semanal registra o tempo todo, e `observado_em` não
  decide): são contadas nas observações `artefatos_depois_do_ingest_ignorados` e
  `observacoes_depois_do_ingest_ignoradas` e nunca viram divergência, e a execução e a posição
  usadas ficam em `manifesto_do_ingest execucao=... linhas=...`. Execuções com a mesma posição
  valem uma só. Sem execução, com candidata sem posição legível, com posições diferentes entre as
  candidatas ou com uma posição que o manifesto atual não tem (linhas a mais, hash da última
  diferente, fim no meio de uma transação, manifesto corrompido), a posição não se sabe: o item
  `manifesto:aquisicao` sai `INCONCLUSIVO` com o motivo e a reprodução para antes do `ingest`,
  nunca voltando a um corte por instante. O artefato congelado sem o arquivo segue inconclusivo.
- O `ingest` original também grava a configuração com que rodou (`configuracao_ingest.json`: `uf`,
  `corte_observacao`, `familias_fontes`, o SHA-256 do catálogo de fontes e o do leiaute do
  SIA-PA), e a execução só vale como original se tem a que o `ingest` refeito vai usar; todas as
  candidatas têm de tê-la. Sem o arquivo, ilegível ou com algum campo diferente (outra UF, outro
  corte, outro catálogo de fontes), o item `manifesto:aquisicao` sai `INCONCLUSIVO`
  (`ingest_original_sem_configuracao` ou `ingest_original_com_configuracao_diferente campos=...`)
  e a reprodução para antes do `ingest`: o refeito não seria o que o congelamento usou.
- A `origem_dados` da config (sem ela, `SINTETICO`) tem de ser a dos conjuntos congelados; senão o
  item `origem_dados` sai `INCONCLUSIVO` (`origem_dados_diferente_do_congelado`) e a reprodução
  para antes do `ingest`.
- A janela de cada partição refeita (a avaliada e o TESTE) é o `ingest` com só o SIA-PA dos
  artefatos que a partição registra (`janela_dos_artefatos`), nunca pelo mês das linhas. O piloto
  da janela leva as competências dos arquivos (o `validate --ingest` as exige) e as das linhas
  (ele recorta por elas). Partição sem artefatos não executa regra: o item `particao:<P>` sai
  `INCONCLUSIVO` (`particao_vazia`), com a observação `particao_sem_artefatos`, e o fluxo para
  antes da validação.
- O refeito é comparado com o congelado e com a rodada registrada do mesmo congelamento e modo (a
  última de `registro_execucoes.jsonl`, com o relatório `avaliacao/<freeze_id>/rep_*.json` e as
  execuções em `runs/`). O relatório só vale se bate com a entrada do registro (`report_id`,
  `freeze_id`, modo, origem dos dados, `decisao_g2`, lista de execuções, quantidade de métricas e
  de métricas nulas): um relatório válido que não é o registrado (copiado de outro congelamento,
  trocado depois) é original indisponível, os itens `metricas`, `notas` e `relatorio:campos` saem
  `INCONCLUSIVO` e a observação `relatorio_original_nao_confere_com_o_registro campos=...` diz em
  que ele difere (`sustemporal.reporting.reproduce_original`). O método com duas execuções
  registradas não tem execução original (a última não substitui a primeira) e a observação
  `execucao_registrada_repetida metodo=...` o diz.
- Os artefatos dos auxiliares vêm da `entrada_validacao.json` original de cada política
  (`<raiz_saidas>/split/insumos/<politica_id>.json`, a que o `freeze` leu), porque o manifesto guarda
  só a identidade de cada campo. Ela só vale se existe, é legível e tem, campo a campo, a
  identidade congelada (`conferir_entradas`); a população e os rótulos já são conferidos pelo
  manifesto, e a cobertura e a seleção só derivam desses artefatos (T14-16). Ausente, ilegível ou
  alterada depois do congelamento, ela não se ignora: o item `insumos:<politica>` sai
  `INCONCLUSIVO` (`entrada_original_ausente`, `entrada_original_ilegivel` ou
  `entrada_original_alterada`) e a reprodução para antes de refazer, com o auxiliar disponível ou
  não.
- Cada método é refeito com a política da execução congelada dele, e não com a `politica_id` da
  config: o `config/cohort.yaml` traz `politica_id: M_TEMP_PADRAO`, que o `validate` recusa nos
  baselines, e uma config sem `politica_id` dá a padrão do método, que pode não ser a congelada
  (`sustemporal.reporting.reproduce_politicas`). A política de cada método é a da entrada original
  (campo `politica`; sem ele, a do catálogo `catalog/policies/<politica_id>.yaml`); tem de ter a
  identidade que o manifesto congelou (`entradas_validacao`) e, se a execução registrada do método
  existe, o mesmo `politica_id`. Refaz-se como a padrão do método (se é igual a ela) ou como a do
  catálogo de mesmo id e conteúdo. A que não é nenhuma das duas (alterada ou removida do catálogo,
  fora do catálogo, duas do mesmo método, de id diferente da chave ou diferente da execução
  registrada) não se refaz: o item `insumos:<politica>` sai `INCONCLUSIVO`
  (`politica_congelada_indisponivel`, `politica_congelada_alterada`,
  `politica_congelada_com_outro_id`, `politica_congelada_ambigua` ou
  `politica_registrada_diferente`), nunca erro de configuração nem divergência, e a reprodução
  para antes de refazer. O método sem política congelada segue pela padrão.
- Os catálogos que a config declara e o catálogo de regras têm o SHA-256 no manifesto. A
  reprodução usa os de agora, e a diferença é observação (`catalogos_diferentes_do_congelado`,
  `catalogo_de_regras_diferente_do_congelado`): o conteúdo refeito decide se é igual ou divergente.
- Arquivo que a cadeia abre e não consegue ler (diretório no lugar do arquivo, falta de permissão,
  bytes que não decodificam ou truncados) nunca vira traceback, `DIVERGENTE` nem `IGUAL` sem
  justificativa; a falta de arquivo necessário é verificação inconclusiva, nunca violação. O que é
  original (manifesto de aquisição e a trava dele, registro de rodadas, relatório, execuções,
  saídas, insumos, execução do `ingest` e arquivos brutos) deixa o item `INCONCLUSIVO` e o
  `reproducao.json` é gravado: `manifesto_ilegivel erro=<Tipo>` ou `manifesto_corrompido` no
  `manifesto:aquisicao`, `registro_ilegivel erro=<Tipo>` nas observações (sem registro não há
  relatório nem execução original), `original_ilegivel arquivo=<relativo a raiz_dados>` no item
  `ingest:originais` (arquivo bruto sem permissão). O que é entrada da config ou do repositório
  (config, congelamento, catálogo de fontes, território e os catálogos de `catalog/`) sai 2 com
  `chave=valor`: o erro de cada leitor, ou `reproduce_entrada_ilegivel arquivo=... erro=... onde=...`
  para o que nenhum leitor trata (`sustemporal.reporting.reproduce_leitura`), e
  `reproduce_saida_ilegivel` (saída 5) se o arquivo é do destino da própria reprodução. O registro de
  rodadas adulterado, inclusive com bytes que não decodificam, segue falha operacional
  (`registro_adulterado`, saída 5, sem `reproducao.json`). A tabela da seção 5.5 diz o resultado de
  cada arquivo e cada dano, e `tests/integration/test_reproduce_leituras.py` estraga cada um.

### 5.2 O que é comparado

| Item de `reproducao.json` | Compara | Contra |
|---|---|---|
| `conjunto:sia_pa.v1` e `conjunto:sia_pa_rotulos.v1` | o leiaute do Parquet (nomes, ordem e tipos), linhas e hash lógico da união e dos rótulos refeitos, e a linhagem (`artifact_ids`); o conjunto refeito que o manifesto não traz sai `INCONCLUSIVO` (`conjunto_nao_congelado`) | o declarado no manifesto e, se o arquivo original existe, o arquivo |
| `split:split_id`, `split:campos`, `split:particao:<P>` e `split:rotulos:<P>` | id do split (que leva a especificação, a coorte, as fontes, os rótulos e os artefatos inspecionados); todos os outros campos do manifesto do split, juntos em `split:campos` (`spec`, `dataset_hash`, contagens e hashes por partição, artefatos inspecionados e de TESTE, `cohort_id`, `exclusoes` e `limites`); e o leiaute, as linhas, o hash lógico e a linhagem de cada partição e dos rótulos dela, pela união das partições das duas pontas | o split do manifesto |
| `insumos:<politica>` | cada campo da `EntradaValidacao` do TESTE refeita (`dataset`, `snapshots`, `auxiliares`, `selecoes`, `cobertura`, `integridade`, `politica_documentada`, `politica` e `identidade_adicional`), pela identidade de cada campo (a união dos campos das duas pontas: o que só o congelamento traz também diverge); antes de refazer, que a entrada original da política confira, que a política congelada se resolva (`politica_congelada_*` e `politica_registrada_diferente`) e a disponibilidade dos artefatos dos `auxiliares` (CNES e SIGTAP) | `entradas_validacao` do manifesto, gravada de `split/insumos/<politica_id>.json`; os artefatos e a política, dessa entrada original |
| `manifesto:aquisicao` | só aparece quando a posição do manifesto de aquisição que o `ingest` original leu, ou a configuração com que ele rodou, não se sabe ou não é a do refeito: sempre `INCONCLUSIVO`, com o motivo em `detalhe` (`ingest_original_ausente`, `ingest_original_sem_posicao`, `ingest_original_ambiguo`, `ingest_original_sem_configuracao`, `ingest_original_com_configuracao_diferente`, `manifesto_menor_que_o_lido_pelo_ingest`, `manifesto_diferente_do_lido_pelo_ingest`, `posicao_do_ingest_no_meio_de_uma_transacao`, `manifesto_corrompido` ou `manifesto_ilegivel erro=<Tipo>`: diretório no lugar do manifesto ou da trava, sem permissão) | `manifesto_lido.json` e `configuracao_ingest.json` da execução do `ingest` que produziu o SIA-PA congelado |
| `ingest:originais` | só aparece quando o `ingest` refeito não consegue ler um arquivo bruto do manifesto de aquisição (sem permissão): sempre `INCONCLUSIVO` (`original_ilegivel arquivo=<relativo a raiz_dados> erro=<Tipo>`), e a reprodução para aí | o arquivo bruto que o manifesto aponta |
| `origem_dados` | só aparece quando a `origem_dados` da config (sem ela, `SINTETICO`) não é a dos conjuntos congelados: sempre `INCONCLUSIVO` (`origem_dados_diferente_do_congelado`) | a `origem_dados` dos `datasets` do manifesto |
| `saida:<METODO>:<esquema>` | o leiaute completo (nomes, ordem e tipos), linhas e hash lógico das cinco saídas de cada método, **sem os valores da coluna `run_id`**, e a linhagem, pela união dos esquemas das duas execuções (e dos métodos); a saída repetida na mesma execução vira `<esquema>#2`, `#3`... | as saídas da execução original |
| `metricas` | cada métrica por nome e estrato (numerador, denominador, valor e intervalo), como multiconjunto: a métrica repetida conta cada vez | o relatório da rodada registrada |
| `notas` | as notas do relatório (recorte, especificação do bootstrap e cobertura dos resultados), como multiconjunto | as notas do relatório da rodada registrada |
| `relatorio:campos` | `modo`, `origem_dados`, `freeze_id`, `decisao_g2`, a quantidade de execuções e as tabelas (esquema, linhas e hash lógico); ficam de fora o `report_id`, o instante e os ids das execuções, que derivam de caminho e relógio, e as métricas e notas, que têm item próprio | o relatório da rodada registrada |

O hash lógico (`lh1`) é do multiconjunto de linhas, nas colunas do esquema, e não depende da ordem
das linhas nem da compressão. O hash do refeito é sempre recalculado do arquivo, nunca lido do
contrato. Os valores de `run_id` não entram na comparação: o do `validate --ingest` depende dos
caminhos da config (`piloto.territorio`, `catalogos`), então a mesma entrada em outro diretório ou
máquina dá outro `run_id`; por isso o hash das saídas deixa de fora os valores dessa coluna.

Antes de calcular qualquer hash, o leiaute completo do Parquet é conferido contra o esquema canônico
(`catalog/schemas`) e, nas saídas, dos dois lados entre si: nomes, **ordem** e tipos físicos. A
ordem faz parte do esquema (todo escritor grava as colunas na ordem do esquema) e cada tipo canônico
tem o seu tipo físico: `TEXTO` é `VARCHAR`, `INTEIRO` é `BIGINT`, `BOOLEANO` é `BOOLEAN`, `DATA` é
`DATE` e `DECIMAL` é `DECIMAL(p,s)` de qualquer precisão. Coluna que falta (inclusive `run_id`, que
o hash ignora), coluna a mais, coluna de outro tipo e colunas fora de ordem são `DIVERGENTE` com
`esquema_divergente colunas=<lista> lado=<refeito|original|original_e_refeito>`; a projeção do hash
nunca é a interseção das colunas, que esconderia a diferença. Com o mesmo conteúdo, os artefatos de
origem (`artifact_ids`, como multiconjunto) também têm de ser os mesmos: `linhagem_diverge`. A seção 5.6
diz o que cada comparação confere antes de projetar e o que deixa de fora.

| Situação | Significa | Saída |
|---|---|---|
| `IGUAL` | linhas e hash lógico coincidem; nos itens que comparam o arquivo refeito com o declarado (`conjunto:*`, `split:particao:*` e `split:rotulos:*`) também os bytes, se há arquivo original legível (sem ele, `detalhe` `original_ausente` ou `original_ilegivel` e vale o hash declarado no manifesto); nos itens `saida:*` os bytes não se comparam, porque o `run_id` gravado difere por construção, e decide o hash lógico sem os valores dessa coluna | 0 |
| `BYTES_DIFERENTES_HASH_LOGICO_IGUAL` | só nos itens `conjunto:*`, `split:particao:*` e `split:rotulos:*`: mesmo conteúdo, bytes de Parquet diferentes (compressão, ordem ou metadados); é relatado e não é falha. Os itens `saida:*` não o dão | 0 |
| `DIVERGENTE` | conteúdo diferente; inclui original que não confere com o declarado, saída registrada que a reconstrução não emitiu (`saida_ausente_no_refeito`, por exemplo `evidencias.v1`), saída nova que a execução registrada não tem (`saida_sem_original`), método que a reconstrução não refez, leiaute de Parquet diferente do esquema ou entre as duas pontas (`esquema_divergente`), linhagem diferente (`linhagem_diverge`), partição que só o refeito traz (`particao_sem_original`) e campos diferentes (`campos=<lista>` em `split:campos`, `relatorio:campos` e `insumos:<politica>`) | 5 (`reproducao_divergente`) |
| `INCONCLUSIVO` | falta o original para comparar (relatório, execução ou saída ausente, truncada ou fora do contrato), a posição do manifesto de aquisição que o `ingest` original leu não se sabe, ou a configuração com que ele rodou não é a do refeito (item `manifesto:aquisicao`), a origem dos dados da config não é a dos conjuntos congelados (item `origem_dados`), o manifesto de aquisição não abre ou um arquivo bruto não abre (`manifesto_ilegivel`, item `ingest:originais`), o relatório da rodada registrada não bate com a entrada do registro (`metricas` e `notas`), a entrada original da política em `split/insumos` falta, não lê ou foi alterada (`entrada_original_ausente`, `_ilegivel` ou `_alterada`, item `insumos:<politica>`), a política congelada de um método não se resolve ou não se confere (`politica_congelada_indisponivel`, `_alterada`, `_com_outro_id`, `_ambigua` ou `politica_registrada_diferente`, item `insumos:<politica>`), a partição refeita (avaliada ou TESTE) não tem artefatos (`particao_vazia`, item `particao:<P>`) ou o conjunto refeito não está no manifesto (`conjunto_nao_congelado`), o congelamento não traz as partições refeitas (`particao_nao_congelada`) ou o ingest refeito não normalizou um artefato do SIA-PA congelado ou dos auxiliares das entradas congeladas, CNES e SIGTAP (`originais_indisponiveis`: arquivo ausente, truncado, em quarentena ou com leiaute incompatível; nos auxiliares o item é `insumos:<politica>`); nunca é violação, mas também não conta como reproduzido | 5 (`reproducao_inconclusiva`) |

O `resultado` geral é a pior situação dos itens. `reproducao.json` é gravado antes da falha
(`freeze_id`, `modo`, `origem_dados` (a dos conjuntos do manifesto congelado), `origem_dados_config` (a declarada na config, e `SINTETICO` sem declaração), `resultado`, `relatorio_refeito`, `observacoes` e as
`comparacoes`, cada uma com `item`, `situacao`, `esperado`, `obtido` e `detalhe`), e a mensagem de
erro traz a contagem e os primeiros itens. Códigos de saída: 0 reproduzido; 2 config sem
`freeze_id` ou com outro, sem `--offline`, confirmatória, destino em uso, manifesto ou entradas
locais ausentes, ilegíveis ou inválidas; 5 divergência ou item inconclusivo; 6 rede.

`observacoes` registra o que difere sem ser, por si, divergência de conteúdo:
`ingest_sem_tabela artefatos=N estados=...` (o ingest refeito deixou artefatos sem tabela: arquivo
ausente, quarentena ou falha; explica os itens `INCONCLUSIVO` de `originais_indisponiveis`),
`manifesto_do_ingest execucao=... linhas=...` (a execução do `ingest` original e o tamanho do
manifesto de aquisição que a reprodução leu),
`artefatos_depois_do_ingest_ignorados n=...` e `observacoes_depois_do_ingest_ignoradas n=...` (o que
o manifesto atual tem depois dessa posição e a cópia deixou de fora), `particao_sem_artefatos
particao=...` (a partição refeita não tem artefatos), `relatorio_original_nao_confere_com_o_registro campos=...` (o relatório lido não é o que o registro descreve), `execucao_registrada_repetida metodo=...` (o método tem duas execuções registradas e fica sem original), `registro_ilegivel erro=<Tipo>` (o registro de rodadas não abre: sem rodada, sem relatório nem execução original), `catalogos_diferentes_do_congelado catalogos=...` e `catalogo_de_regras_diferente_do_congelado` (o SHA-256 de um catálogo, ou do catálogo de regras, difere do congelado), `config_diferente_da_congelada` (o hash do
protocolo da config usada difere do congelado, por exemplo com outro número de threads ou outros
caminhos de `runtime`), `codigo_diferente_do_congelado congelado=<commit> atual=<commit>` e
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
- A disponibilidade dos auxiliares e a política de cada método só são conferidas com a
  `entrada_validacao.json` original de cada política em `<raiz_saidas>/split/insumos` (T14-16).
  Sem ela (ausente, ilegível ou alterada depois do congelamento) a política fica `INCONCLUSIVO`
  (`entrada_original_*`) e nada se refaz; o mesmo vale para a política que não se resolve
  (`politica_congelada_*`).
- A posição do manifesto de aquisição vem do `ingest` original, não do congelamento: o manifesto de
  congelamento não guarda a posição que o `freeze` leu nem a execução do `ingest`, e o `reproduce`
  acha a execução pelo SIA-PA congelado (T14-16). Duas execuções do `ingest` sobre o mesmo SIA-PA
  com o manifesto em posições diferentes (uma coleta semanal entre elas, por exemplo) deixam a
  posição ambígua, e o congelamento não diz qual valeu: `INCONCLUSIVO`. Supõe-se que o `validate` e
  o `freeze` leram o manifesto onde o `ingest` o leu; uma coleta registrada entre o `ingest` e o
  `validate` muda o registro temporal do `validate` e pode aparecer como divergência nos `insumos`.
  Um split derivado de uma janela, e não do `ingest` inteiro, não casa com nenhuma execução. A
  execução do `ingest` também só vale se gravou a configuração do refeito (`configuracao_ingest.json`);
  execução sem ela, de antes dessa gravação, deixa a posição desconhecida.
- O que mais a cadeia lê, e o que fica sem conferência (limites que não dão `IGUAL` falso), está na
  seção 5.5.
- Os comandos rodam da raiz do clone (ou de um diretório com cópia de `catalog/` e `config/`):
  `config/splits.yaml`, `catalog/schemas/selecao_versoes.yaml` e `experiments/decisions` são
  relativos ao diretório de trabalho.
- Não há comando de CLI que prepare a união, os rótulos, as partições e os insumos por política
  (`<raiz_saidas>/split/insumos/<politica_id>.json`) antes do `freeze` com dados reais (T11 #27,
  T14-14); `reproduce_etapas` refaz as partições e as entradas do TESTE para o fluxo pequeno.
- A guarda de rede vale para o processo inteiro: a reprodução não convive com outro trabalho de
  rede no mesmo processo. O que ela cobre e o que fica fora está na seção 5.1 e nos limites da 5.5.
- A varredura das leituras (seção 5.5) estraga os arquivos do mundo temporário de verdade. O
  catálogo do clone (`catalog/`) só falha na abertura, por um gancho de auditoria do Python
  (`sys.addaudithook`): um teste não estraga o repositório. Onde o processo lê arquivo sem permissão
  (root com `CAP_DAC_OVERRIDE`) o dano `PERMISSAO` do mundo temporário é pulado, com o motivo; no CI
  do GitHub (usuário comum) ele roda. A auditoria vê o que o Python abre: leitura que só uma
  extensão em C fizesse escaparia dela (os Parquet comparados passam por `open` no SHA-256 do
  arquivo). O destino da reprodução não é varrido: é novo e vazio, e o que se perde durante a
  execução sai `reproduce_saida_ilegivel` (saída 5). A união, os rótulos e as partições originais
  que não abrem seguem `IGUAL` pelo hash que o congelamento declara, com `original_ausente` ou
  `original_ilegivel` no detalhe: o arquivo é só a segunda conferência (limite de T14-12).
- A leitura do manifesto de aquisição (`Manifesto.ler`, do `acquire`) abre a trava em modo de
  acréscimo, então `<raiz_manifestos>` em mídia só de leitura não se lê: o item `manifesto:aquisicao`
  sai `INCONCLUSIVO` (`manifesto_ilegivel erro=PermissionError` ou `OSError`), e não mais com
  traceback. Reproduzir de uma cópia só de leitura pede a trava gravável (T14-16).
- Nada aqui mede escala (SP) nem é resultado empírico: a reprodução sintética é teste de software.

### 5.4 Propriedades verificadas e os testes

`uv run pytest tests/integration/test_reproduce_offline.py -q` leva cerca de 2 minutos (marcador
`slow`, que roda no CI) e usa só dados sintéticos e o FTP local em loopback. Uma reprodução
completa custa cerca de 15 s (22 s sem a memória de YAML, abaixo) e o CI do GitHub tem limite de 45
minutos (30 até o #39), então as variações que não
mudam o conteúdo (config no estilo do `config/cohort.yaml`, 4 threads, catálogo que o congelamento
não tinha, rótulos originais regravados) e os estragos independentes (conteúdo original adulterado,
relatório que não é o registrado, saídas que a reconstrução não emite) rodam cada grupo numa só
reprodução (as fixtures `reproducao_variada` e `reproducao_estragada`), lida por vários testes. Os
catálogos (esquemas e regras) são relidos centenas de vezes por reprodução, em YAML de Python puro:
os dois módulos de integração da reprodução leem cada texto YAML uma vez (`yaml_em_memoria`, em
`tests/fixtures/reproducao_fluxo.py`, só nos testes), o que tira cerca de 12 s do mundo e 7 s de
cada reprodução.

| Propriedade | Teste |
|---|---|
| 31 itens `IGUAL` e `resultado` `IGUAL`, com o `freeze` recusado sem G0 e exploratório com a decisão de teste | `test_reproduce_offline_reproduz_com_hashes_logicos_iguais` e `test_freeze_e_recusado_sem_g0_e_com_a_decisao_de_teste_fica_exploratorio` |
| Diretório novo e nenhum original alterado | `test_reproduce_refaz_o_fluxo_inteiro_no_diretorio_novo` e `test_reproduce_nao_altera_nenhum_original` |
| Split congelado com artefatos inspecionados é refeito com o mesmo `split_id` (o `_refazer` os repassa a `derivar_protocolo`) | `test_reproduce_refaz_o_split_com_os_artefatos_inspecionados_do_congelamento` e, em `tests/integration/test_reproduce_etapas.py`, os `test_derivar_protocolo_*inspecionado*` (gravação no split e recusa de inspecionado no TESTE ou sem fonte) |
| Coleta nova, republicação com outro conteúdo e ausência registradas depois do `ingest` não alteram a reprodução (igual, com a observação do que ficou de fora), seja qual for o instante da observação: depois do `freeze` ou antes dele, como uma coleta feita entre o `ingest` e o `freeze` | `test_reproduce_ignora_o_que_foi_coletado_depois_do_congelamento` e `test_reproduce_ignora_o_que_foi_coletado_entre_o_ingest_e_o_congelamento` (a reprodução padrão do módulo roda com seis coletas registradas depois do `ingest`, três de cada tipo de instante) e `tests/unit/test_reproduce_manifesto.py` (execução do `ingest` pelo SIA-PA congelado, mesma posição que não é ambiguidade, posição que o manifesto não tem, prefixo com a mesma cadeia e âncora) |
| Sem saber o que o `ingest` leu do manifesto (execução ausente, ambígua, sem posição, hash diferente, além do fim), a reprodução é inconclusiva no item `manifesto:aquisicao` e para antes do `ingest`, junto das entradas originais que não conferem | `test_reproduce_sem_saber_o_que_o_ingest_leu_do_manifesto_e_inconclusivo_e_nao_divergente` (cinco casos) e `test_reproduce_sem_o_ingest_original_relata_tambem_a_entrada_que_nao_confere` |
| Arquivo cuja competência difere da das linhas fica na janela e reproduz igual; partição sem artefatos é inconclusiva, não erro de configuração | `test_reproduce_mantem_na_janela_o_arquivo_cuja_competencia_difere_da_das_linhas`, `test_reproduce_com_particao_vazia_e_inconclusivo_e_nao_erro_de_configuracao` e os `test_janela_dos_artefatos_*` e `test_competencias_da_janela_*` de `tests/integration/test_reproduce_etapas.py` |
| 4 threads dão as mesmas saídas e métricas; bytes diferentes com hash lógico igual saem como tais nos conjuntos e nas partições (`conjunto:*` e `split:*`), e nas saídas (`saida:*`) os bytes não se comparam | `test_reproduce_com_4_threads_e_bytes_diferentes_nos_originais_segue_igual` |
| Divergência de conteúdo falha (saída 5) e nomeia os itens | `test_reproduce_falha_e_nomeia_os_itens_quando_o_conteudo_original_diverge` |
| Original do SIA-PA ausente é inconclusão (saída 5), não divergência nem reprodução | `test_reproduce_com_original_do_sia_pa_ausente_e_inconclusivo_e_nao_divergente` |
| CNES (PF e ST) ou SIGTAP ausente é inconclusão em `insumos:<politica>` (saída 5), sem item divergente, e o fluxo para antes de refazer | `test_reproduce_com_original_auxiliar_ausente_e_inconclusivo_e_nao_divergente` (uma execução por família) e `tests/unit/test_reproduce_insumos.py` |
| Saída registrada que a reconstrução não emitiu (`evidencias.v1`) diverge e a saída é 5; saída nova sem original, método só registrado e execução registrada ausente | `test_reproduce_com_saida_que_a_reconstrucao_nao_emitiu_e_divergente` e `tests/unit/test_reproduce_saidas.py` |
| Entrada original da política ausente, ilegível ou alterada é inconclusão em `insumos:<politica>` (saída 5), com o auxiliar disponível ou não, e o fluxo para antes de refazer | `test_reproduce_com_a_entrada_original_que_nao_confere_e_inconclusivo_e_nao_divergente` (três estragos e, na entrada ausente, também com o auxiliar indisponível) e `tests/unit/test_reproduce_insumos.py` |
| Cada método é refeito com a política da execução congelada dele, com a `politica_id` da config preenchida (como o `config/cohort.yaml`) ou vazia: reproduz igual nos três métodos; política congelada que o catálogo já não dá (mudada ou removida) é inconclusão em `insumos:<politica>`, nunca erro de configuração nem divergência | `test_o_congelamento_traz_a_politica_do_catalogo_em_m_temp_e_as_padrao_dos_baselines`, `test_reproduce_com_politica_id_na_config_refaz_cada_metodo_com_a_politica_congelada`, `test_reproduce_com_a_politica_congelada_que_o_catalogo_ja_nao_da_e_inconclusivo` (catálogo com a política mudada; a removida está no unitário), `tests/unit/test_reproduce_politicas.py` e, em `tests/integration/test_reproduce_etapas.py`, os `test_validar_janela_*` |
| O relatório lido só vale se bate com a entrada do registro (`report_id`, `freeze_id`, modo, origem dos dados, `decisao_g2`, execuções, métricas): relatório válido que não é o registrado é original indisponível (`metricas`, `notas` e `relatorio:campos` inconclusivos); método com duas execuções registradas fica sem original | `test_reproduce_com_relatorio_que_nao_e_o_registrado_e_inconclusivo_e_nao_divergente` e `tests/unit/test_reproduce_original.py` |
| A configuração com que o `ingest` original rodou (UF, corte, famílias, catálogo de fontes, leiaute) tem de ser a do refeito, e a `origem_dados` tem de ser a dos conjuntos congelados; senão inconclusão (`manifesto:aquisicao`, `origem_dados`) antes do `ingest`; catálogos que mudaram são observação | `test_reproduce_sem_saber_o_que_o_ingest_leu_do_manifesto_e_inconclusivo_e_nao_divergente` (casos `configuracao_diferente` e `sem_configuracao`), `test_reproduce_com_origem_dos_dados_diferente_da_congelada_e_inconclusivo`, `tests/unit/test_reproduce_manifesto.py` e `tests/unit/test_reproduce_catalogos.py` |
| O leiaute completo do Parquet (nomes, ordem e tipos) é conferido antes de projetar o hash: saída refeita sem `run_id`, com coluna a mais, de outro tipo ou em outra ordem é `DIVERGENTE`, nunca `IGUAL`; o mesmo vale para o original e entre as duas pontas | `tests/unit/test_reproduce_esquema.py`, os `test_saida_refeita_com_o_leiaute_estragado_*`, `test_saida_original_com_o_leiaute_estragado_*` e `test_conjunto_refeito_com_o_leiaute_estragado_*` de `tests/unit/test_reproduce_comparacao.py` e `test_reproduce_com_saida_refeita_sem_a_coluna_de_identidade_e_divergente_de_esquema` |
| Nenhuma comparação perde diferença por interseção, `get` com padrão ou colapso por chave: métrica repetida, campo só do congelamento, partição que só um lado traz, conjunto refeito que o manifesto não tem, saída repetida, campos do split e do relatório e linhagem | `tests/unit/test_reproduce_conjunto_completo.py` |
| Todo campo do `FreezeManifest`, da config, do `DatasetRef`, do `SplitManifest` e do `EvaluationReport` tem tratamento na varredura, cada comparação diz o que confere antes de projetar, e as tabelas das seções 5.5 e 5.6 são as do módulo | `tests/unit/test_reproduce_varredura.py` |
| Recusas: destino em uso ou arquivo, sem `--offline`, rede permitida, congelamento inexistente, confirmatório | os testes `test_reproduce_recusa_*`, `test_reproduce_exige_offline`, `test_reproduce_de_congelamento_inexistente_*` e `test_reproduce_nao_reproduz_congelamento_confirmatorio`, e `tests/unit/test_reproduce_recusas.py` |
| Nenhum socket de rede abre nem envia durante a reprodução (conexão, datagrama sem conexão, resolução de nome); `AF_UNIX` permitido; tudo restaurado, com ou sem exceção | `test_reproduce_roda_sob_a_guarda_de_rede`, `test_reproduce_recusa_datagrama_de_socket_aberto_antes_da_guarda`, `test_reproduce_recusa_abrir_socket_de_rede_sob_a_guarda` e `tests/unit/test_reproduce_rede.py` |
| Arquivo que a cadeia abre e não consegue ler (diretório no lugar, sem permissão, bytes que não decodificam ou truncados) nunca é traceback, `DIVERGENTE` nem `IGUAL` sem justificativa, e o resultado é o da tabela da seção 5.5: `INCONCLUSIVO` com o `reproducao.json` (originais), saída 2 com `chave=valor` (entradas da config e do repositório) ou falha operacional (registro adulterado); uma auditoria das aberturas falha se a cadeia abre arquivo sem linha na tabela | `tests/integration/test_reproduce_leituras.py` (um cenário por leitura e dano, os independentes juntos numa reprodução só), `tests/unit/test_reproduce_leituras.py` (a tabela e o runbook), `tests/unit/test_reproduce_leitura.py` (a tradução do que nenhum leitor trata), `tests/unit/test_reproducao_estragos.py` (os estragos e a restauração) e, nos leitores próprios, `tests/unit/test_reproduce_manifesto.py` (manifesto, âncora e trava) e `tests/unit/test_reproduce_original.py` (registro, relatório e execução) |
| Comparação por hash lógico, contagens e métricas; inconclusivo falha | `tests/unit/test_reproduce_comparacao.py` e `tests/unit/test_reproduce_conferencia.py` (split, originais, notas, ambiente e rodada registrada) |
| Sintético nunca é confirmatório | `test_sintetico_nunca_e_confirmatorio` |

### 5.5 O que a reprodução lê: de onde vem cada campo e como se confere

A reprodução refaz o que foi registrado, e o que ela não consegue conferir sai `INCONCLUSIVO`. Cada
campo do `FreezeManifest` e da config (inclusive os de `runtime` e `piloto`) tem aqui a fonte do
valor que a cadeia usa, como a diferença aparece em `reproducao.json` e o efeito; o mesmo vale
para os campos de `DatasetRef`, `SplitManifest` e `EvaluationReport`, que as comparações projetam ou
deixam de fora. As tabelas saem, linha a linha, de `sustemporal.reporting.reproduce_varredura`, e
`tests/unit/test_reproduce_varredura.py` falha se um campo novo dos contratos ficar sem tratamento
ou se uma linha daqui deixar de ser a do módulo.

- Fonte (de onde vem o valor que a cadeia usa): `CONGELAMENTO` (o manifesto), `REGISTRO` (o registro
  de rodadas), `ORIGINAL` (o que o `ingest` e o `validate` gravaram nas saídas originais), `CODIGO`
  (constante do código), `CONFIG` (a config de agora) e `NENHUMA` (a cadeia não o lê).
- Conferência (como a diferença aparece): `ITEM` (item de `reproducao.json`), `OBSERVACAO` (linha
  de `observacoes`; o conteúdo refeito decide), `INDIRETA` (só aparece em outro item, como a
  especificação do `bootstrap` nas `notas`), `RECUSA` (a reprodução recusa antes de refazer) e
  `NENHUMA` (nada o confere: limite declarado).

| Campo do `FreezeManifest` | Fonte | Conferência | Efeito |
|---|---|---|---|
| `freeze_id` | CONGELAMENTO | RECUSA | recomputado do conteúdo; adulterado ou de outro id sai 2 |
| `criado_em` | NENHUMA | NENHUMA | informativo; já não decide o manifesto de aquisição |
| `config_hash` | CONGELAMENTO | OBSERVACAO | `config_diferente_da_congelada`; o conteúdo decide |
| `codigo` | CONGELAMENTO | OBSERVACAO | `codigo_diferente_do_congelado`; o conteúdo decide |
| `ambiente` | CONGELAMENTO | OBSERVACAO | `pacotes_diferentes_do_congelado`; o conteúdo decide |
| `catalogos_sha256` | CONGELAMENTO | OBSERVACAO | `catalogos_diferentes_do_congelado` |
| `datasets` | CONGELAMENTO | ITEM | `conjunto:*` por hash lógico; acha o ingest e a origem |
| `split` | CONGELAMENTO | ITEM | `split:*`; a `spec` e os inspecionados vêm dele |
| `features` | NENHUMA | NENHUMA | a avaliação por regras não usa features |
| `bootstrap` | CONGELAMENTO | INDIRETA | o do manifesto vale; `metricas` e `notas` |
| `metricas` | CODIGO | INDIRETA | constante do código; `metricas` do relatório registrado |
| `comparacoes_primarias` | CODIGO | INDIRETA | constante do código; `notas` do relatório |
| `margens` | NENHUMA | NENHUMA | a avaliação não usa margens (T11 #2) |
| `decisao_g0` | NENHUMA | NENHUMA | só autoriza congelar |
| `catalogo_regras_sha256` | CONGELAMENTO | OBSERVACAO | `catalogo_de_regras_diferente_do_congelado` |
| `politicas_sha256` | CONGELAMENTO | ITEM | a política refeita é a congelada; senão `insumos:*` inconclusivo |
| `entradas_validacao` | CONGELAMENTO | ITEM | `insumos:*`: entrada original e identidade campo a campo |

| Campo da config | Fonte | Conferência | Efeito |
|---|---|---|---|
| `versao` | NENHUMA | NENHUMA | não lido pela cadeia |
| `modo` | REGISTRO | RECUSA | só o exploratório; a rodada é a do modo no registro |
| `origem_dados` | CONGELAMENTO | ITEM | `origem_dados` inconclusivo se difere dos conjuntos |
| `runtime.duckdb_memoria` | NENHUMA | NENHUMA | desempenho; o conteúdo não depende |
| `runtime.duckdb_threads` | NENHUMA | NENHUMA | desempenho; 1 e 4 threads dão o mesmo conteúdo |
| `runtime.raiz_dados` | ORIGINAL | ITEM | SHA-256 do bruto conferido pelo ingest; quarentena inconclusiva |
| `runtime.raiz_manifestos` | ORIGINAL | ITEM | só até a posição que o ingest leu (`manifesto:aquisicao`) |
| `runtime.raiz_saidas` | ORIGINAL | ITEM | ingest, `split/insumos`, relatório e execuções originais |
| `runtime.dir_congelamentos` | CONGELAMENTO | RECUSA | manifesto com id recomputado e registro encadeado |
| `runtime.rede_permitida` | NENHUMA | RECUSA | recusado (saída 6) |
| `runtime.verificacao_fidelidade` | NENHUMA | NENHUMA | limite: o ingest original não registra o modo |
| `piloto.uf` | ORIGINAL | ITEM | `configuracao_ingest.json`: `manifesto:aquisicao` |
| `piloto.competencias_processamento` | CONGELAMENTO | INDIRETA | a janela vem da partição; a cobertura na identidade |
| `piloto.territorio` | CONGELAMENTO | ITEM | `recorte_territorial` na identidade dos insumos |
| `piloto.familias_fontes` | ORIGINAL | ITEM | `configuracao_ingest.json`: `manifesto:aquisicao` |
| `vigilancia` | NENHUMA | NENHUMA | não lido: o piloto é exigido |
| `coorte` | CONFIG | INDIRETA | o `split_id` leva a coorte; diferente diverge |
| `particoes` | CONGELAMENTO | NENHUMA | a `spec` do manifesto vale; a da config é ignorada |
| `bootstrap` | CONGELAMENTO | NENHUMA | o do manifesto vale; o da config é ignorado |
| `metodos` | CODIGO | INDIRETA | refaz os três métodos; método sem registro diverge |
| `politica_id` | CONGELAMENTO | ITEM | cada método refaz com a política congelada dele |
| `semente` | NENHUMA | NENHUMA | não lida pela cadeia (o bootstrap tem a do manifesto) |
| `contrafactual` | NENHUMA | NENHUMA | não lido pela cadeia |
| `corte_observacao` | ORIGINAL | ITEM | `configuracao_ingest.json` e `snapshots` dos insumos |
| `freeze_id` | CONGELAMENTO | RECUSA | o da CLI; config com outro sai 2 |
| `catalogos` | CONGELAMENTO | ITEM | fontes e leiaute pelo ingest original; os demais, observação |

Campos que as comparações projetam ou deixam de fora (a fonte `ORIGINAL` é o conjunto do
congelamento ou a saída da execução registrada que se compara):

| Campo do `DatasetRef` | Fonte | Conferência | Efeito |
|---|---|---|---|
| `dataset_id` | ORIGINAL | INDIRETA | deriva de esquema, hash lógico e artefatos; o das saídas leva o `run_id` |
| `schema_id` | ORIGINAL | ITEM | pareia o item e dá o leiaute esperado: `esquema_divergente` |
| `caminho` | NENHUMA | NENHUMA | onde o arquivo está; o conteúdo decide |
| `hash_logico` | ORIGINAL | ITEM | recalculado do arquivo, nunca lido da referência |
| `linhas` | ORIGINAL | ITEM | recontada do arquivo: `refeito_diverge` |
| `artifact_ids` | ORIGINAL | ITEM | multiconjunto de artefatos: `linhagem_diverge` |
| `origem_dados` | CONGELAMENTO | ITEM | item `origem_dados`, antes de refazer |
| `produzido_por` | NENHUMA | NENHUMA | rótulo do código que gravou; o código diferente é observação |
| `reconciliacao` | ORIGINAL | INDIRETA | contagem derivada do conteúdo; o hash lógico cobre as linhas |
| `multiplicidade` | ORIGINAL | INDIRETA | contagem derivada do conteúdo; o hash lógico conta a repetição |

| Campo do `SplitManifest` | Fonte | Conferência | Efeito |
|---|---|---|---|
| `split_id` | CONGELAMENTO | ITEM | `split:split_id` |
| `spec` | CONGELAMENTO | ITEM | `split:campos`; a do manifesto é a que refaz |
| `dataset_hash` | CONGELAMENTO | ITEM | `split:campos` |
| `linhas_por_particao` | CONGELAMENTO | ITEM | `split:campos` |
| `hash_por_particao` | CONGELAMENTO | ITEM | `split:campos` |
| `artefatos_inspecionados` | CONGELAMENTO | ITEM | `split:campos`; vêm do manifesto e entram no `split_id` |
| `artefatos_teste` | CONGELAMENTO | ITEM | `split:campos` |
| `cohort_id` | CONGELAMENTO | ITEM | `split:campos` |
| `particoes` | CONGELAMENTO | ITEM | `split:particao:*`, pela união das chaves das duas pontas |
| `exclusoes` | CONGELAMENTO | ITEM | `split:campos` |
| `limites` | CONGELAMENTO | ITEM | `split:campos` |
| `rotulos_por_particao` | CONGELAMENTO | ITEM | `split:rotulos:*`, pela união das chaves das duas pontas |

| Campo do `EvaluationReport` | Fonte | Conferência | Efeito |
|---|---|---|---|
| `report_id` | REGISTRO | INDIRETA | o original só vale se bate com o registro; o refeito deriva do caminho |
| `modo` | REGISTRO | ITEM | `relatorio:campos` |
| `origem_dados` | REGISTRO | ITEM | `relatorio:campos` |
| `freeze_id` | REGISTRO | ITEM | `relatorio:campos` |
| `decisao_g2` | ORIGINAL | ITEM | `relatorio:campos` |
| `runs` | REGISTRO | ITEM | `relatorio:campos` só pela quantidade; os ids derivam do caminho |
| `metricas` | ORIGINAL | ITEM | `metricas`: multiconjunto por nome, estrato e valor |
| `tabelas` | ORIGINAL | ITEM | `relatorio:campos`: esquema, linhas e hash lógico |
| `notas` | ORIGINAL | ITEM | `notas`: multiconjunto |
| `criado_em` | NENHUMA | NENHUMA | instante da execução; o conteúdo decide |

Arquivos que a cadeia abre, o que os confere e o que acontece quando um deles não abre. As tabelas
saem, linha a linha, de `LEITURAS` (`sustemporal.reporting.reproduce_varredura`, definida em
`reproduce_leituras.py` por causa do limite de tamanho do arquivo): cada linha é um arquivo, ou um
grupo de arquivos do mesmo leitor, na ordem em que a cadeia os lê. Uma auditoria das aberturas de uma
reprodução (`tests/integration/test_reproduce_leituras.py`) falha se a cadeia abre arquivo sem linha
aqui. `config/splits.yaml` e `experiments/decisions` não entram: a cadeia não os lê (a especificação
do split vem do manifesto).

| Arquivo | Quem lê | Fonte | O que o confere |
|---|---|---|---|
| `<config>` | `load_config` | `--config` | ilegível ou inválida sai 2 antes de abrir outro arquivo |
| `<dir_congelamentos>/frz_*.json` | `carregar_freeze` | `--freeze` | id recomputado do conteúdo; ausente, ilegível, adulterado ou de outro id sai 2 |
| `<catalogos.fontes>` | `configuracao_do_ingest`, `ingest` | `catalogos.fontes` da config | SHA-256 na configuração gravada do `ingest`: ilegível sai 2; outro conteúdo, `manifesto:aquisicao` inconclusivo |
| `<piloto.territorio>` | `ingest`, `validate` | `piloto.territorio` da config | recorte territorial na identidade dos insumos; ilegível sai 2 |
| `<dir_congelamentos>/registro_execucoes.jsonl` | `ler_registro`, `rodada_registrada` | o congelamento e o modo | cadeia de hashes; adulterado é falha operacional; que não abre, não há original |
| `<raiz_saidas>/avaliacao/*/rep_*.json` | `ler_original` | o `report_id` do registro | tem de bater com a entrada do registro; senão, original indisponível |
| `<raiz_saidas>/runs/*/run_result.json` | `ler_original` | os `runs` do registro | `run_id` coerente com a pasta; que não abre, a execução fica sem original |
| `<raiz_saidas>/runs/*/*.parquet` | `comparar_execucoes` | as saídas do `run_result.json` | leiaute e hash lógico das cinco saídas; que não abre, `INCONCLUSIVO` |
| `<raiz_saidas>/split/ds_*.parquet` e `<raiz_saidas>/split/rotulos/ds_*.parquet` e `<raiz_saidas>/split/entradas/ds_*.parquet` | `comparar_referencia`, `comparar_split` | o `DatasetRef` do manifesto (caminho absoluto) | vale o hash declarado no congelamento; o arquivo original é a segunda conferência |
| `<raiz_saidas>/split/insumos/*.json` | `conferir_entradas`, `politicas_congeladas` | `entradas_validacao` e `politicas_sha256` | identidade campo a campo; a política, também contra a execução registrada |
| `<raiz_saidas>/ingest/execucao_*/datasets.jsonl` | `resolver_manifesto` | o SIA-PA congelado | acha a execução do `ingest` pelo SIA-PA; que não abre, a execução não é candidata |
| `<raiz_saidas>/ingest/execucao_*/manifesto_lido.json` | `resolver_manifesto` | a execução do `ingest` | linhas e hash da última linha do manifesto que o `ingest` leu |
| `<raiz_saidas>/ingest/execucao_*/configuracao_ingest.json` | `resolver_manifesto` | a execução do `ingest` | a configuração com que o `ingest` rodou tem de ser a do refeito |
| `<raiz_manifestos>/aquisicao.jsonl` | `resolver_manifesto`, `gravar_manifesto` | a posição que o `ingest` leu | prefixo até essa posição, com a cadeia e o hash da última linha; corrompido ou ilegível, a posição não se sabe |
| `<raiz_manifestos>/aquisicao.jsonl.ancora` | `Manifesto.ler` | o manifesto de aquisição | sequência e hash da última linha gravada; ilegível ou divergente é manifesto corrompido |
| `<raiz_manifestos>/aquisicao.jsonl.trava` | `Manifesto.ler` | o manifesto de aquisição | trava de leitura compartilhada; que não abre, o manifesto não se lê |
| `<raiz_dados>/raw/sha256/*/*.dbc` | o `ingest` refeito (SIA-PA, CNES) | o manifesto de aquisição | SHA-256 do bruto; ausente ou truncado, `originais_indisponiveis`; sem permissão, `ingest:originais` |
| `<raiz_dados>/raw/sha256/*/*.zip` | o `ingest` refeito (SIGTAP) | o manifesto de aquisição | SHA-256 do bruto; ausente ou truncado, `originais_indisponiveis`; sem permissão, `ingest:originais` |
| `<diretorio_de_trabalho>/catalog/schemas/selecao_versoes.yaml` | `validate` (`temporal.lote`) | o diretório de trabalho (T14-15) | esquema da seleção de versões; ilegível sai 2 |
| `catalog/familias.yaml` | `carregar_regras`, `build_coverage` | o repositório | famílias de fonte que as regras e a cobertura usam; ilegível sai 2 |
| `catalog/rules/*/*.yaml` | `carregar_regras` | o repositório | SHA-256 do catálogo no manifesto (observação); ilegível sai 2 |
| `catalog/schemas/sia_pa.yaml` e `catalog/schemas/cnes_estab_cbo.yaml` e `catalog/schemas/sigtap_proc_registro.yaml` e `catalog/schemas/sigtap_proc_ocupacao.yaml` e `catalog/schemas/sigtap_procedimento.yaml` | `carregar_regras` | o repositório | esquemas das tabelas que as regras leem; ilegível sai 2 |
| `catalog/policies/M_TEMP_PADRAO.yaml` e `catalog/policies/*.yaml` | `politicas_congeladas` | o repositório | a política congelada tem de ser a padrão do método ou a do catálogo de mesmo conteúdo |
| `catalog/layouts/sia_pa.yaml` | `configuracao_do_ingest`, `ingest` | `catalogos.leiaute_sia_pa` ou o repositório | SHA-256 na configuração gravada do `ingest`; ilegível sai 2 |
| `catalog/layouts/cnes.yaml` | o `ingest` refeito (CNES) | o repositório | leiaute dos arquivos do CNES; ilegível sai 2 |
| `catalog/layouts/sigtap.yaml` | o `ingest` refeito (SIGTAP) | o repositório | leiaute das tabelas do SIGTAP; ilegível sai 2 |
| `catalog/schemas/cnes_estabelecimento.yaml` e `catalog/schemas/sigtap_registro.yaml` | o `ingest` refeito (normalização do CNES ST e do SIGTAP) | o repositório | esquemas das tabelas normalizadas; sem abrir, sai 2; com bytes que não decodificam, o `ingest` põe o artefato em `FALHA_NORMALIZACAO` (`originais_indisponiveis`) |
| `catalog/schemas/cobertura.yaml` | `build_coverage` (o `ingest` refeito) | o repositório | esquema da tabela de cobertura; ilegível sai 2 |
| `catalog/labels/sia_pa.yaml` e `catalog/schemas/sia_pa_rotulos.yaml` | `derivar_protocolo` (rótulos) | o repositório | livro de códigos dos rótulos do SIA-PA e o esquema deles; ilegível sai 2 |
| `catalog/schemas/selecao_versoes.yaml` e `catalog/schemas/agregados_registro.yaml` | `validate` | o repositório | esquemas das saídas da validação; ilegível sai 2 |
| `catalog/schemas/avaliacoes.yaml` e `catalog/schemas/evidencias.yaml` e `catalog/schemas/falhas.yaml` | `identidade_do_arquivo` | o repositório | leiaute esperado de cada saída comparada; ilegível sai 2 |
| `<saida>/*` | o `ingest`, `derivar_protocolo`, `validate` e a avaliação refeitos | a própria reprodução | o que a reprodução grava e relê no destino novo |
| `<clone>/*.py` e `<clone>/*.pyc` e `<clone>/*.sql` | o interpretador, as regras em SQL | o clone | versão do código e pacotes em `observacoes_do_ambiente` (observação) |
| `<tmp>/tmp*` | o `ingest` refeito (descompressão do DBC) | o próprio processo | o conteúdo vem do bruto já conferido pelo SHA-256 |

A varredura estraga cada linha de três jeitos, de verdade no mundo temporário (os catálogos do clone
só falham na abertura, seção 5.3): diretório no lugar do arquivo, sem permissão e bytes que não
decodificam (texto) ou arquivo truncado (binário). Estraga o primeiro arquivo que a cadeia lê em
cada linha, com estas exceções: os três insumos, os conjuntos originais e as cinco saídas de um método
(o `B_ATEND`) saem juntos, a execução original é a do `M_TEMP`, e os brutos são os do SIA-PA, do CNES
PF e do CNES ST num cenário e o do SIGTAP noutro. Os arquivos independentes que só pesam no fim da
reprodução saem estragados juntos numa reprodução só; os que a param cedo rodam um por vez. O
resultado de cada dano (`saída 2`: erro com `chave=valor`;
`INCONCLUSIVO`: os itens de `reproducao.json` e a saída 5; `IGUAL` pelo hash declarado: o arquivo
original é só a segunda conferência, e sem ele vale o hash do congelamento; `—`: o dano não se
aplica, e o motivo está abaixo):

| Arquivo | Diretório no lugar | Sem permissão | Bytes ilegíveis |
|---|---|---|---|
| `<config>` | saída 2 | saída 2 | saída 2 |
| `<dir_congelamentos>/frz_*.json` | saída 2 | saída 2 | saída 2 |
| `<catalogos.fontes>` | saída 2 | saída 2 | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<piloto.territorio>` | saída 2 | saída 2 | saída 2 |
| `<dir_congelamentos>/registro_execucoes.jsonl` | `INCONCLUSIVO` (`metricas`, `notas`, `relatorio:campos`, `saida:*`), observação `registro_ilegivel` | `INCONCLUSIVO` (`metricas`, `notas`, `relatorio:campos`, `saida:*`), observação `registro_ilegivel` | falha operacional (saída 5) |
| `<raiz_saidas>/avaliacao/*/rep_*.json` | `INCONCLUSIVO` (`metricas`, `notas`, `relatorio:campos`) | `INCONCLUSIVO` (`metricas`, `notas`, `relatorio:campos`) | `INCONCLUSIVO` (`metricas`, `notas`, `relatorio:campos`) |
| `<raiz_saidas>/runs/*/run_result.json` | `INCONCLUSIVO` (`saida:*`) | `INCONCLUSIVO` (`saida:*`) | `INCONCLUSIVO` (`saida:*`) |
| `<raiz_saidas>/runs/*/*.parquet` | `INCONCLUSIVO` (`saida:*`) | `INCONCLUSIVO` (`saida:*`) | `INCONCLUSIVO` (`saida:*`) |
| `<raiz_saidas>/split/ds_*.parquet` e `<raiz_saidas>/split/rotulos/ds_*.parquet` e `<raiz_saidas>/split/entradas/ds_*.parquet` | `IGUAL` pelo hash declarado (`conjunto:*`, `split:particao:*`, `split:rotulos:*`) | `IGUAL` pelo hash declarado (`conjunto:*`, `split:particao:*`, `split:rotulos:*`) | `IGUAL` pelo hash declarado (`conjunto:*`, `split:particao:*`, `split:rotulos:*`) |
| `<raiz_saidas>/split/insumos/*.json` | `INCONCLUSIVO` (`insumos:*`) | `INCONCLUSIVO` (`insumos:*`) | `INCONCLUSIVO` (`insumos:*`) |
| `<raiz_saidas>/ingest/execucao_*/datasets.jsonl` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<raiz_saidas>/ingest/execucao_*/manifesto_lido.json` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<raiz_saidas>/ingest/execucao_*/configuracao_ingest.json` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<raiz_manifestos>/aquisicao.jsonl` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<raiz_manifestos>/aquisicao.jsonl.ancora` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `<raiz_manifestos>/aquisicao.jsonl.trava` | `INCONCLUSIVO` (`manifesto:aquisicao`) | `INCONCLUSIVO` (`manifesto:aquisicao`) | — |
| `<raiz_dados>/raw/sha256/*/*.dbc` | `INCONCLUSIVO` (`conjunto:*`, `insumos:*`) | `INCONCLUSIVO` (`ingest:originais`), observação `manifesto_do_ingest` | `INCONCLUSIVO` (`conjunto:*`, `insumos:*`) |
| `<raiz_dados>/raw/sha256/*/*.zip` | `INCONCLUSIVO` (`conjunto:*`, `insumos:*`) | `INCONCLUSIVO` (`ingest:originais`), observação `manifesto_do_ingest` | `INCONCLUSIVO` (`conjunto:*`, `insumos:*`) |
| `<diretorio_de_trabalho>/catalog/schemas/selecao_versoes.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/familias.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/rules/*/*.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/schemas/sia_pa.yaml` e `catalog/schemas/cnes_estab_cbo.yaml` e `catalog/schemas/sigtap_proc_registro.yaml` e `catalog/schemas/sigtap_proc_ocupacao.yaml` e `catalog/schemas/sigtap_procedimento.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/policies/M_TEMP_PADRAO.yaml` e `catalog/policies/*.yaml` | `INCONCLUSIVO` (`insumos:*`) | `INCONCLUSIVO` (`insumos:*`) | `INCONCLUSIVO` (`insumos:*`) |
| `catalog/layouts/sia_pa.yaml` | saída 2 | saída 2 | `INCONCLUSIVO` (`manifesto:aquisicao`) |
| `catalog/layouts/cnes.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/layouts/sigtap.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/schemas/cnes_estabelecimento.yaml` e `catalog/schemas/sigtap_registro.yaml` | saída 2 | saída 2 | `INCONCLUSIVO` (`insumos:*`) |
| `catalog/schemas/cobertura.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/labels/sia_pa.yaml` e `catalog/schemas/sia_pa_rotulos.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/schemas/selecao_versoes.yaml` e `catalog/schemas/agregados_registro.yaml` | saída 2 | saída 2 | saída 2 |
| `catalog/schemas/avaliacoes.yaml` e `catalog/schemas/evidencias.yaml` e `catalog/schemas/falhas.yaml` | saída 2 | saída 2 | saída 2 |

Fora da varredura de danos, com o motivo:

- `<raiz_manifestos>/aquisicao.jsonl.trava`: o conteúdo não conta, só a abertura do arquivo de trava
- `<saida>/*`: o destino é novo e vazio (`reproduce_destino_nao_vazio`; que não se lista ou não se cria sai 2, `reproduce_destino_ilegivel`): nada de fora o estraga antes de a reprodução gravá-lo, e o que se perde durante a execução sai falha operacional (`reproduce_saida_ilegivel`)
- `<clone>/*.py` e `<clone>/*.pyc` e `<clone>/*.sql`: é o código que roda: a instalação do pacote não é entrada da reprodução
- `<tmp>/tmp*`: temporário que o próprio processo grava e lê na mesma chamada

Limites que ficam (T14-16 em `docs/PENDENCIAS.md`). Nenhum deles dá `IGUAL` falso: a diferença
vira observação e o conteúdo refeito decide, ou o item sai `INCONCLUSIVO` ou `DIVERGENTE`.

- A guarda de rede (`reproduce_rede`) vale para o módulo `socket` do Python no processo. Extensão em
  C que abra socket nativo, o `_socket` usado direto, o descritor cru de um socket aberto
  (`os.write`, `os.sendfile`), o socket TLS (`ssl.SSLSocket`) aberto antes da guarda, que escreve
  pelo OpenSSL sem passar pelos métodos de `socket.socket` (a CLI não o abre), e subprocesso ficam
  fora; o autoload de extensões do DuckDB está
  desligado pela config (`autoinstall_known_extensions` e `autoload_known_extensions` em
  `sustemporal.duck.conectar`). Para isolamento de verdade, rode a reprodução em ambiente sem rede.

- `metodos` da config: o `reproduce` sempre refaz os três métodos de validação por regras. Método
  refeito sem execução registrada sai `INCONCLUSIVO` (`original_ausente`); método só registrado
  sai `DIVERGENTE` (`saida_ausente_no_refeito`).
- `runtime.verificacao_fidelidade`: o `ingest` original não registra o modo (`COMPLETA`, `AMOSTRAL`
  ou `DESLIGADA`). Se a config de agora usa outro, a diferença só aparece pelo efeito: artefato que
  passa a ir para a quarentena (`INCONCLUSIVO`, `originais_indisponiveis`) ou conjunto com linhas a
  mais ou a menos (`DIVERGENTE`). Gravá-lo em `configuracao_ingest.json` é do `ingest` (T14-16).
- `features`, `margens` e `decisao_g0` do manifesto, `semente`, `contrafactual`, `vigilancia` e
  `versao` da config: a avaliação por regras e a cadeia não os leem; ficam sem conferência.
- `metricas` e `comparacoes_primarias` do manifesto são constantes do código: só a diferença das
  `metricas` e das `notas` do relatório registrado as revela.
- `coorte` e `particoes` da config: o split refeito usa a coorte da config e a `spec` do manifesto;
  coorte diferente muda o `split_id` e diverge.
- A posição do manifesto de aquisição e as execuções do `ingest` vêm do `ingest` original, e supõe-se
  que o `validate` e o `freeze` leram o manifesto onde ele o leu (seção 5.3). O desenho de fechar
  isso no `FreezeManifest` está em T14-16.

### 5.6 O que cada comparação confere antes de projetar

Toda comparação que projeta, filtra ou ignora colunas ou campos confere antes o conjunto completo,
e nenhuma diferença some por interseção, por `get` com padrão ou por colapso por chave (a coluna de
identidade que o hash ignora, a partição ou o conjunto que só um lado traz, a métrica ou a saída
repetida, o campo que só o congelamento tem). A tabela sai de `COMPARACOES` em
`sustemporal.reporting.reproduce_varredura`.

| Item de `reproducao.json` | Confere antes de projetar | Fica de fora |
|---|---|---|
| `conjunto:*` | o leiaute (nomes, ordem e tipos) do refeito, do original e entre os dois; os esquemas pela união do manifesto e dos refeitos (`sem_etapa`, `conjunto_nao_congelado`); linhas, hash lógico e linhagem | `caminho` e `produzido_por` |
| `split:split_id` | o id, que leva a especificação, a coorte, as fontes, os rótulos e os artefatos inspecionados | nada |
| `split:campos` | todos os campos do manifesto do split, menos o id e as referências; campo novo do contrato entra sozinho | nada |
| `split:particao:*` | as partições da população pela união das chaves (`particao_ausente`, `particao_sem_original`, `particao_nao_congelada`) e, em cada uma, o leiaute, o hash lógico e a linhagem | `caminho` e `produzido_por` |
| `split:rotulos:*` | as partições dos rótulos, como `split:particao:*` | `caminho` e `produzido_por` |
| `saida:*` | o leiaute completo dos dois lados, inclusive a coluna `run_id`; os esquemas e os métodos pela união; a saída repetida (`<esquema>#2`); o hash lógico e a linhagem | os valores de `run_id`, que derivam do caminho, e só depois do leiaute; e os bytes do arquivo, que o `run_id` gravado muda por construção |
| `insumos:*` | a união dos campos da identidade da entrada: o campo só do congelamento, ou só da entrada refeita, é divergência | nada |
| `metricas` | o multiconjunto de (nome, estrato, valor): a métrica repetida conta cada vez | nada |
| `notas` | o multiconjunto das notas: a nota repetida conta cada vez | nada |
| `relatorio:campos` | `modo`, `origem_dados`, `freeze_id`, `decisao_g2`, a quantidade de execuções e as tabelas (esquema, linhas e hash lógico); campo novo do contrato entra sozinho | `report_id`, `criado_em` e os ids das execuções (derivam do caminho e do relógio); `metricas` e `notas` têm item próprio |

Fora desta tabela, de propósito: a `RunResult` das execuções (`entradas`, `snapshot_set_id`,
`politica_id`, `semente`, `config_hash`, `estado`...) não é comparada campo a campo; o conteúdo das
saídas decide, a linhagem das saídas confere os artefatos de origem, os insumos têm a identidade
campo a campo (`insumos:*`) e o código, o ambiente e a config diferentes são observação. O registro de
rodadas só vale com um relatório que bata com ele (inclusive a `decisao_g2`), e o método com duas
execuções registradas fica sem execução original, com a observação `execucao_registrada_repetida`,
em vez de a última substituir a primeira.

## 6. Onde ficam saídas e manifestos

Os caminhos vêm de `runtime` na configuração; os padrões (`RuntimeConfig`) são relativos ao
diretório de trabalho e ficam fora do Git (`.gitignore`: `data/*`, `outputs/*`).

| Conteúdo | Chave | Padrão | Observação |
|---|---|---|---|
| Originais imutáveis | `raiz_dados` | `data/` | `raw/sha256/<2 primeiros>/<sha256>.<ext>`, endereçados pelo hash |
| Manifestos | `raiz_manifestos` | `manifests/` | `aquisicao.jsonl` (append-only), `.ancora`, `.trava` (o `.gitignore` ignora `*.trava`); `vigilancia.jsonl` |
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
procuram execuções, todos por `raiz_execucoes(config)` (leitor comum `sustemporal.execucoes`, que
exige o `run_id` exato). `--saida DIR` desvia a gravação, e então a execução não é achada por
eles.

**Execução imutável (#36).** O `run_id` não inclui a versão do código: antes de gravar, o motor lê o
`run_result.json` que já exista em `<raiz_saidas>/runs/<run_id>/` e recusa com saída 2 quando ele
registra outro código (`execucao_existente_com_outro_codigo`) ou não pode ser lido
(`execucao_existente_ilegivel`); o mesmo código regrava de forma idempotente
(`docs/method/model.md` §7). Para reavaliar os mesmos insumos com outro código, use outro destino
(`--saida`). O `reproduce` grava em `<saida>/runs/` novo e nunca regrava uma execução, então não
esbarra na recusa. Com `--saida` dentro do checkout e fora de pasta ignorada, a segunda execução
igual vê o resultado anterior como árvore suja e é recusada (ORQ-37 em `docs/PENDENCIAS.md`).

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
três políticas (`M_TEMP_PADRAO`, `b_atend_exploratoria` e `b_proc_exploratoria`),
escolhendo a execução de `validate --ingest` cuja entrada é a população da partição TESTE. O
M_TEMP do mundo usa a `M_TEMP_PADRAO` do catálogo, que não é a padrão do método
(`m_temp_nao_resolvida`): a CLI só escolhe a política por `config.politica_id`, que o `validate`
recusa em outro método, e o script troca a padrão do M_TEMP só enquanto valida o original. É o que
faz o `reproduce` refazer cada método com a política congelada dele (seção 5.1), e o fluxo roda
também com a config no estilo do `config/cohort.yaml`, com `politica_id: M_TEMP_PADRAO`. O
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
