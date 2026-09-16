# Tangent API.
#
# Runtime only: the embedding stack (torch, ~590 MB) is deliberately absent.
# app/embed.py imports sentence_transformers inside a lazily-called function and
# the API never calls it, so computing embeddings stays a local task run against
# the same database - see requirements-embed.txt.
FROM python:3.11-slim

# libpq is not needed: psycopg[binary] ships its own. curl is here only so the
# platform's health check has something to call from inside the container.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first, so a code change does not reinstall the dependency layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Never run as root in a container that talks to the internet.
RUN useradd --create-home --uid 10001 tangent \
 && chown -R tangent:tangent /app
USER tangent

EXPOSE 8000

# Platforms inject $PORT; default to 8000 for a plain `docker run`. Shell form so
# the variable is expanded at start rather than treated as a literal.
ENV PORT=8000
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
