-- ============================================================
-- Finance Portfolio · Limpieza + migración IDs a UUID
-- Base de datos: finance_portfolio
-- Entorno de prueba: borra todos los datos mensuales
-- ============================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) Eliminar tablas dependientes (CASCADE limpia FKs)
DROP TABLE IF EXISTS monthly_entity_balances CASCADE;
DROP TABLE IF EXISTS monthly_hybrid_accounts CASCADE;
DROP TABLE IF EXISTS monthly_records CASCADE;

-- 2) Recrear monthly_records (solo metadatos; totales se calculan en backend)
CREATE TABLE monthly_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    year INT NOT NULL,
    month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_record_year_month UNIQUE (year, month)
);

-- 3) Entidades simples (Santander, Sabadell, KuCoin)
CREATE TABLE monthly_entity_balances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL REFERENCES monthly_records(id) ON DELETE CASCADE,
    entity_id VARCHAR(30) NOT NULL REFERENCES entities(id),
    balance_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    CONSTRAINT uq_balance_record_entity UNIQUE (record_id, entity_id)
);

-- 4) Cuentas híbridas (MyInvestor, Trade Republic)
CREATE TABLE monthly_hybrid_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL REFERENCES monthly_records(id) ON DELETE CASCADE,
    entity_id VARCHAR(30) NOT NULL REFERENCES entities(id),
    liquid_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    monthly_contribution NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    cumulative_invested NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    CONSTRAINT uq_hybrid_record_entity UNIQUE (record_id, entity_id)
);

COMMIT;

-- Verificación rápida:
-- \d monthly_records
-- \d monthly_entity_balances
-- \d monthly_hybrid_accounts
