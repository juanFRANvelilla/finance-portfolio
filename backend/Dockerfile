# Etapa 1: dependencias en un venv
FROM python:3.12-slim AS build

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Etapa 2: tests unitarios (unittest, sin BD ni red).
# No se copia a la imagen final, pero Kaniko/Docker construyen todas las
# etapas del Dockerfile en orden aunque no se usen en la etapa final, así que
# si un test falla, el build entero falla antes de llegar a "Build and Push".
FROM build AS test

COPY app ./app
COPY tests ./tests

# Dummy: app.core.config.Settings exige database_url al importarse, pero estos
# tests no abren conexión real a ninguna BD.
ENV DATABASE_URL="postgresql://test:test@localhost:5432/test"

RUN python -m unittest discover -s tests -t . -v

# Etapa 3: runtime
FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 1001 appuser

COPY --from=build /opt/venv /opt/venv
COPY app ./app

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
