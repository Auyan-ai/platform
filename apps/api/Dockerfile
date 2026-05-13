FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "poetry==1.8.4"

# Copiar solo el manifiesto primero (capa de caché)
COPY apps/api/pyproject.toml apps/api/

# Instalar dependencias de producción sin virtualenv
RUN cd apps/api \
    && poetry config virtualenvs.create false \
    && poetry install --without dev --no-interaction --no-ansi

# Copiar el repo completo (los imports son apps.api.*)
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
