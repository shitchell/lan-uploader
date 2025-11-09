.PHONY: test test-verbose test-integration test-cov clean install-dev help

help:
	@echo "LAN Uploader - Development Commands"
	@echo "===================================="
	@echo "make install-dev    Install development dependencies"
	@echo "make test           Run all tests"
	@echo "make test-verbose   Run tests with verbose output"
	@echo "make test-integration  Run only integration tests"
	@echo "make test-cov       Run tests with coverage report"
	@echo "make clean          Clean up temporary files"

install-dev:
	pip install -r requirements-dev.txt

test:
	python -m pytest tests/

test-verbose:
	python -m pytest tests/ -v

test-integration:
	python -m pytest tests/test_integration.py -v

test-cov:
	python -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html

clean:
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
