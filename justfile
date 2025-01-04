# List all available commands
default:
    @just --list

# Install globally using pipxu
install:
    pipxu install -e -f .

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
