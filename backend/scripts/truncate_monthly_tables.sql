-- ============================================================
-- Solo borrar datos (mantener estructura actual SERIAL/INT)
-- ============================================================

TRUNCATE TABLE monthly_entity_balances, monthly_hybrid_accounts, monthly_records
RESTART IDENTITY CASCADE;
