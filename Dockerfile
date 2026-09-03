FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    unzip \
    php-cli \
    php-gd \
    php-xml \
    php-mbstring \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

COPY requirements.txt .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . .

RUN composer install --no-dev --optimize-autoloader --working-dir=/app/backend/danfse

RUN mkdir -p /app/storage /app/data /app/data/tmp_worker

EXPOSE 8000

# O PostgreSQL de producao nao e alterado pelo lifespan da API. Execute a
# migracao como etapa obrigatoria do container para que uma versao que usa
# colunas novas nunca comece a receber trafego com o schema antigo.
CMD ["sh", "-c", "python -m backend.app.scripts.migrar_banco && exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
