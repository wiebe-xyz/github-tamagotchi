.PHONY: test lint typecheck build clean

test:
	pytest --cov=src --cov-report=term-missing --cov-fail-under=70

test-unit:
	pytest tests/unit -v

test-services:
	pytest tests/services -v

test-api:
	pytest tests/api -v

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy src/

build:
	docker build -t github-tamagotchi .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov coverage.xml
