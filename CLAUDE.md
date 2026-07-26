# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an OmniFocus CLI written in Python that provides command-line task management for OmniFocus on macOS. The project uses a clean architecture with the Humble Object pattern for testability.

## Running Commands

The script uses UV for execution and dependency management. Run commands using:

```bash
# Direct execution (has uv script header)
./omnifocus.py <command>

# Via uv run
uv run omnifocus.py <command>

# Using installed CLI aliases
omnifocus <command>
todo <command>  # alias
```

## Development Commands

```bash
# Install dependencies and sync environment
uv sync

# Install globally (creates omnifocus and todo commands)
just global-install
# or: uv tool install --force --editable .

# Run tests
just test
# or: uv run pytest

# Run tests with coverage
just coverage
# or: uv run pytest tests/ --cov=omnifocus --cov-report=term-missing

# Lint code
just lint
# or: uv run ruff check .

# Format code
just format
# or: uv run ruff format . && uv run ruff check . --fix

# Clean cache files
just clean
```

## Architecture

### Core Design Patterns

1. **Humble Object Pattern**: `OSXSystem` class isolates all external dependencies (OmniFocus, macOS system calls) for testing
2. **Dependency Injection**: `OmniFocusManager` receives `OSXSystem` instance, making it fully testable
3. **Pydantic Models**: `Task` model provides type-safe data validation and serialization

### Three-Layer Architecture

```
CLI Layer (Typer commands)
    ↓
Business Logic Layer (OmniFocusManager)
    ↓
System Interface Layer (OSXSystem - Humble Object)
    ↓
External Systems (OmniFocus, macOS, Web)
```

### OmniFocus Integration Methods

The codebase uses two different approaches to interact with OmniFocus:

1. **JavaScript Automation (JXA)** - Used for the broad task listings

   - Via `OSXSystem.run_javascript()` which calls `osascript -l JavaScript`
   - Used by: `get_all_tasks()`, `get_flagged_tasks()`, `get_inbox_tasks()`
   - Returns JSON data parsed into Task models

2. **Omni Automation (OmniJS)** - Faster alternative for reading (10-100x faster)

   - Via `OSXSystem.run_omni_automation()` which runs scripts directly in OmniFocus context
   - Used by: `get_inbox_and_flagged_tasks_omni()` (backs `_get_interesting_tasks()`,
     and so every command that numbers tasks: `interesting`, `flagged`, `complete`,
     `flow`, `open-task`, `snooze`) and `get_incomplete_tasks()` (backs `fixup-url`)
   - Avoids Apple Events overhead by evaluating JavaScript in-process
   - When mocking these commands in tests, mock the OmniJS method the command
     actually calls — not `get_inbox_tasks()`/`get_flagged_tasks()`

3. **URL Schemes** - Primary method for writing/modifying data

   - Via `OSXSystem.open_url()` with `omnifocus:///add?` URLs
   - Used by: `add_task()` and all task modification operations
   - Parameters are URL-encoded and opened via macOS `open` command

4. **Hybrid Approach** - Complex operations (tag management, snooze)
   - Creates a new task with modified properties via URL scheme
   - Completes the original task to "replace" it
   - Workaround for operations not well-supported by URL schemes

### Key Data Flow

- **Task retrieval**: OmniFocus → JXA/OmniJS → JSON → Pydantic Task model
- **Task creation**: Task model → URL scheme parameters → OmniFocus
- **Task modification**: Read task → Create new task with changes → Complete old task

## Code Conventions

### Python Style

- Use Python 3.12+ features (modern type syntax: `str | None` instead of `Optional[str]`)
- Use Pydantic for data validation
- Use Typer with Annotated syntax for CLI arguments
- Use Rich for terminal output formatting
- Use `ic()` from icecream for debugging
- Prefer early returns over nested ifs
- Use descriptive variable names over comments

### Testing

- Tests are in `tests/unit/` directory
- Use pytest framework
- All tests use mocked `OSXSystem` - never interact with real OmniFocus
- Tests designed to run in parallel with pytest-xdist
- Follow AAA pattern (Arrange, Act, Assert)
- Use fixtures for test setup

### Type Annotations

- Always use type hints
- For complex return types, define Pydantic models named `FunctionNameReturn`
- Example: `get_user_profile() -> UserProfileResponse`

## Important Implementation Details

### Task Number Consistency

The "interesting" command shows inbox and flagged tasks with numbered indices. These numbers must remain stable across multiple operations to avoid user confusion. When implementing multi-task operations:

- Fetch all tasks upfront before any modifications
- Validate all task numbers before processing
- Store task references, not just numbers

### Tag Management Workaround

Direct JavaScript-based tag manipulation is unreliable. Instead:

- Create a new task with the desired tags using URL scheme
- Complete the original task
- This ensures all task properties (due date, defer date, project, etc.) are preserved

### LLM Integration

The `flow` command calls the Groq HTTP API directly to shorten task names:

- Requires `GROQ_API_KEY` in the environment, or in `~/gits/igor2/secretBox.json`
- Falls back to the original name on any failure (missing key, API error, truncated or empty response)
- Uses `openai/gpt-oss-120b` by default (configurable in `LLMTaskShortener`)
- GPT-OSS are reasoning models: the hidden reasoning trace shares the `max_tokens`
  budget with the answer, so the budget is 512 and `reasoning_effort` is `low`.
  That parameter is gated on the model — Groq rejects it with HTTP 400 on
  non-reasoning models, so `supports_reasoning_effort` decides whether to send it.
- Groq decommissions models periodically; a 404 means the default needs updating
  against https://console.groq.com/docs/deprecations

### Flow Session Integration

The `flow` command integrates with a separate flow tracking system via `y` CLI:

- Calls `y flow-go <session-name>` to start sessions
- Requires `y` command in PATH
- Properly escapes arguments with shell quoting

## Testing Strategy

All external dependencies are completely isolated:

- `OSXSystem` is mocked in all tests
- No actual OmniFocus calls during testing
- No network requests during testing
- Tests run in parallel for speed

When adding new features:

1. Add tests to `tests/unit/test_omnifocus.py`
2. Mock all `OSXSystem` methods used
3. Verify behavior with various inputs
4. Test error conditions

## Configuration Files

- `pyproject.toml`: Project metadata, dependencies, CLI entry points
- `justfile`: Development task automation
- `.github/workflows/test.yml`: CI/CD with automated test badge updates
- Script header in `omnifocus.py`: UV-compatible inline dependencies

## Common Gotchas

1. **URL Encoding**: Always use `urllib.parse.quote` when constructing omnifocus:// URLs
2. **JavaScript Escaping**: When embedding scripts in AppleScript strings, escape backslashes and quotes
3. **Task ID Format**: Task IDs from OmniFocus are opaque strings, never parse or modify them
4. **Date Formats**: Use ISO format for date interchange, `%Y-%m-%d` for URL schemes
5. **Tag Operations**: Never modify tags directly via JavaScript - always use the URL scheme workaround
6. **Terminal Commands**: For commands using pagers (git, less), append `| /bin/cat` to prevent breakage

## External Dependencies

- **OmniFocus**: macOS productivity app (required)
- **Groq API key**: Optional, for AI-powered task name shortening (`GROQ_API_KEY`)
- **Flow system (y command)**: Optional, for flow session tracking
- **UV**: Package manager for running and installing

## CLI Entry Points

The project defines two CLI entry points in `pyproject.toml`:

- `omnifocus`: Primary command
- `todo`: Alias for shorter typing
