FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "poetry==1.8.4"

# Copiar manifiestos primero para cache de capas de dependencias
COPY apps/api/pyproject.toml apps/api/poetry.lock apps/api/

RUN cd apps/api \
    && poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

# Copiar repo completo (imports son apps.api.*)
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
