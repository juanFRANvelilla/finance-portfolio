# Finance Portfolio

Monorepo de una aplicación de finanzas personales para el seguimiento mensual del patrimonio (capital líquido vs invertido), pensada para uso local sin autenticación.

## Estructura

```
finance_portfolio/
  backend/     API REST con FastAPI + SQLAlchemy + Pydantic
  frontend/    SPA con Angular (standalone) + Tailwind CSS + Chart.js
  run.sh       Arranca backend y frontend a la vez
```

Consulta el README de cada paquete para más detalle:

- [`backend/README.md`](./backend/README.md)
- [`frontend/README.md`](./frontend/README.md)

## Requisitos previos

- **PostgreSQL** corriendo en local (`localhost:5432`), con la base de datos `finance_portfolio` y las tablas `entities`, `monthly_records`, `monthly_entity_balances` ya creadas (y `monthly_hybrid_accounts`, que no se usa todavía).
- Python 3.11+
- Node.js 20+ y npm

## Arranque rápido (todo el stack)

```bash
./run.sh
```

Esto levanta:

- Backend FastAPI en `http://localhost:8000` (Swagger UI en `/docs`)
- Frontend Angular en `http://localhost:4200`

## Arranque por separado

```bash
# Terminal 1
cd backend && ./run.sh

# Terminal 2
cd frontend && ./run.sh
```

## Notas de diseño

- El backend mapea modelos SQLAlchemy sobre las tablas ya existentes en `finance_portfolio`; no gestiona migraciones (no se usa Alembic).
- Los totales (`total_liquid`, `total_invested`, etc.) **no se persisten**; se calculan al vuelo en el backend y se envían como DTO.
- El endpoint `POST /api/records/{year}/{month}/import` valida `expected_totals` y persiste solo balances.
- CORS está habilitado en el backend únicamente para `http://localhost:4200`.
