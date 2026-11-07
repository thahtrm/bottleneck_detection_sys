# ==============================================================================
# Early Risk Web (ERW) — Makefile
# ==============================================================================

SHELL := /bin/bash
ROOT_DIR := $(shell pwd)
PYTHON := $(ROOT_DIR)/.venv/bin/python
UVICORN := $(ROOT_DIR)/.venv/bin/uvicorn
RUFF := $(ROOT_DIR)/.venv/bin/ruff
NPM := npm

BACKEND_DIR := $(ROOT_DIR)/webapp/backend
FRONTEND_DIR := $(ROOT_DIR)/webapp/frontend
FRONTEND_DIST := $(FRONTEND_DIR)/dist

.PHONY: help run run-dev dev-frontend build-frontend seed-demo reset-demo sim-eval test lint clean

help:
	@echo "=============================================================================="
	@echo "                    EARLY RISK WEB (ERW) — MAKE COMMANDS"
	@echo "=============================================================================="
	@echo "  make run             Khởi chạy ứng dụng Web (FastAPI + Frontend UI) tại 0.0.0.0:8000"
	@echo "  make run-dev         Khởi chạy backend FastAPI với auto-reload (0.0.0.0:8000)"
	@echo "  make dev-frontend    Khởi chạy Vite dev server cho frontend (port 5173)"
	@echo "  make build-frontend  Build production static files cho frontend React + Mantine"
	@echo "  make seed-demo       Nạp dữ liệu kịch bản Demo trực quan (admin, PM, 5 kịch bản task)"
	@echo "  make reset-demo      Xóa sạch và nạp lại dữ liệu kịch bản Demo mới hoàn toàn"
	@echo "  make sim-eval        Chạy đánh giá mô phỏng lịch sử trên DuckDB (mẫu ZOOKEEPER)"
	@echo "  make test            Chạy toàn bộ 308 backend tests qua pytest"
	@echo "  make lint            Kiểm tra cú pháp & code style qua ruff"
	@echo "  make clean           Dọn dẹp các cache files (.pytest_cache, __pycache__)"
	@echo "=============================================================================="

# Build frontend if dist folder does not exist
$(FRONTEND_DIST)/index.html:
	@echo "==> Building frontend static assets..."
	@cd $(FRONTEND_DIR) && $(NPM) install --silent && $(NPM) run build

build-frontend:
	@echo "==> Building frontend static assets..."
	@cd $(FRONTEND_DIR) && $(NPM) install && $(NPM) run build

# Run application in production/standalone mode (Single Process: API + Static UI)
run: $(FRONTEND_DIST)/index.html
	@echo "==> Starting Early Risk Web on http://0.0.0.0:8000 (Ctrl+C to stop)..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m erw.main

# Run backend in development mode with hot-reload
run-dev:
	@echo "==> Starting FastAPI backend in reload mode on http://0.0.0.0:8000..."
	@cd $(BACKEND_DIR) && $(UVICORN) erw.main:create_app --factory --host 0.0.0.0 --port 8000 --reload

# Run frontend in development mode with Vite HMR
dev-frontend:
	@echo "==> Starting Vite frontend dev server..."
	@cd $(FRONTEND_DIR) && $(NPM) run dev

# Seed demo scenarios & users into SQLite database
seed-demo:
	@echo "==> Seeding presentation demo data..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m erw.cli seed-demo

reset-demo:
	@echo "==> Wiping and re-seeding presentation demo data..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m erw.cli seed-demo --reset

# Register webhook with Jira Cloud
register-webhook:
	@echo "==> Registering Jira Webhook with Jira Cloud..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m erw.cli register-webhook

# Run historical simulation evaluation (SRS FR-V1)
sim-eval:
	@echo "==> Running historical simulation evaluation on DuckDB..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m erw.cli sim-eval \
		--instance Apache \
		--project ZOOKEEPER \
		--from 2021-03-01 \
		--to 2021-03-15 \
		--step-days 2 \
		--output $(ROOT_DIR)/reports/sim-apache-zookeeper.md

# Run backend test suite
test:
	@echo "==> Running backend test suite..."
	@cd $(BACKEND_DIR) && $(PYTHON) -m pytest -q

# Run code linter
lint:
	@echo "==> Running ruff code quality check..."
	@$(RUFF) check $(BACKEND_DIR)

# Clean cache
clean:
	@echo "==> Cleaning cache artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
