-- Rellena total_liquid, total_invested y total_net_worth en registros existentes
-- a partir de los balances ya guardados (ejecutar una vez tras añadir las columnas).

UPDATE monthly_records mr
SET
  total_liquid = COALESCE(calc.total_liquid, 0),
  total_invested = COALESCE(calc.total_invested, 0),
  total_net_worth = COALESCE(calc.total_liquid, 0) + COALESCE(calc.total_invested, 0)
FROM (
  SELECT
    mr2.id AS record_id,
    COALESCE(simple.liquid, 0) + COALESCE(hybrid.liquid, 0) AS total_liquid,
    COALESCE(simple.invested, 0) + COALESCE(hybrid.invested, 0) AS total_invested
  FROM monthly_records mr2
  LEFT JOIN (
    SELECT
      meb.record_id,
      SUM(meb.balance_amount) FILTER (WHERE e.entity_type = 'LIQUID') AS liquid,
      SUM(meb.balance_amount) FILTER (WHERE e.entity_type = 'INVESTED') AS invested
    FROM monthly_entity_balances meb
    JOIN entities e ON e.id = meb.entity_id
    GROUP BY meb.record_id
  ) simple ON simple.record_id = mr2.id
  LEFT JOIN (
    SELECT
      mha.record_id,
      SUM(mha.liquid_amount) AS liquid,
      SUM(mha.cumulative_invested) AS invested
    FROM monthly_hybrid_accounts mha
    GROUP BY mha.record_id
  ) hybrid ON hybrid.record_id = mr2.id
) calc
WHERE mr.id = calc.record_id;
