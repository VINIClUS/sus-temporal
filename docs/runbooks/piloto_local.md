# Piloto local (T05) — execução na máquina do pesquisador

Roteiro para rodar o piloto G0 com dados reais fora do CI. Dados reais nunca entram no Git; o
repositório só traz código, catálogo e fixtures sintéticas. Método: `docs/method/observability.md`.

## 0. Preparação

```bash
uv sync --locked
export SUSTEMPORAL_REAL_DATA_DIR=/caminho/fora/do/repositorio
mkdir -p "$SUSTEMPORAL_REAL_DATA_DIR"
cp config/pilot.yaml config/runtime.yaml "$SUSTEMPORAL_REAL_DATA_DIR/"
export CFG="$SUSTEMPORAL_REAL_DATA_DIR/pilot.yaml"
export RAIZ_DADOS="$SUSTEMPORAL_REAL_DATA_DIR/dados"
export RAIZ_MANIFESTOS="$SUSTEMPORAL_REAL_DATA_DIR/manifestos"
export RAIZ_SAIDAS="$SUSTEMPORAL_REAL_DATA_DIR/saidas"
```

`config/pilot.yaml` herda de `runtime.yaml` (`base: runtime.yaml`), procurado no diretório da
própria cópia: por isso os dois arquivos vão juntos. Em `$CFG`, defina `runtime.raiz_dados`,
`runtime.raiz_manifestos` e `runtime.raiz_saidas` com os mesmos caminhos de `RAIZ_DADOS`,
`RAIZ_MANIFESTOS` e `RAIZ_SAIDAS` (o YAML não expande variáveis) e ajuste `duckdb_memoria` e
`duckdb_threads` à memória física. A rede só é permitida na aquisição (`rede_permitida: true` no
perfil do piloto). Para uma coorte explícita, acrescente o bloco `coorte` de `config/cohort.yaml`,
com a mesma UF do `piloto` (a pertença `HISTORICA` é recusada: ainda não há pertença versionada);
sem ele, o relatório usa a UF, o território e o intervalo das competências do `piloto`. Rode todos
os comandos na raiz do repositório: `piloto.territorio` e os trechos da seção 2 leem `catalog/`
por caminho relativo.

## 1. Aquisição, em duas rodadas com a ingestão do SIA-PA no meio

A passada auxiliar pede o CNES e o SIGTAP das competências de atendimento que os registros do
SIA-PA trazem. Essas competências saem da ingestão do SIA-PA e nunca são presumidas (plano §2,
G0): não se supõe que os arquivos do mesmo mês bastem. A ordem completa é:

1. passada primária (SIA-PA) e passada de documentos (1.1);
2. conferência do leiaute do SIA-PA (seção 2) e `ingest` (seção 3), que nesse ponto só tem o
   SIA-PA;
3. `atendimento.txt` derivado dessa ingestão (1.2);
4. passada auxiliar com esse arquivo (1.3);
5. conferência dos leiautes do CNES e do SIGTAP (seção 2), novo `ingest` e `pilot-report`
   (seção 3).

Saída 5 (`FALHA_OPERACIONAL`) em qualquer passada indica tentativa não obtida ou competência fora
da listagem: a falha fica no manifesto e reaparece no relatório como inconclusivo classificado.

### 1.1 Passadas primária e de documentos

```bash
uv run sustemporal acquire --config "$CFG"                       # SIA-PA das seis competências
uv run sustemporal acquire --config "$CFG" --passada documentos  # documentos do catálogo
```

A passada de documentos guarda as páginas e os PDFs listados em `documentos` de
`catalog/sources.yaml` (W1–W9, O4 e O5), com o SHA-256 no manifesto. Em seguida, confira o
leiaute do SIA-PA (seção 2) e rode o `ingest` (seção 3).

### 1.2 Competências de atendimento derivadas da ingestão

`atendimento.txt` tem uma competência de atendimento AAAAMM por linha: as distintas das linhas
não deletadas do SIA-PA na execução mais recente do `ingest` (só as preenchidas), inclusive meses
anteriores a 2018 que os registros trouxerem.

```bash
uv run python - "$RAIZ_SAIDAS" > "$SUSTEMPORAL_REAL_DATA_DIR/atendimento.txt" <<'PY'
import json
import sys
from pathlib import Path

import duckdb

execucoes = sorted((Path(sys.argv[1]) / "ingest").glob("execucao_*/datasets.jsonl"))
refs = [json.loads(linha) for linha in execucoes[-1].read_text(encoding="utf-8").splitlines()]
caminhos = [r["caminho"] for r in refs if r["schema_id"] == "sia_pa.v1"]
consulta = (
    "SELECT DISTINCT competencia_atendimento FROM read_parquet($c) "
    "WHERE NOT deletado AND competencia_atendimento IS NOT NULL ORDER BY 1"
)
for (competencia,) in duckdb.execute(consulta, {"c": caminhos}).fetchall():
    print(competencia)
PY
```

### 1.3 Passada auxiliar

```bash
uv run sustemporal acquire --config "$CFG" --passada auxiliar \
  --competencias-atendimento "$SUSTEMPORAL_REAL_DATA_DIR/atendimento.txt"
```

Para cada família auxiliar do piloto, a passada pede a união das competências de atendimento do
arquivo com as de processamento do piloto. Depois, confira os leiautes do CNES e do SIGTAP
(seção 2) e rode de novo o `ingest`, seguido do `pilot-report` (seção 3).

## 2. Conferir os leiautes contra os cabeçalhos reais (antes de cada `ingest`)

Os leiautes do SIA-PA e do CNES são `INFERIDA`/`SECUNDARIA` e `A_CONFIRMAR`; o leitor é estrito
(ADR 0002), então um leiaute errado manda o arquivo para `QUARENTENA_LEIAUTE`. Antes de cada
`ingest`, compare o cabeçalho de cada arquivo obtido com o catálogo: o SIA-PA depois da passada
primária, o CNES e o SIGTAP depois da auxiliar. SIA-PA:

```bash
uv run python - "$RAIZ_DADOS" "$RAIZ_MANIFESTOS/aquisicao.jsonl" <<'PY'
import sys
from pathlib import Path

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import FamiliaFonte, LayoutSpec
from sustemporal.ingest.dbc import descomprimir_dbc
from sustemporal.ingest.dbf import ler_cabecalho
from sustemporal.store import caminho_conteudo
from sustemporal.yamlio import carregar_yaml

raiz_dados, manifesto = Path(sys.argv[1]), Path(sys.argv[2])
leiaute = LayoutSpec.model_validate(carregar_yaml(Path("catalog/layouts/sia_pa.yaml")))
esperado = [(c.nome_fisico, c.tipo_fisico, c.largura, c.decimais) for c in leiaute.campos]
for versao in Manifesto(manifesto).ler().versoes.values():
    if versao.chave.fonte is not FamiliaFonte.SIA_PA or versao.chave.tipo_conteudo is not None:
        continue
    extensao = versao.formato.value.lower()
    dados = caminho_conteudo(raiz_dados / "raw", versao.sha256, extensao).read_bytes()
    dbf = descomprimir_dbc(dados)[0] if extensao == "dbc" else dados
    lidos = [(c.nome, c.tipo, c.largura, c.decimais) for c in ler_cabecalho(dbf).campos]
    divergentes = [(e, lido) for e, lido in zip(esperado, lidos) if e != lido]
    print(versao.chave.nome_original, versao.sha256, f"campos={len(lidos)}", divergentes)
PY
```

Cada linha mostra o arquivo, o SHA-256, o número de campos (54, 60 ou 61 são aceitos) e as
posições divergentes (nome, tipo, largura, decimais). CNES: `catalog/layouts/cnes.yaml` é uma
lista (`leiautes:`) com um leiaute por família, lida por `carregar_leiautes_cnes()`; o PF tem 40
campos (`SECUNDARIA`), o ST é `INFERIDA` do PF, e SR e HB são famílias reservadas, sem leiaute:

```bash
uv run python - "$RAIZ_DADOS" "$RAIZ_MANIFESTOS/aquisicao.jsonl" <<'PY'
import sys
from pathlib import Path

from sustemporal.acquisition.manifest import Manifesto
from sustemporal.ingest.cnes import carregar_leiautes_cnes
from sustemporal.ingest.dbc import descomprimir_dbc
from sustemporal.ingest.dbf import ler_cabecalho
from sustemporal.store import caminho_conteudo

raiz_dados, manifesto = Path(sys.argv[1]), Path(sys.argv[2])
leiautes = carregar_leiautes_cnes()
for versao in Manifesto(manifesto).ler().versoes.values():
    leiaute = leiautes.get(versao.chave.fonte)
    if leiaute is None or versao.chave.tipo_conteudo is not None:
        continue
    esperado = [(c.nome_fisico, c.tipo_fisico, c.largura, c.decimais) for c in leiaute.campos]
    extensao = versao.formato.value.lower()
    dados = caminho_conteudo(raiz_dados / "raw", versao.sha256, extensao).read_bytes()
    dbf = descomprimir_dbc(dados)[0] if extensao == "dbc" else dados
    lidos = [(c.nome, c.tipo, c.largura, c.decimais) for c in ler_cabecalho(dbf).campos]
    divergentes = [(e, lido) for e, lido in zip(esperado, lidos) if e != lido]
    nome = f"{versao.chave.fonte.value} {versao.chave.nome_original}"
    print(nome, versao.sha256, f"campos={len(lidos)}/{len(esperado)}", divergentes)
PY
```

SIGTAP: as posições vêm do `<tabela>_layout.txt` de cada zip; liste-os e compare com
`catalog/layouts/sigtap.yaml`:

```bash
uv run python -c "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); \
[print(n, z.read(n).decode('latin-1')) for n in z.namelist() if n.endswith('_layout.txt')]" \
  "$ARQUIVO_ZIP"
```

`ARQUIVO_ZIP` é o conteúdo do SIGTAP no armazenamento (`caminho_conteudo` sob `$RAIZ_DADOS/raw`).

### Atualizar o catálogo por PR

Divergência ou confirmação vira PR de humano (`humano/*`), nunca edição local silenciosa:

1. Corrija o campo em `catalog/layouts/<fonte>.yaml` conforme o cabeçalho real.
2. Troque `confirmacao: A_CONFIRMAR` por `CONFIRMADO` só para o que o cabeçalho comprova, com
   `proveniencia: OFICIAL_ARQUIVO`; o que continuar inferido mantém a marca original.
3. Registre a fonte em `docs/references/fontes.md`: nome do arquivo, competência, SHA-256 do
   conteúdo (o do manifesto), data da coleta e o trecho do cabeçalho (sem dados de pacientes).
4. Rode `bash scripts/ci.sh` e abra o PR. Só depois rode o `ingest`.

## 3. Ingestão e relatório

```bash
uv run sustemporal ingest --config "$CFG"        # depois da 1.1 e de novo depois da 1.3
uv run sustemporal pilot-report --config "$CFG"  # só depois do segundo ingest
```

O primeiro `ingest` (depois da 1.1) só tem o SIA-PA e serve para derivar `atendimento.txt` (1.2);
o segundo, depois da passada auxiliar, traz também o CNES e o SIGTAP. O `ingest` grava
`<raiz_saidas>/ingest/execucao_<instante>_<id>/` (Parquet, `datasets.jsonl`, `resultados.jsonl`,
`manifesto_lido.json`, `configuracao_ingest.json`). O `pilot-report` lê a execução completa mais
recente do `ingest` (com `datasets.jsonl`, `manifesto_lido.json` e `configuracao_ingest.json`;
pasta interrompida é ignorada com o aviso `pilot_report_ingest_incompleto`), seleciona as versões
(B_PROC e B_ATEND) e grava `<raiz_saidas>/pilot/execucao_<instante>_<id>/relatorio.json` mais as
tabelas `piloto_*.v1`.
Mudou a UF, o corte de observação, as famílias, `sources.yaml` ou o leiaute do SIA-PA depois do
`ingest`? O `pilot-report` recusa (saída 2, `ingest_com_configuracao_divergente campo=…`): rode o
`ingest` de novo com a configuração atual.
Revise `resultados.jsonl` (quarentenas, `FORA_DO_RECORTE`, `FORA_DO_CORTE`) antes de ler o
relatório. Competência com republicação de conteúdo divergente (`versoes_concorrentes` em
`piloto_exclusoes.v1` e nas notas) fica fora da população até a decisão humana de qual versão vale.

## 4. Registrar a execução

Para cada uma das seis competências de desenvolvimento, anote fora do Git: fontes auxiliares
necessárias, bytes obtidos, tempo de cada comando e os casos de defasagem
(`piloto_defasagem.v1`). Guarde os hashes de `relatorio.json` e das tabelas.

## 5. Decisão G0 (humana)

Copie `experiments/decisions/MODELO_G0.yaml` para `G0_<AAAA-MM-DD>.yaml`, preencha com base no
relatório real e registre por PR de humano. Separe limitação amostral de ausência estrutural com
os denominadores do relatório. Agentes não criam nem alteram decisões; o modelo nunca libera
portão. Revise o relatório com a orientação antes de ampliar o projeto.
