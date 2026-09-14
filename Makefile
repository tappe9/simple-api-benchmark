.DEFAULT_GOAL := help
PYTHON ?= python3

.PHONY: help up down logs ps test test-implementations test-contract test-benchmark test-workflows test-site generate-readme benchmark benchmark-smoke benchmark-official benchmark-publish benchmark-healthcheck-investigation axum-diagnostic

help:
	@echo "Targets:"
	@echo "  up             Start all services"
	@echo "  down           Stop all services and remove volumes"
	@echo "  logs           Follow service logs"
	@echo "  ps             Show Compose services"
	@echo "  test           Run all local quality gates"
	@echo "  test-implementations Run implementation-specific acceptance/failure tests"
	@echo "  test-contract  Run the shared API contract suite"
	@echo "  test-benchmark Run benchmark unit/integration tests"
	@echo "  test-workflows Run workflow syntax and policy tests"
	@echo "  test-site      Run Pages/static-site tests"
	@echo "  generate-readme Regenerate README benchmark sections"
	@echo "  benchmark      Run local benchmark"
	@echo "  benchmark-smoke Run short non-publishing benchmark smoke"
	@echo "  benchmark-official Run the trusted official benchmark wrapper"
	@echo "  benchmark-publish Publish an audited official result"
	@echo "  benchmark-healthcheck-investigation Run non-publishing healthcheck diagnostic"
	@echo "  axum-diagnostic Run the non-publishing Axum load diagnostic"

up:
	docker compose up --build -d

down:
	docker compose down --remove-orphans --volumes

logs:
	docker compose logs -f

ps:
	docker compose ps

test-go-gin:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_go_gin_service.py

test-go-echo:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_go_echo_service.py

test-rust-actix:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_rust_actix_service.py

test-rust-axum:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_rust_axum_service.py
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_rust_axum_acceptance.py

test-node-fastify:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_node_fastify_service.py

test-node-express:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_node_express_service.py

test-python-fastapi:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_python_fastapi_service.py

test-python-flask:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) tests/test_python_flask_service.py

test-implementations:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.ci implementations

test-contract:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_contract_*.py' -v

test-benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_benchmark_*.py' -v

test:
	@$(MAKE) --no-print-directory test-implementations
	@$(MAKE) --no-print-directory test-contract
	@$(MAKE) --no-print-directory test-benchmark
	@$(MAKE) --no-print-directory test-workflows
	@$(MAKE) --no-print-directory test-site
	@$(MAKE) --no-print-directory benchmark-smoke
	@$(MAKE) --no-print-directory axum-diagnostic

test-workflows:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_workflows*.py' -v
	@actionlint

test-site:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_site.py' -v
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_history_site.py' -v
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -p 'test_pages.py' -v
	@node --test tests/test_site.mjs tests/test_dashboard.mjs tests/test_dashboard_browser.mjs

generate-readme:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.generate_readme

benchmark:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run

benchmark-smoke:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.run --smoke

benchmark-official:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.official

benchmark-publish:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.publish

benchmark-healthcheck-investigation:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.healthcheck_investigation

axum-diagnostic:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m benchmark.axum_diagnostic
