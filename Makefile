# Shortcuts for the commands in docs/DEPLOY.md and the CI workflow. `make help` lists them.

.PHONY: help secrets up down reset logs ps build migrate test lint format web-check

help:  ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

secrets:  ## Create .env and fill in missing generated secrets (prints names only)
	python3 scripts/gen_secrets.py

up: secrets  ## Build and start the whole stack
	docker compose up -d --build

down:  ## Stop the stack, keep the data
	docker compose down

reset:  ## Stop the stack and DELETE all data (database, traces)
	docker compose down -v

logs:  ## Follow the logs of the Lighthouse services
	docker compose logs -f api worker migrate

ps:  ## Show the state and health of every container
	docker compose ps -a

build:  ## Rebuild the backend and web images
	docker compose build

migrate:  ## Apply new SQL migrations to the running database
	docker compose run --rm migrate

test:  ## Run the backend tests (needs the test database, see tests/conftest.py)
	uv run pytest

lint:  ## Run the checks CI runs for the backend
	uv run ruff check
	uv run ruff format --check
	uv run basedpyright

format:  ## Format the Python code
	uv run ruff format

web-check:  ## Run the checks CI runs for the web app
	cd web && pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test && pnpm build
