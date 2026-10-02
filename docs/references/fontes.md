# Registro de fontes

Estado em 2026-10-01. Este registro diz de onde vem cada fato usado em `inventario_campos.md`, nas
ADRs e no catálogo. Os hosts `*.gov.br` e o FTP do DATASUS estão bloqueados neste ambiente de
desenvolvimento. Por isso nenhum documento oficial foi lido na íntegra nem preservado. Fatos e URLs
vêm dos levantamentos da fase de planejamento (2026-10-01). Os IDs abaixo (E, W*, O*, S*) são os
usados nos demais documentos.

## Rótulos de proveniência

| Rótulo | Significado | Situação atual |
|---|---|---|
| OFICIAL_DOCUMENTO | Documento oficial lido e preservado (cópia + SHA-256) | Nenhuma fonte |
| OFICIAL_VISTO_EM_BUSCA | URL oficial vista só em resultado de buscador; o texto devolvido é paráfrase, às vezes em inglês, não verbatim | W3, W5, W8, O2–O6, O10 |
| SECUNDARIA | Código, transcrição, inventário ou documentação de terceiros efetivamente lidos | W1, W9, S1–S32; o que se sabe de O1, O7–O9 e O11–O16 (para O7–O9, só a existência) |
| EMPIRICA_CNESDATA | Estrutura observada pelos autores do CnesData em arquivos reais | S33 (leiaute PF) |
| INFERIDA | Inferência deste projeto; sempre diz a partir de quê | — |
| A_CONFIRMAR | Conferir contra documento oficial preservado ou arquivo real no piloto | Todo fato que não seja OFICIAL_DOCUMENTO |

Nos catálogos vale o vocabulário de `AGENTS.md` (Proveniência). Ali EMPIRICA_CNESDATA conta como
SECUNDARIA, e A_CONFIRMAR é um estado de `Confirmacao`, não uma proveniência.

## Regras de uso

1. Hierarquia: OFICIAL_DOCUMENTO > OFICIAL_VISTO_EM_BUSCA > SECUNDARIA e EMPIRICA_CNESDATA >
   INFERIDA. A fonte oficial prevalece sobre a secundária. Concordância entre secundárias aumenta a
   confiança, mas não as torna oficiais.
2. Todo fato SECUNDARIA, EMPIRICA_CNESDATA ou INFERIDA é A_CONFIRMAR até ser conferido contra
   documento oficial preservado ou arquivo real preservado.
3. Nunca apresentar como oficial um leiaute, lista de códigos ou trecho normativo secundário ou
   inferido. Todo item levado a `catalog/` mantém rótulo e ID de fonte.
4. OFICIAL_VISTO_EM_BUSCA só orienta a busca do documento e não é citação. Texto devolvido por
   buscador não vai entre aspas como se fosse do documento.
5. Citações de documento oficial devem ser curtas e trazer localizador (página ou seção) e o SHA-256
   da cópia preservada. Redistribuir o documento inteiro exige auditoria de direitos (plano T14).
6. Documentação corrente não comprova semântica histórica (plano, "Fontes e distinção de
   fundamento"). Aplicar um fato a 2018–2025 exige documento da época ou evidência nos arquivos do
   período; sem isso, a verificação fica INCONCLUSIVA.
7. Código de terceiros (microdatasus, PySUS, healthbR) não é fonte de regra administrativa (plano,
   stack).
8. Data de coleta não é data de publicação nem de vigência (plano, Restrições globais).

## A. Fontes citadas no plano (E, W1–W9)

Títulos e URLs estão como no plano. O snapshot está PENDENTE em todas: nenhuma cópia foi preservada.
Cada uma deve ser preservada na máquina do pesquisador com `sustemporal acquire` (comando planejado,
plano §9), registrando SHA-256, conforme o plano: "preservar uma cópia/versão na execução". O acesso
foi verificado por requisição HTTP neste ambiente em 2026-10-01.

| ID | Título e URL (como no plano) | Tipo e rótulo | Para que serve no projeto | Acesso neste ambiente | Snapshot |
|---|---|---|---|---|---|
| E | Esboço anexado, `Esboco_Validacao_Temporal_SUS_Vinicius_Santana(3).pdf`, especialmente §§2, 5, 6, 7 e 8 | Documento-base do pesquisador (não é fonte administrativa) | Objetivos, recorte, hipóteses e limites; prevalece sobre o plano no escopo científico | Ausente (arquivo local do pesquisador) | PENDENTE: copiar byte a byte para `docs/spec/esboco_original.pdf`, com SHA-256 (plano, cabeçalho) |
| W1 | Microdatasus, código `R/process_sia.R`, bloco `PA_INDICA`. `https://github.com/rfsaldanha/microdatasus/blob/master/R/process_sia.R` | Código de terceiros; SECUNDARIA (o plano o agrupa entre "fontes técnicas primárias") | Ponto de partida do codebook de PA_INDICA (0/5/6), plano §2 | Acessível via GitHub: `github.com` responde 403, e o conteúdo foi lido em `raw.githubusercontent.com` (ramo master, microdatasus 3.0.0); ver S1 | PENDENTE |
| W2 | DuckDB, Reading and Writing Parquet Files. `https://duckdb.org/docs/current/data/parquet/overview` | Documentação técnica do fornecedor | Leitura direta de Parquet com projeção e filtros, plano §3 | Bloqueado (`duckdb.org` sem resposta); fonte da página acessível via GitHub (`duckdb/duckdb-web`, `docs/current/data/parquet/overview.md`); ver S32 | PENDENTE |
| W3 | Ministério da Saúde, Manual do BPA, configuração de competência. `https://wiki.saude.gov.br/sia/index.php/BPA` | Wiki oficial; OFICIAL_VISTO_EM_BUSCA | Competência de apresentação/processamento distinta do mês de atendimento, plano §4 | Bloqueado; visto só em resultado de busca (paráfrase) | PENDENTE |
| W4 | W3C, PROV-DM, componentes e relações de proveniência. `https://www.w3.org/TR/prov-dm/` | Recomendação técnica W3C | Representação PROV (entidades, atividades, agentes; `used`, `wasGeneratedBy`, `wasDerivedFrom`, `wasAssociatedWith`), plano §6 | Bloqueado (`w3.org` sem resposta); nenhuma cópia lida | PENDENTE |
| W5 | Ministério da Saúde, CNES — Dúvidas Frequentes, competências fechadas. `https://wiki.saude.gov.br/cnes/index.php/D%C3%BAvidas_Frequentes` | Wiki oficial; OFICIAL_VISTO_EM_BUSCA (paráfrase em inglês) | Competência fechada não alterável pelo usuário (contrafactuais), plano §6 | Bloqueado; visto só em resultado de busca | PENDENTE |
| W6 | Scikit-learn, Cross-validation: evaluating estimator performance. `https://scikit-learn.org/stable/modules/cross_validation.html` | Documentação técnica | Dependência por grupos e validação temporal, plano §7 | Bloqueado (`scikit-learn.org` sem resposta); fonte acessível via GitHub (`scikit-learn/scikit-learn`, `doc/modules/cross_validation.rst`, ramo main), ainda não lida | PENDENTE |
| W7 | Ministério da Saúde, SIGTAP — Gerais, quantidade máxima. `https://wiki.saude.gov.br/sigtap/index.php/Gerais` | Wiki oficial; conteúdo A_CONFIRMAR (não visto neste levantamento, nem em busca) | Semântica de quantidade máxima por tratamento/atendimento, plano §5 | Bloqueado | PENDENTE |
| W8 | Ministério da Saúde, SIGTAP — Download, arquivos mensais e notas técnicas. `https://wiki.saude.gov.br/sigtap/index.php/Download` | Wiki oficial; OFICIAL_VISTO_EM_BUSCA (o resumo menciona um `.txt` por competência, zipado) | Aquisição de versões do SIGTAP e de notas técnicas, plano T04 | Bloqueado; visto só em resultado de busca | PENDENTE |
| W9 | PySUS, documentação do projeto; apoio técnico à aquisição/leitura, sujeito a teste de fidelidade. `https://pysus.readthedocs.io/` | Documentação de terceiros; SECUNDARIA | Candidato a leitor, rejeitado como dependência (ADR 0002); serve como verificação cruzada externa | Bloqueado (`pysus.readthedocs.io` sem resposta); fonte acessível via GitHub (`AlertaDengue/PySUS`, `docs/source/`); ver S4 | PENDENTE |

## B. Fontes oficiais adicionais (descobertas no levantamento)

O snapshot está PENDENTE em todas (`sustemporal acquire`). Todas estão bloqueadas neste ambiente
(`*.gov.br`, FTP do DATASUS, `ses.sp.bvs.br`). A exceção é O16: o host S3 responde, mas negou a
listagem do bucket (AccessDenied). A existência de arquivos no FTP vem de um inventário de terceiros
(S10), não de uma listagem oficial.

| ID | Fonte | Localizador | Como se sabe | Uso no projeto |
|---|---|---|---|---|
| O1 | Informe Técnico SIASUS 2019-07 (PDF, 1.103.131 bytes) | `ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/200801_/Doc/Informe_Tecnico_SIASUS_2019_07.pdf` | Existência e tamanho: SECUNDARIA (S10). Conteúdo: SECUNDARIA (transcrições S6–S8) | Nome dos arquivos PA; leiaute e códigos (posições 14, 15, 50–53 e 58; PA_INDICA; PA_DOCORIG). O inventário não tem `IT_SIASUS_1707.pdf` |
| O2 | Informe Técnico SIASUS 2008-01 | `http://w3.datasus.gov.br/siasih/Arquivos/SIASUS_Informe_T%C3%A9cnico_2008-01.pdf` | OFICIAL_VISTO_EM_BUSCA; conteúdo não verificado | Com O1, delimitar o leiaute e a semântica vigentes em 2018 |
| O3 | Portaria SAES/MS nº 1.110, de 11/11/2021 | `https://bvsms.saude.gov.br/bvs/saudelegis/saes/2021/prt1110_18_11_2021.html` | OFICIAL_VISTO_EM_BUSCA; a URL traz `18_11_2021`, e a data exata é A_CONFIRMAR | Janela de competências de atendimento aceitas no processamento; apresentação retroativa; reapresentação |
| O4 | SES-SP, projeto DRS XI Presidente Prudente (PDF) | `https://www.saude.sp.gov.br/resources/cve-centro-de-vigilancia-epidemiologica/areas-de-vigilancia/doencas-cronicas-nao-transmissiveis/observatorio-promocao-a-saude/mural-de-boas-praticas/projetos/drs11_pprudente.pdf` | OFICIAL_VISTO_EM_BUSCA | 45 municípios e 5 CGR |
| O5 | SES-SP, `E_REG-DRS-XI_2022.pdf` | `https://ses.sp.bvs.br/wp-content/uploads/2022/05/E_REG-DRS-XI_2022.pdf` | OFICIAL_VISTO_EM_BUSCA | RRAS 11; 5 regiões de saúde com 12/19/5/5/4 municípios; população 769.440 |
| O6 | Decreto estadual SP nº 51.433/2006 | `https://www.al.sp.gov.br/repositorio/legislacao/decreto/2006/decreto-51433-28.12.2006.html` | OFICIAL_VISTO_EM_BUSCA | Criação da estrutura dos DRS |
| O7 | IT CNES 1706 (PDF) | `ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/doc/IT_CNES_1706.pdf` (`doc` em minúsculas) | Existência: SECUNDARIA (S10); conteúdo não lido | Leiautes e domínios de ST, PF, SR e HB |
| O8 | `TAB_SIA.zip` (72.960.215 bytes) | `ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/200801_/Auxiliar/TAB_SIA.zip` | Existência: SECUNDARIA (S10); conteúdo não lido | Tabelas auxiliares; pode conter os domínios de PA_CODOCO, PA_FLQT e PA_FLER (hipótese INFERIDA) |
| O9 | `TAB_CNES.zip` | `ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Auxiliar/TAB_CNES.zip` | Existência: SECUNDARIA (S10); conteúdo não lido | Domínios do CNES |
| O10 | SIGTAP, página de download da Tabela Unificada | `http://sigtap.datasus.gov.br/tabela-unificada/app/download.jsp` (ver também W8) | OFICIAL_VISTO_EM_BUSCA | Versões por competência |
| O11 | SIGTAP, diretório FTP | `ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/` e `ftp://ftp2.datasus.gov.br/public/sistemas/tup/downloads/` | SECUNDARIA (S18 usa `/pub/`; S19 usa `/public/`) | Aquisição dos zips |
| O12 | SIGTAP, arquivos dentro de cada zip: `LEIA_ME.TXT`, `layout.txt`, `*_layout.txt` e "DATASUS - Tabela de Procedimentos - Lay-out.xls" | Membros do zip | LEIA_ME: SECUNDARIA (cópia em S17). Leiautes: SECUNDARIA (cópia 2026-02 em S16) | Codificação; nome do zip; idades em meses; leiaute por competência |
| O13 | DATASUS, Transferência de Arquivos | Página `https://datasus.saude.gov.br/transferencia-de-arquivos/`. `POST https://datasus.saude.gov.br/wp-content/ftp.php` recebe `tipo_arquivo[]`, `fonte[]`, `ano[]`, `mes[]` e `uf[]` e devolve endereços `ftp://`. `https://datasus.saude.gov.br/wp-content/download.php` gera `https://datasus.saude.gov.br/wp-content/zipupload/<id>/arquivo.zip` | SECUNDARIA (S20, observado em 2026-08-28) | Descoberta de arquivos; possível canal HTTPS (A_CONFIRMAR) |
| O14 | FTP DATASUS, diretórios de dados | `ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/200801_/Dados/`, `.../SIASUS/199407_200712/Dados/` e `.../CNES/200508_/Dados/{grupo}/` | SECUNDARIA (S2, S3 e S5 concordam) | Origem dos DBC |
| O15 | Gateway HTTPS do FTP | `https://ftp.datasus.gov.br/dissemin/publicos/...` | SECUNDARIA: S20 o lista como permitido; S21 diz que "costuma dar timeout"; S9 relata as portas 80/443 fora do ar em 01/08/2026 | Não usar como canal único |
| O16 | OpenDataSUS, CNES estabelecimentos (CSV) | `https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/cnes_estabelecimentos_csv.zip` | SECUNDARIA (S22) | Só retrato corrente; não serve ao histórico mensal |
| O17 | Nota Técnica nº 7/2023-CGSI/DRAC/SAES/MS | Sem URL | Citada num resumo de busca sobre competências fechadas do CNES; existência A_CONFIRMAR | Localizar e avaliar |

## C. Fontes secundárias consultadas

Lidas via `raw.githubusercontent.com`, PyPI ou arquivos locais. Quando o levantamento não registrou o
commit, vale o ramo indicado na data de 2026-10-01 (A_CONFIRMAR). Ao preservar uma fonte que sustente
item de catálogo, registrar o commit e o SHA-256 (PENDENTE).

| ID | Fonte (referência lida) | O que sustentou | Ressalva |
|---|---|---|---|
| S1 | microdatasus `R/process_sia.R` (master, v3.0.0; é a W1) | Decodificadores de PA_INDICA, PA_DOCORIG, PA_TPFIN, PA_MOTSAI, PA_CATEND, PA_FLIDADE, PA_SEXO, PA_RACACOR e PA_TPUPS; sequência dos 40 campos tratados | Erros no código (ver inventário §1.4); S9 relata falha em execução |
| S2 | microdatasus `R/datasus_download_helpers.R` e `R/fetch_datasus.R` | Diretórios FTP; arquivos referem-se a períodos de processamento; parte do arquivo como "fragment"; precedência entre publicações atual, preliminar e histórica | — |
| S3 | PySUS 2.11.5 (`AlertaDengue/PySUS`, main; release "Latest" em 2026-10-01): `pysus/api/ftp/databases.py`, `client.py` | Caminhos e grupos SIASUS/CNES; regex de nome com sufixo; leitura via pyreaddbc e decodificação cp1252 com `errors="replace"` | — |
| S4 | PySUS `docs/source/working-with-datasus-data.rst` (main; fonte de W9) | Atualização retroativa dos meses recentes; PA de 54 para 60 colunas; "DATASUS does not version file layouts" | Documentação de terceiros |
| S5 | datasusr `R/datasus_catalog.R` (`cran/datasusr`) | Diretórios FTP (concordância) | — |
| S6 | Transcrição em Markdown do IT SIASUS 2019-07: `thallyslemos/tcc-pipeline-transito-sus`, `docs/Informe_Tecnico_SIASUS_2019_07.md` @ `7c62bc3f3f8485404a6e1af4e82c644a5468d800` | Nome `PAufaamm`; posições 14, 15, 50–53 e 58; PA_INDICA; PA_DOCORIG; AP_CMP; DT_PROCESS e DT_ATEND (BI) | Transcrição; conferir com O1 |
| S7 | `Vinicius-Luiz/etl_data_analisys_sia_python`, `metadata/sia_metadata.csv` | Mesma redação do IT (transcrição independente) | — |
| S8 | `dr2pedro/siasus_service`, `src/core/BPA.ts` | Mesma redação do IT (transcrição independente) | — |
| S9 | `MarkusLC/mestrado-ccu-pe`, `docs/fontes/res_09.json` | `PAPE1801`: PA_MVM = 201801 e PA_CMP de 201710 a 201801; ~12 % dos registros em arquivos posteriores; nome real PA_SRV_C; PA_FNTORC em 2026; IDADEMIN/IDADEMAX em anos; portas 80/443 do gateway fora do ar | A alegação "234 arquivos; mensal a partir de 2024, trimestral antes" sobre o SIGTAP não foi verificada e é inconsistente |
| S10 | `abelsilvaeng/datasus-respiratorio`, `dados/inventario-datasus.csv` (varredura do FTP em 27/08/2026) | Partes a–d de SP; tamanhos; existência de O1, O7, O8 e O9; nomes CNES; SP CNES não dividido | Retrato de uma data |
| S11 | `Precisa-Saude/datasus-parquet`, `state/pending.json` | Existência de `PASP2606d.dbc` | — |
| S12 | `ImpulsoGov/sm-etl-cloud-run`, `siasus_procedimentos_ambulatoriais.py` | Padrão `PA{uf}{yymm}[a-z]?.dbc` | — |
| S13 | healthbR 0.4.0 (`cran/healthbR`: `R/sia.R`, `R/sia_data_internal.R`, vinheta) | PA_MVM "movimentação" e PA_CMP "competência"; URL montada sem sufixo de parte | Dicionário não confiável (inventário §1.4) |
| S14 | `shmjade/datasus` | — | Inverte PA_MVM e PA_CMP; não usar |
| S15 | `hdneves/siasus` (CSV de backup) | Uma linha com PA_CODOCO = 1, PA_FLQT = K e PA_FLER = 0 | Uma linha; não dá domínio |
| S16 | `abUFS/sus-internacao-calculator`, `data/tabelas/TabelaUnificada_202602_v2602121027` (cópia não modificada) | Leiautes SIGTAP 2026-02 (`tb_procedimento`, `rl_*`, `tb_registro`); contagens de TP_SEXO, TP_COMPLEXIDADE e 9999 | Uma competência |
| S17 | `DiogoCrespi/unificasus` (cópia de `LEIA_ME.TXT`) | Texto do LEIA_ME: nome do zip, ISO-8859-1, idades em meses, 9999 | Leiautes editados localmente; não usar os leiautes |
| S18 | `rdsilva/SIGTAP`, `Sigtap.Rmd` | FTP `/pub/sistemas/tup/downloads/`; `TabelaUnificada_202510_v2510160954.zip` | — |
| S19 | `tropeks/Vitali`, README | FTP `/public/sistemas/tup/downloads/`; `TabelaUnificada_202607_v2607101010.zip`; finais de linha CRLF | — |
| S20 | `redkk123/tabwin-web`, `packages/acquisition/src/datasus.ts` (observado em 2026-08-28) | Endpoints de O13; gateway O15 listado como permitido | — |
| S21 | `rafaelrbnet/DATA-RAG-SUS`, `src/data/ingestion.py` | Instabilidade do gateway O15 | — |
| S22 | `ipea/enderecobr_rs`, `Makefile` | URL de O16 | — |
| S23 | `covid19br/now_fcts`, `data-raw/DRS_SP.csv` | Lista do DRS XI (códigos de 6 dígitos) | — |
| S24 | `vpedrota/ProjetoIA`, `tratados/dados/ibge_drs.csv` | Lista do DRS XI (7 dígitos) | — |
| S25 | AlertaDengue, `regional_by_states.json` | Lista do DRS XI (7 dígitos e região) | — |
| S26 | PyPI JSON (`https://pypi.org/pypi/<nome>/json`, consultado em 2026-10-01) | Versões, licenças, wheels e dependências (ADR 0002) | Metadados declarados pelos autores; o PySUS declara "Proprietary" no classificador por engano |
| S27 | `AlertaDengue/pyreaddbc` (main = 2.0.4): `pyreaddbc/readdbc.py`, testes, fontes C | API `dbc2dbf`; falha silenciosa; os 4 bytes pós-cabeçalho ignorados; reescrita do último byte do cabeçalho | — |
| S28 | `danicat/read.dbc`: `DBC_FORMAT.md`, `NAMESPACE`, `src/dbf2dbc.c`, `src/implode.c` | Leiaute DBC; compressor `dbf2dbc` (4 bytes zerados; fluxo iniciado por `00 06`) | `DBC_FORMAT.md` põe o cabeçalho no offset 10, contra o próprio código |
| S29 | `mymatsubara/datasus-dbc`: `Cargo.toml`, `src/decompress.rs` | Implementação em Rust; os 4 bytes são lidos e não verificados | — |
| S30 | `blast.c` v1.3 (Mark Adler, 2013), cópia lida neste ambiente | Formato DCL: 1º byte 0/1 (literais não codificados/codificados); 2º byte 4/5/6 (log2 do dicionário − 6); código de fim (comprimento 519) | — |
| S31 | `Schallaven/pwexplode`: README e LICENSE | GPL-3.0; fora do PyPI | Só para descarte |
| S32 | `duckdb/duckdb-web`, `docs/current/...` (fonte de W2), e stubs de tipos da wheel duckdb 1.5.6 | Leitura e escrita de Parquet, parâmetros, garantias de ordem | — |
| S33 | CnesData, repositório do usuário (`/home/user/CnesData`), só como referência | Leiaute PF de 40 campos (EMPIRICA_CNESDATA); sentinelas; contrato de COMPETEN; precedente datasus-dbc + dbfread e checagem de tamanho físico; fixture `PFSP2601.dbc`; conflito 3541307/3541308; dígito verificador IBGE; transcrições de manuais do BPA/SIA | O projeto não depende de repositórios pessoais (plano §3); os PDFs oficiais que o CnesData cita não estão no repositório |
