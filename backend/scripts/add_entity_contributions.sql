-- Libro de aportaciones / retiradas por entidad
-- Ejecutar si aún no existe la tabla en finance_portfolio

BEGIN;

CREATE TABLE IF NOT EXISTS entity_contributions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           VARCHAR(30) NOT NULL REFERENCES entities(id),
    contribution_date   DATE NOT NULL,
    amount              NUMERIC(12, 2) NOT NULL CHECK (amount <> 0),
    notes               VARCHAR(200),
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_entity_contributions_entity_date
    ON entity_contributions (entity_id, contribution_date);

ALTER TABLE monthly_hybrid_accounts
    DROP COLUMN IF EXISTS monthly_contribution;

COMMIT;
