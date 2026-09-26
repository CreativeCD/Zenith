# Makefile — Zenith Autonomous AI Coding Harness
# Hackathon 2026

PYTHON ?= python3
VENV ?= .venv
BIN ?= $(VENV)/bin
REPO_PATH ?= .
ISSUE_PATH ?= issue.txt
MODEL ?= gemini-2.5-flash
MAX_STEPS ?= 25

.PHONY: help setup run test clean lint docker-test

help:
	@echo "Zenith AI Coding Harness Makefile"
	@echo "Targets:"
	@echo "  setup        - Create virtual environment and install dependencies"
	@echo "  run          - Execute harness with REPO_PATH and ISSUE_PATH"
	@echo "  test         - Run unit & integration test suite"
	@echo "  lint         - Run ruff linter on source code"
	@echo "  docker-test  - Build and verify inside Docker container"
	@echo "  clean        - Remove virtualenv, caches, and test artifacts"

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt

run:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Virtual environment not found. Running setup..."; \
		$(MAKE) setup; \
	fi
	$(BIN)/python -m harness.cli \
		--repo "$(REPO_PATH)" \
		--issue "$(ISSUE_PATH)" \
		--model "$(MODEL)" \
		--max-steps $(MAX_STEPS)

test:
	@if [ -d "$(VENV)" ]; then \
		$(BIN)/pytest -v tests/ --cov=harness --cov-report=term-missing; \
	else \
		pytest -v tests/ --cov=harness --cov-report=term-missing; \
	fi

lint:
	@if [ -d "$(VENV)" ]; then \
		$(BIN)/ruff check harness/ tests/; \
	else \
		ruff check harness/ tests/; \
	fi

docker-test:
	docker build -t zenith-harness:latest .
	docker run --rm zenith-harness:latest pytest -v tests/

clean:
	rm -rf $(VENV)
	rm -rf .harness
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
