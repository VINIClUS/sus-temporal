-- VIGENCIA_PROCEDIMENTO (model.md §4.4): procedimento presente em tb_procedimento selecionada.
SELECT
    t.row_id,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id AND a.co_procedimento = t.procedimento
        ) THEN 'CORRESPONDENCIA'
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id AND a.co_procedimento IS NULL
        ) THEN 'CAMPO_INSUFICIENTE'
        ELSE 'AUSENCIA'
    END AS resultado,
    (
        SELECT count(*) FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
        WHERE s.row_id = t.row_id AND a.co_procedimento = t.procedimento
    ) AS n_resultados,
    to_json({'procedimento': t.procedimento})::VARCHAR AS parametros,
    t.procedimento AS chave
FROM alvo AS t
