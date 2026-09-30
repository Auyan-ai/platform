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

# Precompilar bytecode (dependencias + app). Poetry no genera los .pyc al instalar:
# sin esto, cada arranque en frío de Cloud Run recompila langchain/langgraph/
# anthropic/openai… con 1 vCPU (~14 s antes de que uvicorn escuche).
RUN python -m compileall -q -j 0 /usr/local/lib/python3.12/site-packages /app/apps

EXPOSE 8000

CMD ["sh", "-c", "uvicorn apps.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
