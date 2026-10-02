# 0002 — Leitor DBC/DBF

## Status

Aceita (2026-10-01), sujeita ao teste de fidelidade nos arquivos reais, ainda pendente.

## Contexto

- **Plano.** Stack: "Adaptador de leitura DBC/DBF apoiado em biblioteca existente e verificado antes
  de uso; PySUS é a primeira candidata, não uma fonte de regras administrativas." O §3 exige revisão,
  licença compatível e teste de fidelidade para reaproveitar leitores. Arquivo ausente, truncado ou
  com leiaute incompatível vai para quarentena/inconclusão, nunca vira conjunto vazio lido como
  ausência cadastral (Foco de revisão, T02–T04). O adaptador é validado contra leitura independente,
  com biblioteca/versão registradas e sem filtros implícitos que removam não aprovados (T03). Rótulos
  são inspecionados antes e depois do pré-processamento para achar perdas da ferramenta (§2).
  `row_id` usa a posição do registro original, e códigos ficam como texto com zeros à esquerda (§4).
- **Formato DBC** (SECUNDARIA, código de referência S27–S30 de `docs/references/fontes.md`):
  - bytes `[0, H)` são o cabeçalho DBF, com `H` = uint16 little-endian no offset 8;
  - seguem 4 bytes descritos como CRC, que nenhum leitor avaliado verifica;
  - depois vem um fluxo PKWare DCL ("implode"), cuja descompressão é o restante do DBF. O fluxo
    começa com um byte 0/1 (literais não codificados/codificados) e um byte 4, 5 ou 6 (log2 do
    dicionário − 6), e termina num código de fim (comprimento 519 no `blast.c`);
  - o `DBC_FORMAT.md` do read.dbc põe o cabeçalho no offset 10, contra o próprio código. Vale o
    código.
- **Codificação desconhecida.** O fixture `PFSP2601.dbc` do CnesData tem byte de driver de idioma
  0x58, que o dbfread mapeia para cp1252, mas o CnesData decodifica em latin-1. O PySUS usa cp1252
  com `errors="replace"` (S3, S33). A_CONFIRMAR.
- **Escala.** Partes de SP chegam a 142,8 MB comprimidos (`PASP2301b`, S10).

## Candidatos avaliados

Metadados do PyPI de 2026-10-01 (S26); comportamento lido no código-fonte (S3, S27–S31).

| Candidato | Licença | Implementação e função | Comportamento em erro | Wheel py3.12 | Notas |
|---|---|---|---|---|---|
| PySUS 2.11.5 | GPL-3.0 | Python; aquisição FTP e leitura via pyreaddbc, com saída Parquet | Herda o pyreaddbc; decodifica cp1252 com `errors="replace"` | Pura; exige `>=3.11,<3.14` | Fixa pandas<3, typer>=0.24.1,<0.25, numpy>=2.4, python-dateutil==2.8.2, dbfread==2.0.7, duckdb<2, fastparquet<=2024.11.0 e pyreaddbc>=2.0.4; não trata SIGTAP |
| pyreaddbc 2.0.4 | AGPL-3.0 (`dbc2dbf.c`; o `blast.c` 1.2 é zlib) | Extensão C; só `dbc2dbf(infile, outfile) -> None` | Imprime mensagem e retorna `None`, sem exceção; ignora os 4 bytes; reescreve o último byte do cabeçalho com 0x0D | Sim (cp39–cp313) | O `read_dbc` do README só existe nos testes; sem compressor |
| datasus-dbc 0.1.3 | MIT | Rust; `decompress(in, out)` e `decompress_bytes(b) -> bytes` | Lê os 4 bytes sem verificar; reação a fluxo truncado não documentada | Sim (cp38–cp312; sem cp313/cp314) | Último release em 2024-04-16; usado pelo CnesData |
| dbc-to-dbf 1.0.1 | Zlib | Python puro, porte do `blast.c`; `DBCDecompress().decompress(bytes)` | Não documentado | Pura | Sem dependências |
| climasus-readdbc-py 0.2.0 | MIT | Python puro, porte do `blast.c` 1.3; `read_dbc(..., encoding="latin1")` | Não documentado | Pura | Exige pandas>=2.0; importa como `climasus_readdbc` (o README diz `readdbc`); copia o cabeçalho sem reescrita |
| readdbc 0.2.0 | MIT | Compila o `blast.c` via cffi no primeiro uso e traz um binário Linux | Não documentado | Rotulada pura, mas compila | Depende de simpledbf, sem release desde 2015 |
| dclimplode 0.0.1.0 | MIT | C++: `blast.c` + `implode.c` do StormLib; comprime e descomprime | — | Não (wheels até cp311; o build importa `distutils`, removido no 3.12) | `compressobj(type=1, dictsize=4096)`; o padrão é o modo ASCII, e o binário é 0 |
| read.dbc 1.2.0 (R) | AGPL-3 | C: `blast.c` + `implode.c` próprio; `dbf2dbc` comprime | — | Não se aplica (R ausente aqui) | `dbf2dbc` zera os 4 bytes e começa o fluxo com `00 06` |
| dbfread 2.0.7 | MIT | Python puro; lê DBF registro a registro | Decodificação estrita por padrão; com `encoding=None`, adivinha pelo byte 29 do cabeçalho e recorre a ascii | Pura | Último release em 2016-11-25; usado pelo CnesData |
| dbf 0.99.11 | BSD | Python puro; lê e escreve dBase/FoxPro | Não avaliado | Pura | Depende de aenum |

Descartados sem avaliação detalhada: dbc-reader 0.1.2 (chama binários empacotados), simpledbf 0.2.6
(sem release desde 2015) e pwexplode (GPL-3.0, fora do PyPI). No PyPI, `dbc` (instalador ADBC) e
`pydbc` (contratos para Python 2.2) não têm relação com o DBC do DATASUS.

## Critérios

1. **Licença**: a licença de publicação ainda não foi definida; para não restringi-la, nenhuma
   dependência GPL/AGPL, nem de teste. MIT, BSD, Zlib e Apache-2.0 são aceitas.
2. **Falha explícita**: erro vira exceção tipada e quarentena com motivo, nunca `None`, mensagem
   impressa, arquivo parcial ou tabela vazia.
3. **Independência**: o leitor de referência dos testes diferenciais não compartilha código com o
   de produção.
4. **Wheels para CPython 3.12** (manylinux), sem compilação na CI.
5. **Sem filtro implícito**: deletados, não aprovados, campos e bytes nunca somem sem contagem.
6. **Preservação**: índice físico, marcador de deleção e bytes de texto recuperáveis; nenhum byte do
   cabeçalho reescrito.

## Decisão

1. **Produção.** O datasus-dbc 0.1.3 descomprime (`decompress_bytes`). Um parser DBF próprio,
   estrito e vetorizado (NumPy, memmap, por blocos), lê os registros de largura fixa a partir dos
   descritores. Ele:
   - mantém índice físico e marcador de deleção de cada registro; deletados são contados e
     preservados com o marcador, nunca descartados em silêncio;
   - guarda campos como texto bruto, sem trim, padding ou conversão; Decimal e inteiro só surgem na
     normalização, com motivo (plano §4);
   - decodifica em latin-1, que é bijetiva (cada byte 0x00–0xFF ↔ um code point U+0000–U+00FF; os
     bytes originais são recuperáveis), registra o byte de driver de idioma (offset 29) e nunca usa
     `errors="replace"`; a codificação real fica A_CONFIRMAR e pode ser reaplicada sobre os bytes;
   - registra nome e versão de cada biblioteca usada na leitura (T03).
2. **Leitores independentes**, só em testes e verificação: dbc-to-dbf 1.0.1 para descomprimir
   (Python puro, base de código distinta da Rust) e dbfread 2.0.7 para o parsing. Usos: testes
   diferenciais sobre fixtures e verificação opcional de fidelidade em arquivos reais, que exige DBF
   descomprimido igual byte a byte, mesmos registros ativos e valores, e deletados = `n` − ativos.
3. **Fixtures.** Não há compressor DCL em Python puro no PyPI (dclimplode sem wheel para 3.12;
   read.dbc é R e AGPL-3). Os fixtures usam um codificador DCL de teste, em `tests/fixtures/` e nunca
   importado pela produção, que emite só literais não codificados (bytes iniciais `00 04|05|06`, cada
   literal como bit 0 + 8 bits, e o código de fim). Sua validade é provada por ida e volta em dois
   decodificadores (datasus-dbc e dbc-to-dbf), com Hypothesis. Um escritor DBF de teste gera
   deletados, presença ou ausência de 0x1A e truncamentos. Limite: literais não exercitam pares
   comprimento/distância; essa cobertura vem dos arquivos reais e, com OK do usuário, do
   `PFSP2601.dbc` do CnesData, cujo fluxo de 57 bytes (1.374 − 1.313 − 4) para ≥ 230 bytes de
   registros não pode ser só de literais não codificados (INFERIDA, por aritmética).
4. **Integridade.** Geram quarentena com motivo:
   - cabeçalho DBC ilegível ou `H` incoerente (conteúdo que não é DBC, como HTML, falha aqui);
   - fluxo DCL com bytes iniciais inválidos, sem código de fim, ou erro do descompressor;
   - ausência do terminador 0x0D ao fim dos descritores de campo;
   - tamanho físico do DBF ≠ `H + n × R` (+1 se terminar em 0x1A), com `n` e `R` do cabeçalho
     (precedente do CnesData, S33);
   - soma das larguras dos campos + 1 (marcador de deleção) ≠ `R` (INFERIDA do formato dBASE;
     conferida contra o dbfread nos testes);
   - descritores (nome, tipo, largura, ordem) diferentes do `LayoutSpec` do período: quarentena por
     leiaute, nunca conversão.

   Os 4 bytes pós-cabeçalho vão em hexadecimal para o manifesto, sem interpretação até haver
   especificação.
5. **PySUS fora das dependências**, desvio explícito da "primeira candidata" do plano: é GPL-3.0;
   fixa pandas<3 e typer<0.25, incompatíveis com as versões correntes; seu leitor, o pyreaddbc, é
   AGPL-3.0, falha em silêncio (imprime e retorna `None`), ignora os 4 bytes e reescreve um byte do
   cabeçalho (o que mascararia a checagem do terminador); e decodifica com `errors="replace"`. Pode
   ser usado à mão, em ambiente separado e com versão registrada, como verificação cruzada externa,
   nunca como dependência nem fonte de regra. pyreaddbc, read.dbc e pwexplode ficam fora pela
   licença; readdbc (compila em tempo de uso e traz binário), climasus-readdbc-py (exige pandas) e
   dbf não são necessários.

## Consequências

- **Python fixado em 3.12**: o datasus-dbc 0.1.3 só publica wheels até cp312 (S26). Para sair do
  3.12: compilar o datasus-dbc com Rust, como o CnesData faz em 3.13 (cargo/rustc 1.97.0 existem
  neste ambiente), ou promover o dbc-to-dbf à produção, mais lento, mantendo o datasus-dbc compilado
  como leitor independente.
- **Manutenção**: o datasus-dbc não tem release desde 2024-04-16; versão fixada com hash no
  `uv.lock`, e o diferencial expõe regressões.
- **Parser próprio**: código a manter, mitigado por testes diferenciais e de propriedade. Desempenho
  em arquivos estaduais medido em T13; nenhum ganho é afirmado.
- **Portão**: nenhum resultado do G0 usa dados lidos pelo adaptador antes do relatório de fidelidade
  do lote correspondente.
- **Pendências**: (1) fidelidade nos arquivos reais, com o diferencial e, se desejado, o PySUS
  externo; (2) leiautes A_CONFIRMAR (`docs/references/inventario_campos.md`); (3) codificação real
  do texto; (4) natureza dos 4 bytes pós-cabeçalho; (5) comportamento do datasus-dbc e do dbc-to-dbf
  com fluxo truncado ou corrompido; (6) OK do usuário para copiar `PFSP2601.dbc`.

## Referências

- Plano (`docs/plan/Plano_Implementacao_Validacao_Temporal_SUS.md`): stack, §2, §3, §4, T03 e Foco
  de revisão.
- `docs/references/fontes.md`: W9 (documentação do PySUS, lida via S4), S3, S10, S26–S31 e S33.
- `docs/references/inventario_campos.md`: leiautes e codificações a confirmar.
- ADR 0001 (stack e Python 3.12).
