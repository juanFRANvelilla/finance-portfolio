# Finance Portfolio · Backend

API REST construida con **FastAPI + SQLAlchemy + Pydantic** para el seguimiento mensual de patrimonio personal (líquido vs invertido). Sin autenticación, pensada para uso local.

## Requisitos

- Python 3.11+
- PostgreSQL corriendo en local con la base de datos `finance_portfolio` y las tablas `entities`, `monthly_records`, `monthly_entity_balances` ya creadas.

## Configuración

Variables de entorno en `.env` (ya incluido con los valores indicados):

```
DATABASE_URL=postgresql://postgres:juanfran@localhost:5432/finance_portfolio
CORS_ORIGINS=http://localhost:4200
```

## Arranque rápido

```bash
./run.sh
```

Esto crea un virtualenv en `.venv`, instala dependencias y levanta el servidor en `http://localhost:8000` (documentación interactiva en `http://localhost:8000/docs`).

## Arranque manual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Estructura

```
app/
  core/       # configuración y conexión a la base de datos
  models/     # modelos SQLAlchemy (Entity, MonthlyRecord, MonthlyEntityBalance)
  schemas/    # schemas Pydantic de entrada/salida
  routers/    # endpoints agrupados por recurso
  main.py     # instancia de FastAPI, CORS y montaje de routers
```

## Endpoints principales

| Método | Ruta                              | Descripción                                                            |
| ------ | --------------------------------- | ------------------------------------------------------------------------ |
| GET    | `/api/entities`                   | Listado de entidades activas                                            |
| GET    | `/api/records/{year}/{month}`     | Totales del mes, balances por entidad y diff con el mes anterior         |
| POST   | `/api/records/{year}/{month}`     | Guarda/actualiza balances del mes y recalcula totales derivados         |
| POST   | `/api/records/import-json`        | Placeholder para ingesta masiva de meses históricos vía JSON (TODO)     |
| GET    | `/api/health`                     | Healthcheck                                                              |

Nota: los modelos SQLAlchemy están mapeados sobre tablas ya existentes (no se generan migraciones automáticas); asegúrate de que el esquema de la base de datos coincide con `app/models`.
