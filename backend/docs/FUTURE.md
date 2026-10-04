# Pendientes (diseño / infra)

## Ajuste híbrido tras compras/ventas automáticas

- [x] Servicio post-snapshot: `hybrid_entity_auto_adjust.py` (KuCoin + MyInvestor compras).
- [x] Comprobar filas del mes antes de aplicar; si faltan → skip + log.
- [ ] MyInvestor **ventas** por mail: reglas de líquido/invertido (TODO cuando haya ejemplo de correo).
- [ ] **trade_republic**: mails / sync de compras y transferencias.
- [ ] Cache Redis: “mes (year, month) abierto” para activos y entidades, evitar consultas repetidas en cada fill (opcional).

## BD

- [x] Trigger `asset_types.entity_id` → entidad HYBRID (si aplica).
