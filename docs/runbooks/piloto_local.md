# Piloto local (T05) — execução na máquina do pesquisador

Roteiro para rodar o piloto G0 com dados reais fora do CI. Dados reais nunca entram no Git; o
repositório só traz código, catálogo e fixtures sintéticas. Método: `docs/method/observability.md`.

## 0. Preparação

```bash
uv sync --locked
export SUSTEMPORAL_REAL_DATA_DIR=/caminho/fora/do/repositorio
```

Copie `config/pilot.yaml` para fora do repositório (ex.: `$SUSTEMPORAL_REAL_DATA_DIR/pilot.yaml`) e
defina `runtime.raiz_dados`, `runtime.raiz_manifestos` e `runtime.raiz_saidas` sob
`$SUSTEMPORAL_REAL_DATA_DIR`. Ajuste `duckdb_memoria` e `duckdb_threads` à memória física. A rede
só é permitida na aquisição (`rede_permitida: true` no perfil do piloto). Para uma coorte explícita,
acrescente o bloco `coorte` de `config/cohort.yaml`; sem ele, o relatório usa a UF, o território e o
intervalo das competências do `piloto`.

## 1. Aquisição

```bash
uv run sustemporal acquire --config "$CFG"                          # passada primária (SIA-PA)
uv run sustemporal acquire --config "$CFG" --passada auxiliar \
  --competencias-atendimento "$SUSTEMPORAL_REAL_DATA_DIR/atendimento.txt"
```

`atendimento.txt` tem uma competência de atendimento AAAAMM por linha, observada nos registros da
passada primária. Saída 5 (`FALHA_OPERACIONAL`) indica tentativa não obtida ou competência fora da
listagem: a falha fica no manifesto e reaparece no relatório como inconclusivo classificado.

## 2. Conferir os leiautes contra os cabeçalhos reais (antes do `ingest`)

Os leiautes do SIA-PA e do CNES são `INFERIDA`/`SECUNDARIA` e `A_CONFIRMAR`; o leitor é estrito
(ADR 0002), então um leiaute errado manda o arquivo para `QUARENTENA_LEIAUTE`. Antes do `ingest`,
compare o cabeçalho de cada arquivo obtido com o catálogo. Rode na raiz do repositório, com
`RAIZ_DADOS` = `runtime.raiz_dados` e `RAIZ_MANIFESTOS` = `runtime.raiz_manifestos`. SIA-PA
(troque o leiaute e a família para o CNES):

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
posições divergentes (nome, tipo, largura, decimais). SIGTAP: as posições vêm do
`<tabela>_layout.txt` de cada zip; liste-os e compare com `catalog/layouts/sigtap.yaml`:

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
uv run sustemporal ingest --config "$CFG"
uv run sustemporal pilot-report --config "$CFG"
```

O `ingest` grava `<raiz_saidas>/ingest/execucao_<instante>_<id>/` (Parquet, `datasets.jsonl`,
`resultados.jsonl`, `manifesto_lido.json`). O `pilot-report` lê a execução completa mais recente
do `ingest` (com `datasets.jsonl` e `manifesto_lido.json`; pasta interrompida é ignorada com o aviso
`pilot_report_ingest_incompleto`), seleciona as versões (B_PROC e B_ATEND) e grava
`<raiz_saidas>/pilot/execucao_<instante>_<id>/relatorio.json` mais as tabelas `piloto_*.v1`.
Revise `resultados.jsonl` (quarentenas, `FORA_DO_RECORTE`, `FORA_DO_CORTE`) antes de ler o
relatório.

## 4. Registrar a execução

Para cada uma das seis competências de desenvolvimento, anote fora do Git: fontes auxiliares
necessárias, bytes obtidos, tempo de cada comando e os casos de defasagem
(`piloto_defasagem.v1`). Guarde os hashes de `relatorio.json` e das tabelas.

## 5. Decisão G0 (humana)

Copie `experiments/decisions/MODELO_G0.yaml` para `G0_<AAAA-MM-DD>.yaml`, preencha com base no
relatório real e registre por PR de humano. Separe limitação amostral de ausência estrutural com
os denominadores do relatório. Agentes não criam nem alteram decisões; o modelo nunca libera
portão. Revise o relatório com a orientação antes de ampliar o projeto.
