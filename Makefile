# Makefile

.PHONY: all format check validate integration-test integration-test-smoke

# Default target: runs format and check
all: validate

# Format the code using ruff
format:
	ruff format --check --diff .

reformat-ruff:
	ruff format .

# Check the code using ruff
check:
	ruff check .

fix-ruff:
	ruff check . --fix

fix: reformat-ruff fix-ruff
	@echo "Updated code."

complexity:
	radon cc . -a -nc

xenon:
	xenon -b D -m B -a B .

bandit:
	bandit -c pyproject.toml -r .

vulture:
	vulture src/ .vulture-whitelist.py

pyright:
	pyright

test:
	pytest tests/unit -v --cov --cov-report=xml --cov-report=term-missing

# Run integration tests locally (requires Docker)
integration-test:
	pytest tests/integration -v --tb=short

# Run single smoke test for faster feedback
integration-test-smoke:
	pytest tests/integration/test_signal_cli_integration.py::TestSignalCliIntegration::test_signal_cli_version_via_dbus -v --tb=short

# Validate the code (format + check)
validate: format check complexity bandit vulture pyright
	@echo "Validation passed. Your code is ready to push."

# Docker build targets
docker-build:
	docker build -t swb:local .

docker-build-no-cache:
	docker build --no-cache -t swb:local .

docker-run:
	docker run -p 8765:8765 -e SIGNAL_LOG_LEVEL=DEBUG swb:local

docker-compose-up:
	docker compose up --build

docker-compose-down:
	docker compose down

docker-test: docker-build
	@echo "Testing Docker image..."
	@docker run --rm swb:local /app/.venv/bin/python -c "import swb; print('Package imported successfully')"
	@echo "Docker image test passed!"