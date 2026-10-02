# Semântica temporal: registro de versões e seleção (T06)

Estado: pré-G0. Tudo o que está aqui foi exercitado só com dados SINTETICO.

## 1. Tempos que nunca se confundem
O plano (§4) separa cinco tempos, cada um com tipo próprio em `contracts/temporal.py`:

- a competência de atendimento A(r);
- a competência de processamento Q(r);
- a competência do arquivo, ou seja, o AAMM do nome publicado;
- a vigência documentada de uma regra;
- o instante em que a pesquisa observou uma versão.

O instante de observação é sempre o do relógio da coleta. Metadados remotos (MDTM, Last-Modified,
mtime) ficam brutos e nunca viram competência nem instante (T02).

## 2. Registro (`temporal/registry.py`)
O registro é o manifesto da aquisição lido inteiro e conferido (cadeia de hash e âncora). Ele tem
duas partes:

- **Versões de conteúdo:** uma por `artifact_id`, isto é, por chave lógica e sha256.
- **Observações:** todas, em ordem de instante, inclusive as falhas.

O registro não resume o histórico a "primeira/última vez visto". `intervalos()` deriva, para
uma chave, os trechos contíguos de observação do mesmo conteúdo. A sequência A, B, A dá três
intervalos, todos rotulados `OBSERVACAO_DA_PESQUISA`. Eles dizem quando **a pesquisa** viu cada
conteúdo, não quando o DATASUS o publicou ou o alterou.

## 3. Decisão por chave (`selecionar_versao`)
A entrada é:

- a fonte;
- o critério da política (base e deslocamento; o canal é opcional);
- a competência exata requerida C;
- a UF;
- o corte de observação K.

A decisão segue estes passos:

1. Toma as observações de arquivos publicados (listagens não entram) com
   `competencia_arquivo = C`. Nenhuma: **AUSENTE**. Nunca se consulta C±1.
2. Descarta as observações posteriores a K. Se todas forem posteriores: **FORA_DO_CORTE**. A data de
   coleta nunca é retroagida: um arquivo de 2018 obtido em 2026 só existe para a pesquisa a partir
   de 2026.
3. Agrupa as observações por parte. Em cada parte:
   - um único conteúdo íntegro obtido dá **seleção**;
   - dois ou mais conteúdos íntegros distintos (republicação divergente, inclusive A→B→A) dão
     **AMBIGUA**;
   - só conteúdo em quarentena dá **EM_QUARENTENA**;
   - só tentativas sem bytes dão **AUSENTE**.

   A integridade considerada é a da observação, quando ela registra uma (pendência T02-11), e
   senão a da versão.
4. Combina as partes. Qualquer parte AMBIGUA torna a seleção AMBIGUA, e qualquer parte em
   quarentena a torna EM_QUARENTENA. Nos multipartes:
   - sem partes esperadas declaradas, **INCOMPLETA** com completude INDETERMINADA (pendência
     T02-12);
   - com partes declaradas e alguma faltante, **INCOMPLETA**;
   - com todas presentes, **SELECIONADA**.
5. `SelecaoVersao.confere` garante na origem que fonte e competência de cada versão selecionada
   são as requeridas.

Toda seleção traz um `motivo` determinístico e os ids das observações usadas. Isso permite
reproduzir a justificativa só a partir do manifesto.

## 4. Política e registro (`select_snapshots`)
- **Política:** é a da execução (`RunConfig.politica_id`); sem ela, vale a da regra. Os arquivos
  ficam em `catalog/policies/<id>.yaml`.
- **Fontes:** a seleção cobre cada fonte auxiliar da regra (≠ SIA_PA).
- **NAO_RESOLVIDA, sem base e sem competência:** em três casos:
  - política `NAO_RESOLVIDA`;
  - política com documento pendente;
  - política sem critério para a fonte.
- **NAO_RESOLVIDA por competência ausente:** se a competência base do registro é nula, a seleção
  também fica `NAO_RESOLVIDA`.
- **Competência requerida:** é `base(r) + deslocamento`.
- **Conjunto congelado:** com corte, o `SnapshotSet` sai com `congelado=True` e id derivado do
  conteúdo. Observações posteriores ao corte não o alteram, porque o mesmo conteúdo dá o mesmo
  id.

| Política | Tipo | Critério |
|---|---|---|
| `B_ATEND` | ALTERNATIVA_EXPLORATORIA | todas as fontes auxiliares por A(r), deslocamento 0 (plano §7) |
| `B_PROC` | ALTERNATIVA_EXPLORATORIA | todas por Q(r), deslocamento 0 |
| `M_TEMP_PADRAO` | NAO_RESOLVIDA | nenhum documento define a competência por regra e fonte; abstenção |

Só será `DOCUMENTADA` uma política que tenha documento preservado (`DocRef` PRESERVADO, com
sha256). Hoje nenhuma tem.

## 5. Lote (`temporal/lote.py`)
O lote parte de uma tabela de registros no DuckDB (`row_id`, `competencia_atendimento`,
`competencia_processamento`). O DuckDB calcula a competência requerida por registro, regra e
fonte. Cada chave distinta (fonte, base, competência) é decidida pela **mesma**
`selecionar_versao`, e o resultado volta por junção.

A equivalência com a seleção por registro é testada por propriedade (Hypothesis). A tabela
`selecao_versoes` segue `selecao_versoes.v1`. `gravar_selecoes` grava o Parquet e devolve o
`DatasetRef` com o hash lógico `lh1` sobre todas as colunas, na ordem do esquema, com a contagem
real.

O motor (T07) pode derivar a mesma seleção do `SnapshotSet` pela chave (fonte, base, competência).
Também confere a coerência de uma tabela fornecida com a política da execução.

## 6. Limites declarados
- A retrospectiva não simula o conhecimento do gestor na data original. Ela usa as versões que a
  pesquisa conseguiu observar até o corte.
- **Ausência de observação não é ausência de publicação.** AUSENTE quer dizer que a pesquisa não
  obteve o arquivo, e a avaliação dependente fica INCONCLUSIVO.
- Vigência de vínculo não é interpolada entre meses ausentes.
