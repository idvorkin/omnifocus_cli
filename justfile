# List all available commands
default:
    @just --list

# Run fast tests (called by pre-commit)
fast-test:
    @echo "0/0 tests passed - Add tests"

# Install in virtual environment
install:
    uv venv
    . .venv/bin/activate
    uv pip install --upgrade --editable .

# Install globally using uv tool
global-install: install
    uv tool install --force --editable  .

# Install development dependencies (for contributing)
install-dev:
    uv pip install -e ".[dev]"

# Run tests
test:
    pytest tests/ -v

# Run tests with coverage
coverage:
    pytest tests/ --cov=omnifocus --cov-report=term-missing

# Format code
format:
    ruff format .
    ruff check . --fix

# Run linting
lint:
    ruff check .
    mypy omnifocus/

# Clean python cache files
clean:
    find . -type d -name "__pycache__" -exec rm -r {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type f -name "*.pyd" -delete
