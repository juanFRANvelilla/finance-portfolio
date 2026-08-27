-- Elimina default_category_id (sustituido por fiat_deposits.entity_id + preview en backend)

BEGIN;

UPDATE entities SET default_category_id = NULL WHERE default_category_id IS NOT NULL;

ALTER TABLE entities DROP COLUMN IF EXISTS default_category_id;

COMMIT;
