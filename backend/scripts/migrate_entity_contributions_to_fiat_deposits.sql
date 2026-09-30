-- Migra entity_contributions → fiat_deposits y elimina el modelo antiguo.
-- Ejecutar contra finance_portfolio (psql o cliente SQL) con backup previo.
--
-- Nota: entity_contributions.notes no tiene columna destino en fiat_deposits;
-- si necesitas conservar notas, añade antes: ALTER TABLE fiat_deposits ADD COLUMN notes VARCHAR(200);

BEGIN;

-- Vista previa (opcional, comentar si ejecutas solo el bloque de abajo)
-- SELECT ec.id, ec.entity_id, ec.amount, ec.contribution_date, ec.notes
-- FROM entity_contributions ec
-- ORDER BY ec.contribution_date, ec.created_at;

INSERT INTO fiat_deposits (id, entity_id, amount, deposit_date, created_at)
SELECT
    ec.id,
    ec.entity_id,
    ec.amount,
    ec.contribution_date,
    ec.created_at
FROM entity_contributions ec
WHERE NOT EXISTS (
    SELECT 1 FROM fiat_deposits fd WHERE fd.id = ec.id
);

DROP TABLE IF EXISTS entity_contributions;

ALTER TABLE entities DROP COLUMN IF EXISTS uses_contribution_ledger;

COMMIT;
