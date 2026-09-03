# syntax=docker/dockerfile:1
# Multi-stage: base (runtime deps) → dev (tooling, hot reload) / prod (gunicorn, non-root).
# Dependencies are read from pyproject.toml so there is a single source of truth.

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libjpeg62-turbo libopenjp2-7 \
       fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && python -c "import tomllib;print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
    && pip install -r /tmp/req.txt

FROM base AS dev
RUN python -c "import tomllib;print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['optional-dependencies']['dev']))" > /tmp/req-dev.txt \
    && pip install -r /tmp/req-dev.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS prod
RUN useradd --create-home --uid 1000 app
COPY --chown=app:app . .
RUN mkdir -p /app/media /app/staticfiles && chown -R app:app /app/media /app/staticfiles \
    && DJANGO_ENV=prod DJANGO_SECRET_KEY=build DATABASE_URL=postgres://x:x@db/x \
       python manage.py collectstatic --noinput
USER app
EXPOSE 8000
CMD ["gunicorn", "termolink.wsgi", "--workers", "4", "--bind", "0.0.0.0:8000", "--timeout", "30"]
