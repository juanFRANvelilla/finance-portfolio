-- Migración: monthly_records solo almacena metadatos del mes.
-- Ejecutar contra finance_portfolio cuando la tabla aún tenga columnas de totales.

ALTER TABLE monthly_records
  DROP COLUMN IF EXISTS total_liquid,
  DROP COLUMN IF EXISTS total_invested,
  DROP COLUMN IF EXISTS total_net_worth,
  DROP COLUMN IF EXISTS monthly_diff,
  DROP COLUMN IF EXISTS invested_percentage;
