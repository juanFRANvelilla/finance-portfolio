-- Aportación mensual fija por activo (catálogo asset_types).
-- Se suma al importe del mes anterior para calcular la previsión del detalle de inversión.

ALTER TABLE asset_types
    ADD COLUMN IF NOT EXISTS monthly_contribution NUMERIC(12, 2) NULL;

COMMENT ON COLUMN asset_types.monthly_contribution IS
    'Fixed monthly contribution in the asset native currency (EUR/USD). NULL = no automatic contribution.';
