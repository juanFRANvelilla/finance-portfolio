# Pendientes (diseño / infra)

## Ajuste híbrido tras compras/ventas automáticas

- [ ] Servicio post-snapshot: deltas de `liquid_amount` (EUR) + recalc `invested_amount` = suma activos vinculados (misma lógica que `sum_linked_asset_investments_eur`).
- [ ] Comprobar filas del mes en `monthly_entity_positions` y `monthly_asset_investments` antes de aplicar; si faltan → log y skip.
- [ ] MyInvestor **ventas** por mail: reglas de líquido/invertido (TODO cuando haya ejemplo de correo).
- [ ] **trade_republic**: mails / sync de compras y transferencias.
- [ ] Cache Redis: “mes (year, month) abierto” para activos y entidades, evitar consultas repetidas en cada fill (opcional).

## BD

- [x] Trigger `asset_types.entity_id` → entidad HYBRID (si aplica).
