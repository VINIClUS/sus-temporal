# Inventário preliminar de campos e códigos (A_CONFIRMAR)

Estado em 2026-10-01. Nenhum arquivo real do DATASUS nem documento oficial foi lido neste ambiente
(`*.gov.br` e FTP do DATASUS bloqueados): tudo aqui é A_CONFIRMAR contra cabeçalhos DBF reais,
leiautes do SIGTAP e documentos oficiais preservados, e nada é leiaute oficial. Rótulos e IDs de
fonte (E, W*, O*, S*): `fontes.md`. Semente de `catalog/layouts/` e `catalog/labels/`: cada item
levado ao catálogo mantém rótulo e ID de fonte e é revisto no G0 (plano §2).

## 1. SIA-PA

### 1.1 Arquivos e diretórios

- **Nome** `PA{UF}{AA}{MM}[parte].dbc`. O IT descreve "PAufaamm.dbf", com `aa`/`mm` "da competência"
  (SECUNDARIA, S6). `AAMM` é a competência de processamento: em `PAPE1801.dbc`, PA_MVM = 201801 e
  PA_CMP ∈ {201801, 201712, 201711, 201710} (SECUNDARIA, S9; o microdatasus diz o mesmo, S2).
- **Parte**: uma letra minúscula quando a UF é dividida (SECUNDARIA, S10–S12; o PySUS aceita também
  `_N`, S3). O healthbR 0.4.0 ignora as partes (S13).
- **Diretórios** (SECUNDARIA, S2, S3, S5), sob `ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/`:
  `200801_/Dados/` (2008-01 em diante), `199407_200712/Dados/` (1994-07 a 2007-12), `200801_/Doc/`
  (O1) e `200801_/Auxiliar/` (O8).
- **Canais**: o microdatasus escolhe por precedência entre publicações atual, preliminar e histórica
  (SECUNDARIA, S2; diretórios A_CONFIRMAR); aqui o canal entra na identidade do artefato e nunca é
  escolhido implicitamente.
- **Revisões**: meses recentes são atualizados retroativamente (SECUNDARIA, S4); ~12 % dos registros
  de uma competência de atendimento chegam em arquivos posteriores (SECUNDARIA, S9).

### 1.2 Divisão de SP em partes

Varredura do FTP de 27/08/2026 (SECUNDARIA, S10; `PASP2606d.dbc` também em S11). Não há
`PASP{AAMM}.dbc` sem sufixo nesses meses; ex.: `PASP2301a/b/c` = 78,4 / 142,8 / 97,5 MB.

| Competência do arquivo (AAMM) | Partes |
|---|---|
| 1801–1902 | a, b |
| 1903–2407 | a, b, c |
| 2408 | a, b, c, d |
| 2409–2501 | a, b, c |
| 2502–2606 | a, b, c, d |

INFERIDA: o G0 exige `a, b` (1801, 1807) ou `a, b, c` (2001, 2007, 2201, 2207). O critério de
divisão é desconhecido, então parte ausente torna a competência INCONCLUSIVA. As partes podem mudar
com republicação (A_CONFIRMAR).

### 1.3 Campos

- **Posições**: `*` = confirmada pela transcrição do IT 2019-07 (SECUNDARIA, S6–S8); demais =
  INFERIDA (coerente com as confirmadas e com a sequência de nomes tratados pelo microdatasus, S1).
  Tipos e larguras: A_CONFIRMAR (o IT transcrito só dá CHAR(6) em 14–15 e CHAR(1) em 50–53).
- **Variação**: o PA passou de 54 para 60 colunas com PA_INE, PA_NAT_JUR, PA_SRV_C, PA_VL_CF,
  PA_VL_CL e PA_VL_INC (SECUNDARIA, S4), justamente as posições 55–60 inferidas; a data de entrada de
  cada uma (A_CONFIRMAR) decide o leiaute de 2018. Arquivos de 2026 acrescentam PA_FNTORC
  (SECUNDARIA, S9). Campo ausente no período ⇒ INCONCLUSIVO, nunca violação (Restrições globais).
- **Papéis**: CHAVE (junção, seleção temporal, aplicabilidade); LINHAGEM (liga a linha à origem ou a
  outras linhas); ATRIBUTO (candidato; só entra no classificador pela lista positiva rastreada à
  origem, plano §7); ROTULO (desfecho oficial); DIAGNOSTICO (erro, consistência ou valor produzido
  pelo processamento). `?` = papel incerto, fora da lista positiva até confirmação. † = contexto que o
  SIA pode preencher a partir do CNES/SIGTAP (INFERIDA dos nomes); se confirmado, é resultado do
  processamento (plano §7) e revela a versão de referência usada pelo SIA, logo serve ao diagnóstico
  da seleção temporal, não como atributo.
- **Proibidos como atributo: ROTULO e DIAGNOSTICO.** "O classificador não receberá o rótulo, campos
  de erro ou quantidades e valores aprovados como atributos" (plano, Restrições globais, citando
  E §6); campos de erro só auxiliam diagnóstico e anotação (plano §7). Assim: PA_INDICA, PA_QTDAPR e
  PA_VALAPR são ROTULO; PA_CODOCO, PA_FLQT, PA_FLER e PA_FLIDADE são campos de erro; PA_DIF_VAL,
  NU_VPA_TOT e NU_PA_TOT, de significado desconhecido mas com nomes de diferença e totais de valor
  (INFERIDA), ficam DIAGNOSTICO por precaução.
- **Fora das tabelas canônicas**: identificadores pessoais (PA_CNSMED; PA_CNPJCPF quando CPF), por
  minimização (decisão deste projeto, A_CONFIRMAR com a orientação). A ingestão acrescenta linhagem
  inexistente no DBF (artefato, parte, índice físico, marcador de deleção), base do `row_id`
  (plano §4).

| Pos. | Campo | Descrição curta | Papel provável | Rótulo da descrição |
|---|---|---|---|---|
| 1 | PA_CODUNI | Código do estabelecimento (CNES) | CHAVE | INFERIDA (nome) |
| 2 | PA_GESTAO | Gestão (código do gestor?) | ATRIBUTO? † | INFERIDA (nome) |
| 3 | PA_CONDIC | Condição (de gestão?); o IT traz lista de valores | ATRIBUTO? † | INFERIDA (nome); lista: SECUNDARIA |
| 4 | PA_UFMUN | Município (6 dígitos), provavelmente o do estabelecimento | CHAVE (recorte DRS XI) | 6 dígitos: SECUNDARIA; resto: INFERIDA (nome) |
| 5 | PA_REGCT | Regra contratual? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 6 | PA_INCOUT | Incremento "outros"? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 7 | PA_INCURG | Incremento de urgência? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 8 | PA_TPUPS | Tipo de unidade (ex.: 02 UBS, 05 hospital geral, 36 ambulatório especializado) | ATRIBUTO? † | SECUNDARIA (S1) |
| 9 | PA_TIPPRE | Tipo de prestador? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 10 | PA_MN_IND | Mantida/individual? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 11 | PA_CNPJCPF | CNPJ ou CPF do prestador; identificador pessoal quando CPF | ATRIBUTO? †; reter só CNPJ | INFERIDA (nome) |
| 12 | PA_CNPJMNT | CNPJ da mantenedora | ATRIBUTO? † | INFERIDA (nome) |
| 13 | PA_CNPJ_CC | CNPJ (sufixo `_CC` não interpretado) | ATRIBUTO? † | INFERIDA (nome) |
| 14* | PA_MVM | "Data de Processamento / Movimento (AAAAMM)"; CHAR(6) | CHAVE (competência de processamento) | SECUNDARIA (S6–S8) |
| 15* | PA_CMP | "Data da Realização do Procedimento / Competência (AAAAMM)"; CHAR(6) | CHAVE (competência de atendimento) | SECUNDARIA (S6–S8) |
| 16 | PA_PROC_ID | Procedimento SIGTAP; chave de junção no microdatasus | CHAVE | SECUNDARIA (S1) |
| 17 | PA_TPFIN | Tipo de financiamento (§1.4) | ATRIBUTO? † | SECUNDARIA (S1) |
| 18 | PA_SUBFIN | Subtipo de financiamento? | ATRIBUTO? † | INFERIDA (nome) |
| 19 | PA_NIVCPL | Nível de complexidade? | ATRIBUTO? † | INFERIDA (nome); tratado em S1 |
| 20 | PA_DOCORIG | Instrumento de registro (§1.4) | CHAVE (aplicabilidade) | SECUNDARIA (S6–S8, S1) |
| 21 | PA_AUTORIZ | Número da autorização (APAC/RAAS?) | LINHAGEM (liga linhas da mesma autorização; retenção A_CONFIRMAR) | INFERIDA (nome) |
| 22 | PA_CNSMED | CNS do profissional; identificador pessoal | Não reter | INFERIDA (nome) |
| 23 | PA_CBOCOD | CBO do profissional; chave de junção no microdatasus | CHAVE | SECUNDARIA (S1) |
| 24 | PA_MOTSAI | Motivo de saída/permanência; 00 = sem motivo de saída (BPA-C/BPA-I) | ATRIBUTO | SECUNDARIA (S1) |
| 25 | PA_OBITO | Óbito? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 26 | PA_ENCERR | Encerramento? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 27 | PA_PERMAN | Permanência? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 28 | PA_ALTA | Alta? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 29 | PA_TRANSF | Transferência? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 30 | PA_CIDPRI | CID principal | ATRIBUTO | INFERIDA (nome) |
| 31 | PA_CIDSEC | CID secundário | ATRIBUTO | INFERIDA (nome) |
| 32 | PA_CIDCAS | CID de causas associadas? | ATRIBUTO | INFERIDA (nome) |
| 33 | PA_CATEND | Caráter de atendimento (§1.4) | ATRIBUTO | SECUNDARIA (S1) |
| 34 | PA_IDADE | Idade do paciente; unidade A_CONFIRMAR (§1.6) | ATRIBUTO | INFERIDA (nome) |
| 35 | IDADEMIN | Idade mínima do procedimento, aparentemente em anos | DIAGNOSTICO? (cópia do SIGTAP no processamento, INFERIDA) | SECUNDARIA (S9) |
| 36 | IDADEMAX | Idade máxima do procedimento, aparentemente em anos | DIAGNOSTICO? (idem) | SECUNDARIA (S9) |
| 37 | PA_FLIDADE | Idade × SIGTAP: 0 não exigida; 1 compatível; 2 fora da faixa; 3 inexistente; 4 em branco | DIAGNOSTICO | SECUNDARIA (S1) |
| 38 | PA_SEXO | Sexo (§1.4) | ATRIBUTO | SECUNDARIA (S1) |
| 39 | PA_RACACOR | Raça/cor (§1.4) | ATRIBUTO | SECUNDARIA (S1, S6) |
| 40 | PA_MUNPCN | Município de residência do paciente (6 dígitos) | ATRIBUTO | 6 dígitos: SECUNDARIA; resto: INFERIDA (nome) |
| 41 | PA_QTDPRO | Quantidade produzida/apresentada | ATRIBUTO | INFERIDA (nome) |
| 42 | PA_QTDAPR | Quantidade aprovada | ROTULO | INFERIDA (nome) |
| 43 | PA_VALPRO | Valor produzido/apresentado (insumo de P3, plano §7) | ATRIBUTO? † | INFERIDA (nome) |
| 44 | PA_VALAPR | Valor aprovado | ROTULO | INFERIDA (nome) |
| 45 | PA_UFDIF | UF diferente? | ATRIBUTO? † | INFERIDA (nome) |
| 46 | PA_MNDIF | Município diferente? | ATRIBUTO? † | INFERIDA (nome) |
| 47 | PA_DIF_VAL | Diferença de valor? | DIAGNOSTICO | INFERIDA (nome) |
| 48 | NU_VPA_TOT | Total de valor? | DIAGNOSTICO | INFERIDA (nome) |
| 49 | NU_PA_TOT | Total? | DIAGNOSTICO | INFERIDA (nome) |
| 50* | PA_INDICA | "Indicativo de situação da produção produzida"; CHAR(1); 0/5/6 (§1.4) | ROTULO | SECUNDARIA (S6–S8, S1) |
| 51* | PA_CODOCO | "Código de Ocorrência"; CHAR(1); domínio fora do IT | DIAGNOSTICO | SECUNDARIA (S6–S8) |
| 52* | PA_FLQT | "Indicador de erro de Quantidade Produzida"; CHAR(1) | DIAGNOSTICO | SECUNDARIA (S6–S8) |
| 53* | PA_FLER | "Indicador de erro de corpo da APAC"; CHAR(1) | DIAGNOSTICO | SECUNDARIA (S6–S8) |
| 54 | PA_ETNIA | Etnia? | ATRIBUTO | INFERIDA (nome); tratado em S1 |
| 55 | PA_VL_CF | Componente de valor "CF"? | DIAGNOSTICO? | INFERIDA (nome); coluna tardia (S4) |
| 56 | PA_VL_CL | Componente de valor "CL"? | DIAGNOSTICO? | INFERIDA (nome); coluna tardia (S4) |
| 57 | PA_VL_INC | Valor de incremento? | DIAGNOSTICO? | INFERIDA (nome); coluna tardia (S4) |
| 58* | PA_SRV_C | Serviço/classificação? O IT nomeia `PA_SRC_C`; os arquivos reais trazem `PA_SRV_C` | CHAVE? (família serviço/classificação) | Posição e nomes: SECUNDARIA (S6, S9); descrição: INFERIDA (nome) |
| 59 | PA_INE | Equipe (INE)? | ATRIBUTO | INFERIDA (nome); coluna tardia (S4) |
| 60 | PA_NAT_JUR | Natureza jurídica | ATRIBUTO? † | INFERIDA (nome); coluna tardia (S4) |
| 61 (2026) | PA_FNTORC | Fonte orçamentária? | DIAGNOSTICO? | Existência: SECUNDARIA (S9); descrição: INFERIDA (nome) |

### 1.4 Códigos

**PA_INDICA (ROTULO).** Cobertura uniforme em 2018–2025 não confirmada (plano §2); o healthbR não
tem o campo (S13); aprovação parcial é analisada à parte (plano §7).

| Código | Significado | Fonte |
|---|---|---|
| 0 | não aprovado | SECUNDARIA (IT via S6–S8; microdatasus S1 = W1) |
| 5 | aprovado total | idem |
| 6 | aprovado parcial | idem |
| outro ou vazio | DESCONHECIDO: bruto preservado, sem correção | Regra do plano §7 |

**PA_DOCORIG.** O PA reúne todos os instrumentos (IT, S6); a vinheta do healthbR o chama de "BPA
consolidado" (S13), contra o IT. Linhas `C` são verificadas no nível estabelecimento–CBO (Restrições
globais).

| Código | Instrumento (IT, S6–S8; S1) | CO_REGISTRO do SIGTAP (INFERIDA dos rótulos) |
|---|---|---|
| C | BPA-C (consolidado) | 01 |
| I | BPA-I (individualizado) | 02 |
| P | APAC, procedimento principal | 06 |
| S | APAC, procedimento secundário | 07 |
| A | RAAS, Atenção Domiciliar | 08 |
| B | RAAS, Psicossocial | 09 |

**PA_SEXO.** Arquivos reais trazem `M` e `F` (SECUNDARIA, relato do levantamento); o microdatasus
decodifica `0` como "Não exigido" (SECUNDARIA, S1); o healthbR dá 1/2 (S13): não usar.

**Sentinelas candidatas** (SECUNDARIA, S1), para distinguir vazio, desconhecido e não aplicável com
valor bruto e motivo (plano §4):

| Campo | Código e rótulo no microdatasus |
|---|---|
| PA_SEXO | 0 não exigido |
| PA_RACACOR | 00 não exigido; 99 sem informação; 06, 09, 1M, 1G, 1C, DE, D e 87 "indevidos" |
| PA_CATEND | 00 não informado; 99 informação inexistente (BPA-C); 07, 10, 12, 20, 53, 54 e 57 inválidos |
| PA_MOTSAI | 00 produção sem motivo de saída (BPA-C/BPA-I) |
| PA_FLIDADE | 0 idade não exigida; 3 inexistente; 4 em branco |

**Outros domínios.** PA_TPFIN (SECUNDARIA, S1): 01 PAB; 02 Assistência Farmacêutica; 04 FAEC; 05
Incentivo-MAC; 06 MAC; 07 Vigilância em Saúde. PA_RACACOR (SECUNDARIA, S1): 01 branca; 02 preta;
03 parda; 04 amarela; 05 indígena (03/04 confirmados pelo IT, S6). PA_CODOCO, PA_FLQT e PA_FLER não
têm domínio no IT (talvez em O8); valores isolados: PA_CODOCO = 1, PA_FLQT = K, PA_FLER = 0
(SECUNDARIA, S15). PA_CONDIC = "PG" aparece em dado real e falta na lista do IT (SECUNDARIA; fonte
exata não registrada).

**Cautelas** (nada disto é fonte de regra). O código do microdatasus tem erros (PA_INCURG gravado em
PA_INCOUT; PA_ALTA com rótulos de PA_PERMAN; PA_MOTSAI 42 = 43; rótulo `80` de PA_TPUPS truncado;
`mutate` sem nome), e S9 relata falha do `process_sia`. O healthbR erra PA_SEXO (1/2), PA_RACACOR
(03/04 trocados) e PA_TPFIN (01 = FAEC) (S13); `shmjade/datasus` inverte PA_MVM e PA_CMP (S14).

### 1.5 Competência de processamento × atendimento

- **IT** (SECUNDARIA, S6–S8): PA_MVM = "Data de Processamento / Movimento (AAAAMM)"; PA_CMP = "Data
  da Realização do Procedimento / Competência (AAAAMM)". O IT usa "Competência" também para o
  atendimento no APAC (AP_CMP) e separa DT_PROCESS e DT_ATEND nos arquivos BI (S6).
- **Portaria SAES/MS nº 1.110/2021** (O3; OFICIAL_VISTO_EM_BUSCA; paráfrase): o processamento aceita
  atendimentos da competência de processamento e de até 3 anteriores (4 no total); apresentação
  retroativa até 4 competências contadas do atendimento/alta; reapresentação de APAC/SIH rejeitados
  até 6. Competência de processamento é aquela em que SIA/SIH aplicam regras de consistência e
  valoração; competência de produção é o mês da prestação; em agosto/2021 processa-se julho/2021.
  Coerente com isso, cada arquivo PA tem PA_CMP em M, M−1, M−2 e M−3 (SECUNDARIA, S9).
- **Wiki do SIA, BPA** (W3; OFICIAL_VISTO_EM_BUSCA; paráfrase): a competência de apresentação difere
  do mês de atendimento, registrado em cada atendimento, e deve coincidir com a de processamento.
- **A_CONFIRMAR**: norma vigente em 2018–2021 (a Portaria é de 11/2021); PA_MVM constante e igual ao
  `AAMM` do nome; defasagem maior que 3 por reapresentação (INFERIDA da regra de 6), a medir no G0.
- **Consequência (INFERIDA)**: arquivos de 2018-01 trazem atendimentos de 2017-10 a 2017-12 e exigem
  CNES/SIGTAP anteriores a 2018 (Foco de revisão); nenhum mês vizinho é escolhido automaticamente.

### 1.6 Idade

No PA, IDADEMIN/IDADEMAX parecem estar em anos (`25`, `64`; SECUNDARIA, S9); a unidade de PA_IDADE é
A_CONFIRMAR, e o leiaute de exportação do BPA-C transcrito pelo CnesData admite idade 0–130
(SECUNDARIA, S33), o que sugere anos. No SIGTAP, VL_IDADE_MINIMA/MAXIMA estão em meses e 9999 indica
que o fator idade não se aplica (SECUNDARIA, LEIA_ME via S17). Converter só com unidade conhecida
(plano §4); sem ela, a família idade fica INCONCLUSIVA.

## 2. SIGTAP

### 2.1 Pacote

- **Zip por competência**, nome segundo o LEIA_ME: "Tabela Unificada_"Competência dos
  Procedimentos"_"Data de geração do arquivo".zip" (SECUNDARIA, S17). Exemplos:
  `TabelaUnificada_202510_v2510160954.zip` (S18), `TabelaUnificada_202607_v2607101010.zip` (S19),
  `TabelaUnificada_202602_v2602121027` (S16). Padrão `TabelaUnificada_{AAAAMM}_v{AAMMDDhhmm}.zip`
  (INFERIDA): pode haver mais de uma geração por competência, cada uma uma versão de conteúdo
  (A_CONFIRMAR). Onde obter: O10, O11, W8.
- **Disponibilidade**: "234 arquivos; mensal a partir de 2024, trimestral antes" (SECUNDARIA, S9) não
  foi verificado e é inconsistente. Competência sem versão própria ⇒ INCONCLUSIVO ou política
  explícita fixada antes do teste, nunca mês vizinho automático (plano §§5–7).
- **Conteúdo** (SECUNDARIA, S16/S17): TXT de largura fixa; `*_layout.txt` por tabela (cabeçalho
  `Coluna,Tamanho,Inicio,Fim,Tipo`), `layout.txt` combinado e "DATASUS - Tabela de Procedimentos -
  Lay-out.xls". Codificação ISO-8859-1: o LEIA_ME de 04/03/2008 fala em "conjunto de caracteres
  ISO-8859-1" (via S17), e `tb_procedimento.txt`/`tb_registro.txt` de S16 foram detectados como
  ISO-8859; finais de linha CRLF (S19).
- **Leiaute por competência** (SECUNDARIA; origem das cópias antigas não registrada): em 2018-09,
  2023-07 e 2023-10, VL_SH, VL_SA e VL_SP têm 10 posições e `tb_procedimento` tem registro de 330
  bytes; em 2026-02, 12 posições e 336 bytes. Cada competência é lida com os `*_layout.txt` do
  próprio zip; leiaute ausente ou incoerente ⇒ quarentena.

### 2.2 tb_procedimento (cópia 2026-02, S16)

| Posições | Campo | Posições | Campo |
|---|---|---|---|
| 1–10 | CO_PROCEDIMENTO | 279–282 | VL_IDADE_MAXIMA |
| 11–260 | NO_PROCEDIMENTO (250) | 283–294 | VL_SH |
| 261 | TP_COMPLEXIDADE | 295–306 | VL_SA |
| 262 | TP_SEXO | 307–318 | VL_SP |
| 263–266 | QT_MAXIMA_EXECUCAO | 319–320 | CO_FINANCIAMENTO |
| 267–270 | QT_DIAS_PERMANENCIA | 321–326 | CO_RUBRICA |
| 271–274 | QT_PONTOS | 327–330 | QT_TEMPO_PERMANENCIA |
| 275–278 | VL_IDADE_MINIMA | 331–336 | DT_COMPETENCIA |

Contagens do levantamento nessa cópia (SECUNDARIA, S16): TP_SEXO I = 4.664, N = 302, F = 7, M = 4
(significado de I e N: A_CONFIRMAR); TP_COMPLEXIDADE de 0 a 3; 596 procedimentos com
VL_IDADE_MINIMA = 9999.

### 2.3 Relacionamentos e tb_registro (cópia 2026-02, S16)

| Tabela | Campos (posições) | Família de regra (INFERIDA, plano §5) |
|---|---|---|
| rl_procedimento_ocupacao | CO_PROCEDIMENTO 1–10; CO_OCUPACAO 11–16; DT_COMPETENCIA 17–22 | procedimento–CBO |
| rl_procedimento_registro | CO_PROCEDIMENTO 1–10; CO_REGISTRO 11–12; DT_COMPETENCIA 13–18 | instrumento de registro |
| rl_procedimento_habilitacao | CO_PROCEDIMENTO 1–10; CO_HABILITACAO 11–14; NU_GRUPO_HABILITACAO 15–18; DT_COMPETENCIA 19–24 | habilitação |
| rl_procedimento_servico | CO_PROCEDIMENTO 1–10; CO_SERVICO 11–13; CO_CLASSIFICACAO 14–16; DT_COMPETENCIA 17–22 | serviço/classificação |
| rl_procedimento_cid | CO_PROCEDIMENTO 1–10; CO_CID 11–14; ST_PRINCIPAL 15; DT_COMPETENCIA 16–21 | CID |
| tb_registro | CO_REGISTRO 1–2; NO_REGISTRO 3–52; DT_COMPETENCIA 53–58 | domínio do instrumento |

Códigos de `tb_registro` (texto da cópia; SECUNDARIA, S16): 01 BPA (Consolidado); 02 BPA
(Individualizado); 03 AIH (Proc. Principal); 04 AIH (Proc. Especial); 05 AIH (Proc. Secundário); 06
APAC (Proc. Principal); 07 APAC (Proc. Secundário); 08 RAAS (Atenção Domiciliar); 09 RAAS (Atenção
Psicossocial); 10 e-SUS APS (Atenção Primária à Saúde). Presença de cada um nas versões de
2017–2025: A_CONFIRMAR. Mapeamento para PA_DOCORIG: §1.4 (INFERIDA).

**Não usar** os leiautes de `DiogoCrespi/unificasus` (S17): foram editados localmente
(NO_PROCEDIMENTO 300, NO_REGISTRO 100), como registra o próprio `GUIA_AUMENTAR_CAMPOS.md`. Desse
repositório vale só a cópia do LEIA_ME, que continua SECUNDARIA.

## 3. CNES

### 3.1 Diretórios e nomes

- `ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Dados/{GRUPO}/`, grupos LT, ST, DC, EQ,
  SR, HB, PF, EP, RC, IN, EE, EF e GM (SECUNDARIA, S2, S3, S5). Nome `{GG}{UF}{AA}{MM}.dbc`
  (`STSP2301.dbc`, `PFSP2412.dbc` com 74 MB); SP não é dividido (SECUNDARIA, S10). Documentação:
  `200508_/doc/IT_CNES_1706.pdf` (O7; `doc` minúsculo) e `200508_/Auxiliar/TAB_CNES.zip` (O9).
- Grupos de interesse (INFERIDA dos códigos e das famílias do plano §5; A_CONFIRMAR em O7): ST
  estabelecimentos; PF profissionais por estabelecimento e CBO; SR serviços especializados e
  classificação; HB habilitações.
- Competência fechada (W5; OFICIAL_VISTO_EM_BUSCA; paráfrase em inglês): ao fim do mês o CNES copia
  os dados para um histórico de competências e impede o usuário de alterar competência fechada,
  salvo decisão judicial envolvendo a União, executada por ordem de serviço paga. Se o DATASUS
  republica DBC passados: A_CONFIRMAR (vigilância, plano T13). O CSV do OpenDataSUS (O16) é só o
  retrato corrente.

### 3.2 PF: leiaute de 40 campos (EMPIRICA_CNESDATA)

Observado e imposto pelo CnesData (S33): nome, ordem, tipo e largura exatos; divergência é falha de
esquema. Competências observadas não registradas; validade para 2018–2025: A_CONFIRMAR. `C` =
caractere; `N` = numérico sem decimais. Significados do CnesData, sem fonte (INFERIDA): CODUFMUN
município do estabelecimento; UFMUNRES residência (do profissional); PF_PJ pessoa física/jurídica;
CPF_CNPJ CPF/CNPJ do estabelecimento.

"Não reter" marca campos que identificam pessoa e não entram em tabela canônica. A família
estabelecimento–CBO precisa só do par (CNES, CBO) na competência (INFERIDA do plano §5): bastam CNES,
CODUFMUN, CBO e COMPETEN, mais PROF_SUS e VINCULAC se a regra exigir. A tabela canônica guarda
contagens por estabelecimento–CBO, sem CPF, CNS, nome ou registro.

| # | Campo | Tipo | Não reter | # | Campo | Tipo | Não reter |
|---|---|---|---|---|---|---|---|
| 1 | CNES | C7 | — | 21 | CPF_PROF | C11 | SIM |
| 2 | CODUFMUN | C6 | — | 22 | CPFUNICO | C1 | — |
| 3 | REGSAUDE | C4 | — | 23 | CBO | C6 | — |
| 4 | MICR_REG | C6 | — | 24 | CBOUNICO | C6 | — |
| 5 | DISTRSAN | C4 | — | 25 | NOMEPROF | C60 | SIM |
| 6 | DISTRADM | C4 | — | 26 | CNS_PROF | C15 | SIM |
| 7 | TPGESTAO | C1 | — | 27 | CONSELHO | C2 | — |
| 8 | PF_PJ | C1 | — | 28 | REGISTRO | C13 | SIM (com CONSELHO, identifica o profissional) |
| 9 | CPF_CNPJ | C14 | QUESTÃO (abaixo) | 29 | VINCULAC | C6 | — |
| 10 | NIV_DEP | C1 | — | 30 | VINCUL_C | C1 | — |
| 11 | CNPJ_MAN | C14 | — | 31 | VINCUL_A | C1 | — |
| 12 | ESFERA_A | C2 | — | 32 | VINCUL_N | C1 | — |
| 13 | ATIVIDAD | C2 | — | 33 | PROF_SUS | C1 | — |
| 14 | RETENCAO | C2 | — | 34 | PROFNSUS | C1 | — |
| 15 | NATUREZA | C2 | — | 35 | HORAOUTR | N3 | — |
| 16 | CLIENTEL | C2 | — | 36 | HORAHOSP | N3 | — |
| 17 | TP_UNID | C2 | — | 37 | HORA_AMB | N3 | — |
| 18 | TURNO_AT | C2 | — | 38 | COMPETEN | C6 | — |
| 19 | NIV_HIER | C2 | — | 39 | UFMUNRES | C6 | Indireto: residência do profissional, desnecessária às contagens |
| 20 | TERCEIRO | C1 | — | 40 | NAT_JUR | C4 | — |

**QUESTÃO (CPF_CNPJ).** Com PF_PJ indicando pessoa física, CPF_CNPJ seria o CPF de uma pessoa
(INFERIDA dos nomes). Reter só quando for CNPJ de estabelecimento? Decidir após confirmar a
semântica de PF_PJ e CPF_CNPJ em O7; até lá, não reter.

### 3.3 Sentinelas, CBO, competência e leiautes ainda desconhecidos

- **Sentinelas**: no CnesData, CPF_PROF vazio ou `99999999999` e CNS_PROF vazio ou com 15 noves viram
  nulo (EMPIRICA_CNESDATA; no CnesData é regra dos autores, sem registro da observação).
  Aqui esses campos não são retidos; se usados de passagem, guardar bruto e motivo (plano §4).
- **CBO**: o adaptador PF do CnesData aceita só dígitos; o de BPA aceita `^[0-9]{4}[0-9A-Z]{2}$`
  (S33). Aqui o CBO é texto de 6 posições, sem supor só dígitos (A_CONFIRMAR em arquivos reais).
- **COMPETEN**: o CnesData exige COMPETEN igual à competência pedida em toda linha, antes do filtro
  municipal (divergência = falha final), e trata município sem linhas como `source_not_published`,
  retentável, sem buscar outro mês; UFMUNRES nunca substitui CODUFMUN (S33; decisão dos autores).
  Aqui (INFERIDA do Foco de revisão): divergência ⇒ quarentena; município sem linhas ⇒ cobertura
  insuficiente (INCONCLUSIVO), nunca ausência cadastral nem mês vizinho.
- **Texto**: o CnesData decodifica o PF como Latin-1 sem citar fonte; ver ADR 0002.
- **ST, SR, HB**: leiautes desconhecidos; A_CONFIRMAR em O7 e nos cabeçalhos reais. O CnesData não os
  ingere (ST só como "never probe ST"; SR, HB e EP ausentes). Pista: o modelo local do CNES
  (Firebird, não os arquivos de disseminação) tem habilitação com competência inicial/final
  (CMPT_INICIAL/CMPT_FINAL, C6) e serviço/classificação com 3 + 3 caracteres (EMPIRICA_CNESDATA,
  S33), larguras coerentes com `rl_procedimento_servico` (INFERIDA).

## 4. DRS XI — Presidente Prudente

- **Oficial** (O4–O6, só vistos em busca; OFICIAL_VISTO_EM_BUSCA): 45 municípios, 5 CGR; RRAS 11 com
  5 regiões de 12/19/5/5/4 municípios e 769.440 habitantes; DRS criados pelo Decreto 51.433/2006. Os
  trechos de busca deram só 40 nomes.
- **Lista (SECUNDARIA)**: S23 (6 dígitos), S24 (7) e S25 (7 e região) concordam nos 45 municípios e
  códigos. As contagens por região batem com O5; a correspondência região–contagem no documento
  oficial não foi vista (A_CONFIRMAR). IBGE6 = 6 primeiros dígitos do IBGE7, código do DATASUS em
  PA_UFMUN e PA_MUNPCN (SECUNDARIA). Os 45 IBGE7 passam no dígito verificador do CnesData
  (`_ibge7_check_digit`, sem citação; conferido em 2026-10-01), o que só pega erro de digitação.
- **Presidente Epitácio** (piloto do CnesData): 3541307 / 354130. O CnesData usa 3541308 em CI e
  fixtures e 3541307 noutros arquivos; as três listas e o dígito verificador dão 3541307 (A_CONFIRMAR
  no IBGE). Pertença fixa ou histórica e lista oficial versionada: decidir no piloto (plano §7).

| Região | Município | IBGE7 | IBGE6 | Município | IBGE7 | IBGE6 |
|---|---|---|---|---|---|---|
| Alta Paulista | Dracena | 3514403 | 351440 | Flora Rica | 3515806 | 351580 |
| Alta Paulista | Irapuru | 3521606 | 352160 | Junqueirópolis | 3526001 | 352600 |
| Alta Paulista | Monte Castelo | 3531605 | 353160 | Nova Guataporanga | 3533106 | 353310 |
| Alta Paulista | Ouro Verde | 3534807 | 353480 | Panorama | 3535408 | 353540 |
| Alta Paulista | Paulicéia | 3536406 | 353640 | Santa Mercedes | 3547106 | 354710 |
| Alta Paulista | São João do Pau d'Alho | 3549300 | 354930 | Tupi Paulista | 3555109 | 355510 |
| Alta Sorocabana | Alfredo Marcondes | 3500808 | 350080 | Álvares Machado | 3501301 | 350130 |
| Alta Sorocabana | Anhumas | 3502408 | 350240 | Caiabu | 3508900 | 350890 |
| Alta Sorocabana | Emilianópolis | 3515129 | 351512 | Estrela do Norte | 3515301 | 351530 |
| Alta Sorocabana | Indiana | 3520608 | 352060 | Martinópolis | 3529203 | 352920 |
| Alta Sorocabana | Narandiba | 3532207 | 353220 | Pirapozinho | 3539202 | 353920 |
| Alta Sorocabana | Presidente Bernardes | 3541208 | 354120 | Presidente Prudente | 3541406 | 354140 |
| Alta Sorocabana | Regente Feijó | 3542404 | 354240 | Ribeirão dos Índios | 3543238 | 354323 |
| Alta Sorocabana | Sandovalina | 3545506 | 354550 | Santo Anastácio | 3547700 | 354770 |
| Alta Sorocabana | Santo Expedito | 3548302 | 354830 | Taciba | 3552908 | 355290 |
| Alta Sorocabana | Tarabai | 3553906 | 355390 | | | |
| Alto Capivari | Iepê | 3519907 | 351990 | João Ramalho | 3525607 | 352560 |
| Alto Capivari | Nantes | 3532157 | 353215 | Quatá | 3541703 | 354170 |
| Alto Capivari | Rancharia | 3542206 | 354220 | | | |
| Extremo Oeste Paulista | Caiuá | 3509106 | 350910 | Marabá Paulista | 3528700 | 352870 |
| Extremo Oeste Paulista | Piquerobi | 3538303 | 353830 | Presidente Epitácio | 3541307 | 354130 |
| Extremo Oeste Paulista | Presidente Venceslau | 3541505 | 354150 | | | |
| Pontal do Paranapanema | Euclides da Cunha Paulista | 3515350 | 351535 | Mirante do Paranapanema | 3530201 | 353020 |
| Pontal do Paranapanema | Rosana | 3544251 | 354425 | Teodoro Sampaio | 3554300 | 355430 |

## 5. Pendências de confirmação (piloto)

- [ ] PA de SP em 2018-01/07, 2020-01/07 e 2022-01/07, todas as partes: nomes, ordem, tipos e
      larguras reais; unidade de PA_IDADE; origem de IDADEMIN, IDADEMAX e dos campos †.
- [ ] Preservar O1 e O2; achar o IT vigente em 2018 e a norma de janela de 2018–2021; domínios de
      PA_CODOCO, PA_FLQT, PA_FLER e PA_CONDIC (O1, O8); cobertura de PA_INDICA em 2018–2025.
- [ ] SIGTAP: versões de 2017-10 a 2025-12, leiaute de cada zip, TP_SEXO I/N, PA_DOCORIG ↔
      CO_REGISTRO.
- [ ] CNES: leiautes de ST, SR, HB e PF por período; PF_PJ e CPF_CNPJ; codificação do texto.
- [ ] DRS XI: lista oficial versionada, definição de pertença, IBGE7 do piloto do CnesData.
