# Import MyInvestor (PDF Inversis) → `asset_transactions`

Script de un solo uso. Coloca el PDF en `pdfs/` (p. ej. `MSF.DE.pdf`) y ejecuta desde **`backend/`** con el venv activo.

```bash
cd finance_portfolio/backend
source .venv/bin/activate
pip install pypdf   # solo la primera vez
```

## Preproducción (`.env.server`)

**Prueba (no escribe en la BD):**

```bash
python -m scripts.myinvestor_pdf_import.import_transactions \
  --profile pre \
  --ticker MSF.DE \
  --dry-run \
  --verbose
```

**Import real:**

```bash
python -m scripts.myinvestor_pdf_import.import_transactions \
  --profile pre \
  --ticker MSF.DE
```

## Local (`.env`)

**Prueba:**

```bash
python -m scripts.myinvestor_pdf_import.import_transactions \
  --ticker MSF.DE \
  --dry-run
```

**Import real:**

```bash
python -m scripts.myinvestor_pdf_import.import_transactions \
  --ticker MSF.DE
```

## Notas

- `--ticker`: debe existir en `asset_types` (ej. `MSF.DE`).
- Por defecto lee `scripts/myinvestor_pdf_import/pdfs/`. Otro directorio: `--pdf-dir /ruta/a/pdfs`.
- `--dry-run`: muestra filas y `executed_at` que se usarían; **no inserta**.
- Sin `--dry-run`: inserta en `asset_transactions` (`exchange_trade_id` = columna Transacción del PDF).
- Equivalente a `--profile pre`: `APP_PROFILE=server` antes del comando.

Cuando termines la carga, borra esta carpeta y los PDF; no hace falta commitear.
