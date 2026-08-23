-- ============================================================
-- Finance Portfolio · Categoría de inversión por defecto en entities
-- Requiere que investment_categories ya exista (crypto/fondos/acciones)
-- ============================================================

BEGIN;

ALTER TABLE entities
    ADD COLUMN IF NOT EXISTS default_category_id VARCHAR(30) REFERENCES investment_categories(id);

-- Ejemplo: clasifica KuCoin como Crypto por defecto (ajusta el id si es distinto en tu BD)
-- UPDATE entities SET default_category_id = 'crypto' WHERE id = 'kucoin';

COMMIT;

-- Verificación rápida:
-- \d entities
