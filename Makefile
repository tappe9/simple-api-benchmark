COMPOSE ?= docker compose
PYTHON ?= python3
CONTRACT_IMPL ?= all

DB_SERVICE := postgres
DB_NAME := benchmark
DB_USER := benchmark
DB_WAIT_TIMEOUT ?= 60
PSQL := $(COMPOSE) exec -T $(DB_SERVICE) psql -X --username $(DB_USER) --dbname $(DB_NAME) --set ON_ERROR_STOP=1 --tuples-only --no-align

.PHONY: db-up db-check db-reset test-db test-go-gin test-node-fastify test-python-fastapi test-rust-actix test-contract down

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

test-go-gin:
	@$(PYTHON) tests/test_go_gin_service.py

test-node-fastify:
	@$(PYTHON) -m unittest discover -s tests -p test_node_fastify_acceptance.py
	@$(PYTHON) tests/test_node_fastify_service.py

test-python-fastapi:
	@$(PYTHON) -m unittest discover -s tests -p test_python_fastapi_acceptance.py
	@$(PYTHON) tests/test_python_fastapi_service.py

test-rust-actix:
	@$(PYTHON) -m unittest discover -s tests -p test_rust_actix_acceptance.py
	@$(PYTHON) tests/test_rust_actix_service.py

test-contract:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_contract_*.py'
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.contract_runner --implementation "$(CONTRACT_IMPL)" --compose "$(COMPOSE)"

down:
	@echo "Removing benchmark containers and project network..."
	@$(COMPOSE) down --remove-orphans --volumes

.PHONY: benchmark test-benchmark benchmark-smoke install-oha

install-oha:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --install-only

test-benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_benchmark_*.py' -v

benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --compose "$(COMPOSE)"

benchmark-smoke:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --compose "$(COMPOSE)" --smoke

.PHONY: test test-workflows test-site generate-readme

# Recursive invocations deliberately serialize services sharing loopback port 8080.
test:
	@$(MAKE) --no-print-directory test-db
	@$(MAKE) --no-print-directory test-go-gin
	@$(MAKE) --no-print-directory test-rust-actix
	@$(MAKE) --no-print-directory test-node-fastify
	@$(MAKE) --no-print-directory test-python-fastapi
	@$(MAKE) --no-print-directory test-contract
	@$(MAKE) --no-print-directory test-benchmark
	@$(MAKE) --no-print-directory test-workflows
	@$(MAKE) --no-print-directory test-site
	@$(MAKE) --no-print-directory benchmark-smoke

test-workflows:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p test_workflows.py -v
	@actionlint

test-site:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_site.py' -v
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_pages.py' -v
	@node --test tests/test_site.mjs

generate-readme:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.generate_readme
