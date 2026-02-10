.PHONY: help install install-dev lint format type-check test test-cov check db web frontend dev clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	uv pip install -e .

install-dev: ## Install all dependencies (prod + dev)
	uv pip install -e ".[dev]"

lint: ## Run ruff linter
	ruff check .

format: ## Run ruff formatter
	ruff format .

type-check: ## Run mypy strict type checking
	mypy config.py main.py database/ services/ api/ webhook_server.py

test: ## Run tests
	pytest

test-cov: ## Run tests with coverage report
	pytest --cov=. --cov-report=term-missing

check: lint type-check test ## Run all checks (lint + type-check + test)

db: ## Initialize the database
	python main.py init-db

web: ## Start Flask API server
	python main.py web

frontend: ## Start Vite dev server
	cd frontend && npm run dev

dev: ## Start both Flask and Vite (requires two terminals)
	@echo "Run in separate terminals:"
	@echo "  Terminal 1: make web"
	@echo "  Terminal 2: make frontend"

clean: ## Remove build artifacts and caches
	rm -rf __pycache__ .mypy_cache .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
