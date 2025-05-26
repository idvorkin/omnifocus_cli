# List all available commands
default:
    @just --list

# Run fast tests (called by pre-commit)
fast-test:
    uv run pytest tests/ -v

# Install globally using uv tool
global-install:
    uv tool install --force --editable  .

# Run tests
test:
    uv run pytest tests/ -v

# Run tests with coverage
coverage:
    uv run pytest tests/ --cov=omnifocus --cov-report=term-missing

# Format code
format:
    uv run ruff format .
    uv run ruff check . --fix

# Run linting
lint:
    uv run ruff check .

# Clean python cache files
clean:
    find . -type d -name "__pycache__" -exec rm -r {} +
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type f -name "*.pyd" -delete
