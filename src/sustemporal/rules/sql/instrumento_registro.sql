-- INSTRUMENTO_REGISTRO (model.md §4.3): mapa_registro (PA_DOCORIG→CO_REGISTRO) INFERIDA dos
-- rótulos; instrumento fora do mapa já foi para CAMPO_INSUFICIENTE antes do predicado.
WITH alvo_mapeado AS (
    SELECT t.row_id, t.procedimento, m.co_registro
    FROM alvo AS t JOIN mapa_registro AS m ON m.instrumento = t.instrumento
)
SELECT
    t.row_id,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id
                AND a.co_procedimento = t.procedimento AND a.co_registro = t.co_registro
        ) THEN 'CORRESPONDENCIA'
        WHEN NOT EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id AND a.co_procedimento = t.procedimento
        ) THEN 'COBERTURA_INSUFICIENTE'
        ELSE 'AUSENCIA'
    END AS resultado,
    (
        SELECT count(*) FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
        WHERE s.row_id = t.row_id
            AND a.co_procedimento = t.procedimento AND a.co_registro = t.co_registro
    ) AS n_resultados,
    to_json({'co_registro': t.co_registro, 'procedimento': t.procedimento})::VARCHAR
        AS parametros,
    t.procedimento || '|' || t.co_registro AS chave
FROM alvo_mapeado AS t
