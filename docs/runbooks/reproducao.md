# Reprodução por um terceiro (T14)

Roteiro para reproduzir o fluxo documentado em ambiente limpo, sem dados reais e sem rede depois
da instalação. Tudo aqui usa dados sintéticos gerados por código (`origem_dados: SINTETICO`): o
resultado verifica o software e **não é resultado empírico** (`docs/method/claims.md`). Dados
reais nunca entram no Git; as etapas que exigem rede ou dados reais estão na seção 7. O piloto
real tem o roteiro próprio em `docs/runbooks/piloto_local.md`.

## 1. Escopo e limites

- Reproduz-se: instalação travada, verificação do repositório (seção 3), fluxo da CLI sobre dados
  sintéticos (seção 4) e, na parte B da T14, a reprodução offline de um congelamento (seção 5).
- Não se reproduz aqui: aquisição das fontes oficiais, piloto G0, comparações do teste, anotação
  humana e escala (seção 7).
- Estado do repositório: pré-G0. Nenhuma decisão G0, G1 ou G2 existe em `experiments/decisions/`;
  por isso `freeze` é recusado e nenhuma execução sintética é confirmatória.
- Verificado em 2026-10-05 num clone novo de `main` (commit `c26ae52`), em Linux x86_64.

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
cerca de 17 minutos, com mais de 3.200 testes (medido em 2026-10-05); o tempo varia com a máquina.

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

### 4.4 Contrafactual, portões e comandos que dependem de outros PRs

```bash
uv run sustemporal --nivel-log WARNING counterfactual --config "$CFG" --run "$RUN" --row "$ROW"
echo "counterfactual: $?"
uv run sustemporal --nivel-log WARNING freeze --config "$CFG"; echo "freeze: $?"
```

O `counterfactual` sai com **2** (`contrafactual_sem_violacao`): a busca exige um registro com
regra em `VIOLACAO`, e o registro sintético deste fluxo só tem `CONFORME` e `INCONCLUSIVO`. Mesmo
com violação, uma execução `--ingest` não traz o CNES ST das precondições (o `validate --ingest`
grava só os auxiliares que as regras exigem), e a busca sai `SEM_OPERACAO_ADMISSIVEL` (ORQ-24 em
`docs/PENDENCIAS.md`). A parte B usa linhas com violação.

O `freeze` sai com **4** (`portao_sem_decisao portao=G0`): congelar exige uma decisão G0 humana
em `experiments/decisions/`, que nenhum agente cria; é o comportamento esperado. Uma execução
sintética nunca é confirmatória: `evaluate` sem `--exploratory` exige configuração confirmatória,
que exige dados reais e G2.

Estado dos demais comandos em `main` (commit `c26ae52`, 2026-10-05): `evaluate` sai com 3
(`comando_nao_implementado`) até o PR #29 (T11: `evaluate`, `freeze` e registro) entrar, e
`annotation-export` sai com 2 (`congelamento_ausente`) sem um congelamento. A parte B da T14
reescreve este item com o fluxo completo.

### 4.5 Aceite da reprodução

1. `bash scripts/ci.sh` termina com 0.
2. Os passos 4.2 e 4.3 terminam com 0 e deixam `relatorio.json`, os três `run_result.json` e o
   `explicacao.txt` descritos acima.
3. O `counterfactual` da seção 4.4 sai com 2 e o `freeze` com 4.

## 5. Reprodução offline de um congelamento (`sustemporal reproduce --freeze ID --offline`)

**PARTE B da T14: seção a preencher quando o PR #29 estiver em `main`.** Contrato previsto (plano,
§9 e T14):

- o `freeze_id` resolve os artefatos exatos do congelamento, nunca um diretório "latest";
- `--offline` recusa qualquer acesso remoto;
- o fluxo pequeno é refeito a partir dos originais locais até as tabelas finais;
- hashes lógicos e contagens ou métricas são comparados; diferença de bytes Parquet com hash
  lógico igual é relatada como tal, e diferença de conteúdo é falha explícita, com saída diferente
  de zero.

Hoje `reproduce` sai com 3 (`comando_nao_implementado`).

## 6. Onde ficam saídas e manifestos

Os caminhos vêm de `runtime` na configuração; os padrões (`RuntimeConfig`) são relativos ao
diretório de trabalho e ficam fora do Git (`.gitignore`: `data/*`, `outputs/*`).

| Conteúdo | Chave | Padrão | Observação |
|---|---|---|---|
| Originais imutáveis | `raiz_dados` | `data/` | `raw/sha256/<2 primeiros>/<sha256>.<ext>`, endereçados pelo hash |
| Manifestos | `raiz_manifestos` | `manifests/` | `aquisicao.jsonl` (append-only), `.ancora`, `.trava`; `vigilancia.jsonl` |
| Saídas | `raiz_saidas` | `outputs/` | `ingest/`, `pilot/`, `runs/`, `validacao/`, `explicacoes/`, `anotacao/` |
| Congelamentos | `dir_congelamentos` | `experiments/frozen/` | `<freeze_id>.json`, resolvido pelo id |
| Decisões G0, G1, G2 | fixo | `experiments/decisions/` | só humanos; `MODELO_*` nunca libera portão |
| Decisões sobre alegações | fixo | `experiments/decisions/alegacoes/` | só humanos; vale a decisão mais recente de cada alegação |

Cada execução grava sob um id que resolve artefatos exatos (`execucao_<instante>_<id>`,
`val_<hash>`), sem diretório "latest" mutável. O manifesto de aquisição guarda cada observação,
inclusive a repetida; os hashes lógicos dos conjuntos ficam em `datasets.jsonl` e nos
`run_result.json`.

**Destino do `validate`.** `validate --ingest` grava em `<raiz_saidas>/runs/<run_id>/`, onde o
`explain` e o `evaluate` procuram as execuções. `validate --entrada` grava em
`<raiz_saidas>/validacao/` por padrão; para o `evaluate` enxergar essa execução, rode com
`--saida <raiz_saidas>/runs`. O `counterfactual` procura só em `runs/` e `validacao/`: uma
execução gravada com `--saida` em outro diretório não é achada. Alinhar os destinos no código é
pendência do orquestrador (ORQ-21 e ORQ-23 em `docs/PENDENCIAS.md`).

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
