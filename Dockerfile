# Образ с браузером: нужен только для входа через «Ростелеком Паспорт» (/auth/login).
# Если вход делается снаружи (scripts/login_helper.py -> /auth/import), можно собрать
# лёгкий вариант: docker build --build-arg WITH_BROWSER=0 -t rtk-vats-api:slim .
ARG WITH_BROWSER=1

FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- вариант без браузера (~200 МБ) ---
FROM base AS build-0

# --- вариант с браузером: Chromium + системные библиотеки ---
FROM base AS build-1
RUN playwright install --with-deps chromium

FROM build-${WITH_BROWSER} AS final

COPY app/ app/
COPY scripts/ scripts/
COPY pytest.ini .

ENV DATA_DIR=/app/data
EXPOSE 8010

CMD ["sh", "-c", "uvicorn app.main:app --host ${LISTEN_HOST:-0.0.0.0} --port ${LISTEN_PORT:-8010}"]
