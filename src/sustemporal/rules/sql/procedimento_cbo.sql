-- PROCEDIMENTO_CBO (model.md §4.1): testes existenciais em sigtap_proc_ocupacao no escopo selecionado.
SELECT
    t.row_id,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id
                AND a.co_procedimento = t.procedimento AND a.co_ocupacao = t.cbo
        ) THEN 'CORRESPONDENCIA'
        WHEN NOT EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id AND a.co_procedimento = t.procedimento
        ) THEN 'APLICABILIDADE_DESCONHECIDA'
        ELSE 'AUSENCIA'
    END AS resultado,
    (
        SELECT count(*) FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
        WHERE s.row_id = t.row_id
            AND a.co_procedimento = t.procedimento AND a.co_ocupacao = t.cbo
    ) AS n_resultados,
    to_json({'cbo': t.cbo, 'procedimento': t.procedimento})::VARCHAR AS parametros,
    t.procedimento || '|' || t.cbo AS chave
FROM alvo AS t
