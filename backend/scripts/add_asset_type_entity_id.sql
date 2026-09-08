-- Vincula opcionalmente un activo del catálogo a una entidad (p. ej. posiciones Crypto → KuCoin).

ALTER TABLE asset_types
ADD COLUMN IF NOT EXISTS entity_id VARCHAR(30) REFERENCES entities(id);

CREATE INDEX IF NOT EXISTS idx_asset_types_entity_id ON asset_types(entity_id);
