-- Punto 3 ventas KuCoin / PMP (aplicar una vez en pre/pro si no está ya)
ALTER TABLE asset_transactions ALTER COLUMN invested_amount DROP NOT NULL;

ALTER TABLE asset_sales ADD COLUMN IF NOT EXISTS net_liquidity NUMERIC(18, 4);

UPDATE asset_sales
SET net_liquidity = (sale_price * units) - fee
WHERE net_liquidity IS NULL;

ALTER TABLE asset_sales ALTER COLUMN net_liquidity SET NOT NULL;
