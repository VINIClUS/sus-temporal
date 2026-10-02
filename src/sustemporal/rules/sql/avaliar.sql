-- Avaliação V(r, g, S, p) de uma regra sobre todos os registros (docs/method/model.md §3).
-- Uma linha por registro: só LEFT JOIN por chave única (seleção, conjunto, integridade) e testes
-- existenciais no predicado; os marcadores de campo e predicado vêm de allowlist e de arquivos fixos.
WITH base AS (
    SELECT
        r.row_id,
        r.artifact_id,
        r.instrumento,
        r.procedimento,
        r.cbo,
        r.cnes,
        r.competencia_processamento,
        s.fonte AS sel_fonte,
        s.base AS sel_base,
        s.competencia_requerida AS sel_competencia,
        s.estado AS sel_estado,
        s.artifact_ids AS sel_artefatos,
        s.observation_ids AS sel_observacoes,
        s.motivo AS sel_motivo,
        k.fora AS sel_fora,
        k.escopo_vazio AS sel_escopo_vazio,
        k.todas_com_linhas AS sel_todas_com_linhas,
        k.integridade AS sel_integridade,
        k.integridade_ok AS sel_integridade_ok,
        coalesce(ir.estado, 'NAO_VERIFICADO') AS integridade_registro,
        {campo_faltando} AS campo_faltando,
        CASE $vig_tipo
            WHEN 'ATENDIMENTO' THEN r.competencia_atendimento
            WHEN 'PROCESSAMENTO' THEN r.competencia_processamento
        END AS comp_vigencia
    FROM registros AS r
    LEFT JOIN selecoes AS s
        ON s.row_id = r.row_id AND s.rule_id = $rule_id AND s.fonte = $fonte
    LEFT JOIN conjuntos AS k
        ON k.chave = s.artifact_ids AND s.estado = 'SELECIONADA'
    LEFT JOIN integridade AS ir
        ON ir.artifact_id = r.artifact_id
),
aplicabilidade AS (
    SELECT
        *,
        CASE
            WHEN instrumento IS NULL THEN 'DESCONHECIDA'
            WHEN NOT list_contains($instrumentos, instrumento) THEN 'NAO_APLICAVEL_DEMONSTRADA'
            WHEN $tem_vigencia AND comp_vigencia IS NULL THEN 'DESCONHECIDA'
            WHEN $tem_vigencia AND (
                comp_vigencia < coalesce($vig_inicio, comp_vigencia)
                OR comp_vigencia > coalesce($vig_fim, comp_vigencia)
            ) THEN 'NAO_APLICAVEL_DEMONSTRADA'
            ELSE 'APLICAVEL'
        END AS aplicabilidade_previa,
        instrumento IS NOT NULL
            AND NOT list_contains($instrumentos, instrumento) AS fora_dos_instrumentos
    FROM base
),
insumos AS (
    SELECT
        *,
        list_filter(
            [
                CASE WHEN $politica_nao_resolvida THEN 'POLITICA_NAO_RESOLVIDA' END,
                CASE
                    WHEN starts_with(integridade_registro, 'QUARENTENA_')
                        THEN 'ARQUIVO_EM_QUARENTENA'
                END,
                CASE WHEN campo_faltando THEN 'CAMPO_INSUFICIENTE' END,
                CASE coalesce(sel_estado, 'SEM_SELECAO')
                    WHEN 'SEM_SELECAO' THEN 'VIGENCIA_NAO_RESOLVIDA'
                    WHEN 'AUSENTE' THEN 'ARQUIVO_AUSENTE'
                    WHEN 'AMBIGUA' THEN 'VERSAO_AMBIGUA'
                    WHEN 'INCOMPLETA' THEN 'COBERTURA_INSUFICIENTE'
                    WHEN 'EM_QUARENTENA' THEN 'ARQUIVO_EM_QUARENTENA'
                    WHEN 'FORA_DO_CORTE' THEN 'FORA_DO_CORTE'
                    WHEN 'NAO_RESOLVIDA' THEN 'VIGENCIA_NAO_RESOLVIDA'
                    WHEN 'SELECIONADA' THEN CASE
                        WHEN $leiaute <> 'OK' THEN $leiaute
                        WHEN sel_fora THEN 'ARQUIVO_AUSENTE'
                        WHEN sel_escopo_vazio THEN 'COBERTURA_INSUFICIENTE'
                    END
                END
            ],
            m -> m IS NOT NULL
        ) AS motivos_previos
    FROM aplicabilidade
),
alvo AS (
    SELECT * FROM insumos
    WHERE aplicabilidade_previa = 'APLICAVEL' AND len(motivos_previos) = 0
),
alvo_artefato AS (
    SELECT row_id, unnest(string_split(sel_artefatos, ';')) AS artifact_id FROM alvo
),
predicado AS (
{predicado}
),
fatos AS (
    SELECT
        i.*,
        p.resultado,
        coalesce(p.n_resultados, 0) AS n_resultados,
        p.parametros,
        p.chave,
        (
            SELECT c.estado FROM cobertura AS c
            WHERE c.familia_regra = $familia
                AND c.instrumento = i.instrumento
                AND c.competencia = i.competencia_processamento
                AND c.base_temporal = i.sel_base
        ) AS cobertura_estado
    FROM insumos AS i
    LEFT JOIN predicado AS p ON p.row_id = i.row_id
),
decisao AS (
    SELECT
        *,
        CASE
            WHEN aplicabilidade_previa <> 'APLICAVEL' THEN aplicabilidade_previa
            WHEN resultado = 'APLICABILIDADE_DESCONHECIDA' THEN 'DESCONHECIDA'
            ELSE 'APLICAVEL'
        END AS aplicabilidade,
        CASE
            WHEN aplicabilidade_previa = 'DESCONHECIDA'
                THEN ['APLICABILIDADE_DESCONHECIDA', 'CAMPO_INSUFICIENTE']
            WHEN aplicabilidade_previa = 'NAO_APLICAVEL_DEMONSTRADA' THEN CAST([] AS VARCHAR[])
            WHEN len(motivos_previos) > 0 THEN list_sort(list_distinct(motivos_previos))
            WHEN resultado = 'CORRESPONDENCIA' THEN CAST([] AS VARCHAR[])
            WHEN resultado = 'AUSENCIA'
                AND cobertura_estado = 'DISPONIVEL'
                AND sel_integridade_ok
                AND sel_todas_com_linhas THEN CAST([] AS VARCHAR[])
            WHEN resultado = 'AUSENCIA' THEN ['COBERTURA_INSUFICIENTE']
            ELSE [resultado]
        END AS motivos
    FROM fatos
),
estados AS (
    SELECT
        *,
        CASE
            WHEN aplicabilidade <> 'APLICAVEL' OR len(motivos) > 0 THEN NULL
            ELSE resultado = 'AUSENCIA'
        END AS incompatibilidade_demonstrada,
        len(list_filter(motivos, m -> m <> 'APLICABILIDADE_DESCONHECIDA')) = 0
            AS insumos_completos
    FROM decisao
),
classificados AS (
    SELECT
        *,
        CASE
            WHEN aplicabilidade = 'NAO_APLICAVEL_DEMONSTRADA' THEN 'NAO_APLICAVEL'
            WHEN incompatibilidade_demonstrada IS NULL THEN 'INCONCLUSIVO'
            WHEN incompatibilidade_demonstrada THEN 'VIOLACAO'
            ELSE 'CONFORME'
        END AS estado
    FROM estados
),
evidencias AS (
    SELECT
        *,
        CASE estado
            WHEN 'NAO_APLICAVEL' THEN 'APLICABILIDADE'
            WHEN 'CONFORME' THEN 'VINCULO_ENCONTRADO'
            WHEN 'VIOLACAO' THEN 'AUSENCIA_NA_FONTE'
        END AS ev_tipo,
        CASE
            WHEN estado <> 'NAO_APLICAVEL' THEN $query_id
            WHEN fora_dos_instrumentos THEN 'aplicabilidade.instrumento'
            ELSE 'aplicabilidade.vigencia'
        END AS ev_query_id,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN $sql_sha256_aplicabilidade ELSE $sql_sha256 END
            AS ev_sql_sha256,
        CASE
            WHEN estado <> 'NAO_APLICAVEL' THEN parametros
            WHEN fora_dos_instrumentos
                THEN to_json({'instrumento': instrumento, 'rule_id': $rule_id})::VARCHAR
            ELSE to_json({'competencia': comp_vigencia, 'rule_id': $rule_id})::VARCHAR
        END AS ev_parametros,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN $ds_registro ELSE $ds_auxiliar END
            AS ev_dataset_id,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN $hash_registro ELSE $hash_auxiliar END
            AS ev_hash_logico,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN artifact_id ELSE sel_artefatos END
            AS ev_artifact_ids,
        CASE
            WHEN estado = 'NAO_APLICAVEL' THEN 'DISPONIVEL'
            ELSE coalesce(cobertura_estado, 'AUSENTE')
        END AS ev_cobertura,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN integridade_registro ELSE sel_integridade END
            AS ev_integridade,
        CASE WHEN estado = 'NAO_APLICAVEL' THEN 0 ELSE n_resultados END AS ev_n_resultados,
        CASE
            WHEN estado = 'CONFORME' THEN to_json([chave])::VARCHAR
            ELSE '[]'
        END AS ev_chaves_amostra
    FROM classificados
)
SELECT
    row_id,
    $rule_id AS rule_id,
    estado,
    aplicabilidade,
    insumos_completos,
    incompatibilidade_demonstrada,
    array_to_string(motivos, ';') AS motivos,
    sel_fonte,
    sel_base,
    sel_competencia,
    sel_estado,
    sel_artefatos,
    sel_observacoes,
    sel_motivo,
    CASE WHEN ev_tipo IS NOT NULL THEN 'ev_' || sha256(concat_ws(
        chr(31), ev_tipo, ev_query_id, ev_sql_sha256, ev_parametros, ev_dataset_id,
        ev_hash_logico, ev_artifact_ids, ev_cobertura, ev_integridade,
        CAST(ev_n_resultados AS VARCHAR), ev_chaves_amostra
    )) END AS ev_id,
    ev_tipo,
    ev_query_id,
    ev_sql_sha256,
    ev_parametros,
    ev_dataset_id,
    ev_hash_logico,
    ev_artifact_ids,
    ev_cobertura,
    ev_integridade,
    ev_n_resultados,
    ev_chaves_amostra
FROM evidencias
