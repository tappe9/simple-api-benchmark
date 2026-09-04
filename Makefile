COMPOSE ?= docker compose
PYTHON ?= python3

DB_SERVICE := postgres
DB_NAME := benchmark
DB_USER := benchmark
DB_WAIT_TIMEOUT ?= 60
PSQL := $(COMPOSE) exec -T $(DB_SERVICE) psql -X --username $(DB_USER) --dbname $(DB_NAME) --set ON_ERROR_STOP=1 --tuples-only --no-align

.PHONY: db-up db-check db-reset test-db test-go-gin test-node-fastify down

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
	@$(PYTHON) tests/test_node_fastify_service.py

down:
	@echo "Removing benchmark containers and project network..."
	@$(COMPOSE) down --remove-orphans --volumes
