.PHONY: install dev run create-db migrate migrate-down migrate-new test test-cov lint format typecheck check seed promote-admin demote-admin cleanup-otps precommit clean

install:
	uv sync --all-groups
	uv run pre-commit install

dev:
	uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

run:
	uv run python -m src.app

create-db:
	uv run python -m scripts.create_db

migrate:
	uv run alembic upgrade head

migrate-down:
	uv run alembic downgrade -1

migrate-new:
	uv run alembic revision --autogenerate -m "$(name)"

test:
	uv run pytest -q

test-cov:
	uv run pytest -q --cov --cov-report=term-missing

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

check: lint typecheck test-cov

seed:
	uv run python -m scripts.seed

promote-admin:
	uv run python -m scripts.seed --promote-admin $(EMAIL)

demote-admin:
	uv run python -m scripts.seed --demote-admin $(EMAIL)

cleanup-otps:
	uv run python -m scripts.cleanup_otps

precommit:
	uv run pre-commit run --all-files

clean:
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
