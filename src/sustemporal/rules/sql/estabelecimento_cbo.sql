-- ESTABELECIMENTO_CBO (model.md §4.2): par estabelecimento–CBO no CNES PF reduzido a contagens.
-- Nunca identifica nem infere o vínculo de um profissional específico.
SELECT
    t.row_id,
    CASE
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id
                AND a.cnes = t.cnes AND a.cbo = t.cbo AND a.n_vinculos > 0
        ) THEN 'CORRESPONDENCIA'
        WHEN EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id
                AND (a.cnes = t.cnes OR a.cnes IS NULL)
                AND (a.cbo = t.cbo OR a.cbo IS NULL)
                AND (a.n_vinculos > 0 OR a.n_vinculos IS NULL)
                AND (a.cnes IS NULL OR a.cbo IS NULL OR a.n_vinculos IS NULL)
        ) THEN 'CAMPO_INSUFICIENTE'
        WHEN NOT EXISTS (
            SELECT 1 FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
            WHERE s.row_id = t.row_id AND a.cnes = t.cnes
        ) THEN 'COBERTURA_INSUFICIENTE'
        ELSE 'AUSENCIA'
    END AS resultado,
    (
        SELECT count(*) FROM alvo_artefato AS s JOIN aux AS a ON a.artifact_id = s.artifact_id
        WHERE s.row_id = t.row_id
            AND a.cnes = t.cnes AND a.cbo = t.cbo AND a.n_vinculos > 0
    ) AS n_resultados,
    to_json({'cbo': t.cbo, 'cnes': t.cnes})::VARCHAR AS parametros,
    t.cnes || '|' || t.cbo AS chave
FROM alvo AS t
