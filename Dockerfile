FROM node:22-alpine AS frontend

WORKDIR /src
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN npm ci
COPY webapp/frontend/ ./
RUN npm run build

FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
COPY webapp/backend/pyproject.toml webapp/backend/pyproject.toml
COPY webapp/backend/erw webapp/backend/erw

# CPU torch: the web process imports the scorer stack, and the CUDA wheel is unnecessary here.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        -e /app \
        -e /app/webapp/backend

COPY --from=frontend /src/dist /app/webapp/frontend/dist

WORKDIR /app/webapp/backend
EXPOSE 8000
CMD ["python", "-m", "erw.main"]
