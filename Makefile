COMPOSE ?= docker compose
PYTHON ?= python3
CONTRACT_IMPL ?= all

DB_SERVICE := postgres
DB_NAME := benchmark
DB_USER := benchmark
DB_WAIT_TIMEOUT ?= 60
PSQL := $(COMPOSE) exec -T $(DB_SERVICE) psql -X --username $(DB_USER) --dbname $(DB_NAME) --set ON_ERROR_STOP=1 --tuples-only --no-align

.PHONY: db-up db-check db-reset test-db test-implementations test-registry test-compose test-contract down

db-up:
	@echo "Starting PostgreSQL $(DB_SERVICE) service..."
	@status=0; \
	$(COMPOSE) up --detach --wait --wait-timeout $(DB_WAIT_TIMEOUT) $(DB_SERVICE) || status=$$?; \
	if [ "$$status" -eq 0 ]; then \
		$(MAKE) --no-print-directory db-check || status=$$?; \
	fi; \
	if [ "$$status" -ne 0 ]; then \
		echo >&2 "PostgreSQL startup or fixture validation failed (exit $$status)."; \
		$(COMPOSE) ps >&2 || true; \
		$(COMPOSE) logs --no-color $(DB_SERVICE) >&2 || true; \
		$(COMPOSE) down --remove-orphans --volumes >/dev/null 2>&1 || true; \
		exit "$$status"; \
	fi
	@echo "PostgreSQL is healthy and the benchmark fixture is ready."

db-check:
	@set -eu; \
	row="$$( $(PSQL) --field-separator='|' --command "SELECT id, name, price FROM items WHERE id = 42;" )"; \
	if [ "$$row" != "42|Item 42|4200" ]; then \
		echo >&2 "Unexpected fixture row: '$$row'"; \
		exit 1; \
	fi; \
	count="$$( $(PSQL) --command "SELECT COUNT(*) FROM items;" )"; \
	if [ "$$count" != "1" ]; then \
		echo >&2 "Unexpected items row count: '$$count'"; \
		exit 1; \
	fi; \
	echo "Verified items fixture: 42|Item 42|4200 (row count: 1)."

db-reset:
	@echo "Resetting the benchmark database from database/init.sql..."
	@$(MAKE) --no-print-directory down
	@$(MAKE) --no-print-directory db-up

test-db:
	@$(PYTHON) tests/test_database_environment.py

include benchmark/implementations.mk

# Keep even `make -j test-implementations` sequential on shared host port 8080.
test-implementations: test-registry
	@set -eu; for target in $(IMPLEMENTATION_TARGETS); do \
		$(MAKE) --no-print-directory "$$target"; \
	done

test-registry:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.registry --check

test-compose:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_compose_parity.py' -v

test-contract:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_contract_*.py'
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.contract_runner --implementation "$(CONTRACT_IMPL)" --compose "$(COMPOSE)"

down:
	@echo "Removing benchmark containers and project network..."
	@$(COMPOSE) down --remove-orphans --volumes

.PHONY: benchmark test-benchmark benchmark-smoke healthcheck-investigation axum-diagnostic install-oha

install-oha:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --install-only

test-benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_benchmark_*.py' -v

benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --compose "$(COMPOSE)"

benchmark-smoke:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --compose "$(COMPOSE)" --smoke

axum-diagnostic:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.axum_diagnostic --compose "$(COMPOSE)"

healthcheck-investigation:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.healthcheck_investigation

.PHONY: test test-workflows test-site generate-readme

# Recursive invocations deliberately serialize services sharing loopback port 8080.
test:
	@$(MAKE) --no-print-directory test-registry
	@$(MAKE) --no-print-directory test-compose
	@$(MAKE) --no-print-directory test-db
	@$(MAKE) --no-print-directory test-implementations
	@$(MAKE) --no-print-directory test-contract
	@$(MAKE) --no-print-directory test-benchmark
	@$(MAKE) --no-print-directory test-workflows
	@$(MAKE) --no-print-directory test-site
	@$(MAKE) --no-print-directory benchmark-smoke
	@$(MAKE) --no-print-directory axum-diagnostic

test-workflows:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p test_workflows.py -v
	@actionlint

test-site:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_site.py' -v
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_pages.py' -v
	@node --test tests/test_site.mjs tests/test_dashboard.mjs

generate-readme:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.generate_readme
