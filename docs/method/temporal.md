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
intervalos, todos rotulados `OBSERVACAO_DA_PESQUISA`. Uma observação NAO_ENCONTRADO da mesma
parte encerra o intervalo corrente: A, ausente, A dá dois intervalos. Eles dizem quando **a
pesquisa** viu cada conteúdo, não quando o DATASUS o publicou ou o alterou.

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
   - **UF:** arquivo com UF só vale para a UF da execução (`piloto.uf`, senão `vigilancia.uf`).
     Sem UF definida, só fontes nacionais (sem UF) são consultadas.
   - **Canal:** quando o critério fixa um canal, os outros canais são ignorados.
2. Descarta as observações posteriores a K. Se todas forem posteriores: **FORA_DO_CORTE**. A data de
   coleta nunca é retroagida: um arquivo de 2018 obtido em 2026 só existe para a pesquisa a partir
   de 2026.
3. Agrupa as observações por parte. Em cada parte:
   - um único conteúdo íntegro obtido dá **seleção**;
   - dois ou mais conteúdos íntegros distintos (republicação divergente, inclusive A→B→A) dão
     **AMBIGUA**;
   - só conteúdo em quarentena dá **EM_QUARENTENA**;
   - falha de coleta com bytes (INTERROMPIDO com `bytes_recebidos > 0`, ou CONTEUDO_INVALIDO
     recusado antes do hash) também dá **EM_QUARENTENA**, com motivo `falha_de_coleta_com_bytes`.
     Assim a falha de coleta não se confunde com ausência estrutural;
   - só tentativas sem bytes dão **AUSENTE**.

   A integridade considerada é a da observação, quando ela registra uma (pendência T02-11), e
   senão a da versão. `NAO_VERIFICADO` conta como íntegro: o conteúdo foi obtido e não há
   verificação que o reprove.
   - Conteúdo em quarentena ao lado de conteúdo íntegro não impede a seleção do íntegro, mas as
     observações descartadas ficam no motivo (`descartadas_quarentena=`). A regra de fundo é do
     G0 (pendência T06-8).
   - Observação íntegra sem VERSAO no registro é inconsistência do manifesto: fica EM_QUARENTENA
     com motivo `observacao_integra_sem_versao`.
4. Combina as partes. Qualquer parte AMBIGUA torna a seleção AMBIGUA, e qualquer parte em
   quarentena a torna EM_QUARENTENA. Nos multipartes:
   - sem partes esperadas declaradas, **INCOMPLETA** com completude INDETERMINADA (pendência
     T02-12);
   - com partes declaradas, a regra vale mesmo que só o arquivo sem parte tenha sido observado;
   - com partes declaradas e alguma faltante, **INCOMPLETA**;
   - com todas presentes, **SELECIONADA**.
5. `SelecaoVersao.confere` garante na origem que fonte e competência de cada versão selecionada
   são as requeridas.

Toda seleção traz um `motivo` determinístico e os ids das observações usadas. Isso permite
reproduzir a justificativa só a partir do manifesto.

## 4. Política e registro (`select_snapshots`)
- **Política:** uma só por execução. Vale a passada pelo chamador (`politica=`), senão
  `RunConfig.politica_id`, carregada de `catalog/policies/<id>.yaml`. `RuleSpec.politica_id`
  nunca escolhe. Sem nenhuma das duas, cada fonte sai NAO_RESOLVIDA com motivo
  `politica_da_execucao_ausente`. O padrão por método (`politica_padrao`) é do motor, que sempre
  passa `politica=`; `temporal/` não importa `rules/`.
- **Critério (`criterio_da_regra`):** é o da política para a fonte. Em M_TEMP, ele só vale se
  fonte, base e deslocamento coincidirem com um critério de `RuleSpec.criterios_temporais`, com a
  mesma semântica do motor. Sem coincidência, a fonte fica sem critério.
- **Fontes:** a seleção cobre cada fonte auxiliar da regra (≠ SIA_PA).
- **NAO_RESOLVIDA, sem base e sem competência:** política `NAO_RESOLVIDA` ou sem critério para
  a fonte. O motivo é o mesmo do motor: `politica_sem_criterio_para_a_fonte fonte=<f>`.
- **NAO_RESOLVIDA com base e competência:** política com documento pendente. O motor encontra a
  chave no `SnapshotSet` e a confere contra a política.
- **NAO_RESOLVIDA por competência ausente:** se a competência base do registro é nula, a seleção
  também fica `NAO_RESOLVIDA`.
- **Competência requerida:** é `base(r) + deslocamento`.
- **Conjunto congelado:** com corte já passado no relógio injetado, o `SnapshotSet` sai com
  `congelado=True` e id derivado do conteúdo. Observações posteriores ao corte não o alteram,
  porque o mesmo conteúdo dá o mesmo id. Corte no futuro, ou ausência de corte, não congela.
- **Ordem canônica:** seleções e ids do `SnapshotSet` são ordenados, então a ordem das fontes na
  regra não muda o id.

| Política | Tipo | Critério |
|---|---|---|
| `B_ATEND` | ALTERNATIVA_EXPLORATORIA | todas as fontes auxiliares por A(r), deslocamento 0 (plano §7) |
| `B_PROC` | ALTERNATIVA_EXPLORATORIA | todas por Q(r), deslocamento 0 |
| `M_TEMP_PADRAO` | NAO_RESOLVIDA | nenhum documento define a competência por regra e fonte; abstenção |

Só será `DOCUMENTADA` uma política que tenha documento preservado (`DocRef` PRESERVADO, com
sha256). Hoje nenhuma tem.

**`SnapshotSet` da execução.** `unir_snapshots` junta os conjuntos por registro em um só, com uma
seleção por chave (fonte, base, competência). Duas decisões diferentes para a mesma chave, ou
cortes diferentes, são erro.

## 5. Lote (`temporal/lote.py`)
O lote parte de uma tabela de registros no DuckDB (`row_id`, `competencia_atendimento`,
`competencia_processamento`). Uma competência fora do padrão AAAAMM conta como nula e resulta
em `competencia_base_ausente`. UF e corte vêm da `RunConfig` da execução, que recusa corte sem
fuso. O critério por regra e fonte é o de `criterio_da_regra`. O DuckDB calcula a competência
requerida por registro, regra e fonte. Cada chave distinta (fonte, base, competência) é decidida pela **mesma**
`selecionar_versao`, e o resultado volta por junção.

A equivalência com a seleção por registro é testada por propriedade (Hypothesis). A tabela
`selecao_versoes` segue `selecao_versoes.v1`. `gravar_selecoes` grava o Parquet e devolve o
`DatasetRef` com o hash lógico `lh1` sobre todas as colunas, na ordem do esquema, com a contagem
real.

O motor (T07) pode derivar a mesma seleção do `SnapshotSet` pela chave (fonte, base, competência).
Também confere a coerência de uma tabela fornecida com a política da execução.

## 6. Vigilância de republicações (T13, `acquisition/watch.py`)
`sustemporal watch --config config/watch.yaml` roda uma passada por chamada:

1. Para cada família de `vigilancia.familias_fontes`, lista o diretório. A listagem é ela mesma
   uma observação.
2. Toma as `janela_competencias` (6) competências mais recentes com arquivo listado para a UF,
   dentro do recorte do estudo (201801–202512) e nunca depois do mês do relógio.
   - A janela vem dos nomes listados, nunca da data de coleta. A travessia dos meses usa
     `CompetenciaArquivo.deslocar`, sem converter o código em número.
   - Depois de 2025-12 a janela para de andar e fica nas 6 últimas competências de 2025.
   - Observar além do recorte é decisão humana (T13-6, recorte na `RunConfig`).
   - Um arquivo já acompanhado (competência ou parte) que some de uma listagem obtida não é
     trocado em silêncio por uma competência mais antiga. Ele vira INCONCLUSIVO
     (`sumiu_da_listagem`) e conta como falha. Isso vale para competências do início da janela
     atual em diante; as mais antigas saíram da janela porque chegaram competências novas.
3. Observa de novo cada arquivo (`observe_updates`), sem pular os já obtidos. Os mesmos bytes
   viram nova observação da mesma versão; bytes novos viram versão nova. O histórico não é
   substituído.
4. Compara cada arquivo SIA-PA com a versão obtida antes para a mesma chave (fonte, UF,
   competência, parte), em `acquisition/comparacao.py`. As duas versões passam pelo
   `normalize_pa` e são comparadas como multiconjuntos de linhas **ativas**, isto é, não
   deletadas.
   - Ficam de fora as colunas de papel CHAVE e LINHAGEM do esquema `sia_pa.v1` (`row_id`,
     `artifact_id`, `membro`, `indice_registro`, `deletado`). A lista é derivada do esquema.
   - Linhas nunca são casadas por posição.
   - Registros que mudaram de estado de deleção são contados à parte (`mudancas_de_delecao`). Um
     registro que passa a deletado conta como saída das ativas, e portanto como REVISAO_REAL; um
     que deixa de ser deletado conta como entrada.
   - **INALTERADA:** mesmos bytes, ou as mesmas linhas com as mesmas multiplicidades (inclusive
     em outra ordem).
   - **REVISAO_REAL:** só entraram linhas, ou só saíram.
   - **CORRESPONDENCIA_AMBIGUA:** saíram e entraram linhas. O conteúdo mudou, mas sem
     identificador longitudinal não se sabe que linha antiga virou qual nova. Só as contagens
     são registradas, sem pareamento.
   - **INCONCLUSIVO:** a comparação não normaliza (quarentena, arquivo guardado ausente, leiaute
     incompatível), ou a nova observação de um arquivo já acompanhado falhou
     (`observacao_sem_conteudo`, por exemplo NAO_ENCONTRADO ou INTERROMPIDO), ou o arquivo
     sumiu da listagem. Fica no relatório com o motivo e faz a execução sair com falha
     operacional (5). Nunca é tratada como ausência de revisão.
5. Acrescenta a `<raiz_manifestos>/vigilancia.jsonl` uma linha por comparação e um resumo. O
   resumo só fala das observações da pesquisa (`sem_revisao_observada … de=… ate=…
   alcance=somente_observacoes_da_pesquisa`). Com comparação inconclusiva e nenhuma revisão, o
   resumo é `vigilancia_inconclusiva`. **Ausência de revisão observada não afirma que
   nunca houve revisão:** uma republicação entre duas observações, ou antes da primeira, pode
   ter escapado.

Famílias sem normalizador (CNES, SIGTAP) são observadas, e versões novas aparecem no manifesto,
mas não são comparadas linha a linha.

**Vigilância não é coorte.** A vigilância segue o plano (T13: "A partir do piloto, acompanhar
semanalmente uma janela móvel de seis competências recentes durante doze meses"), dentro do
recorte 2018–2025, que é restrição do AGENTS.md. As observações dela não escolhem a coorte, que
vem da própria config (piloto, coorte e partições). Uma republicação observada de uma competência
da coorte só pesa nela pela seleção do T06, com o corte de observação congelado da execução.

**Agendamento (máquina do pesquisador).** A cadência de 7 dias e a duração de 12 meses
(`cadencia_dias`, `duracao_meses`) são cumpridas pelo agendador, não pela CLI. Exemplo de cron,
toda segunda às 03:17:

```cron
17 3 * * 1  cd /caminho/sus-temporal && uv run sustemporal watch --config config/watch.yaml >> logs/watch.log 2>&1
```

Ou com systemd (`~/.config/systemd/user/sustemporal-watch.service` e `.timer`):

```ini
# sustemporal-watch.service
[Service]
Type=oneshot
WorkingDirectory=/caminho/sus-temporal
ExecStart=/usr/bin/env uv run sustemporal watch --config config/watch.yaml

# sustemporal-watch.timer
[Timer]
OnCalendar=Mon *-*-* 03:17:00
Persistent=true
[Install]
WantedBy=timers.target
```

Depois de 12 meses, desative o timer (`systemctl --user disable --now sustemporal-watch.timer`)
ou remova a linha do cron.

## 7. Limites declarados
- A retrospectiva não simula o conhecimento do gestor na data original. Ela usa as versões que a
  pesquisa conseguiu observar até o corte.
- **Ausência de observação não é ausência de publicação.** AUSENTE quer dizer que a pesquisa não
  obteve o arquivo, e a avaliação dependente fica INCONCLUSIVO.
- Vigência de vínculo não é interpolada entre meses ausentes.
