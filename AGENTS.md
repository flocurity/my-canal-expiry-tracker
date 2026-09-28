# AGENTS.md

## Project

myCANAL Expiry Tracker is a small personal Python tool that analyzes manually exported myCANAL playlist data, retrieves public content-detail information, and generates an Excel file showing content expiration dates.

Read `SPEC.md` before making architectural or behavioral changes.

Keep the project pragmatic and relatively small. Do not over-engineer it.

## Python environment and dependencies

Use `uv` for Python environment and dependency management.

- Use `pyproject.toml` as the source of truth for project dependencies.
- Use `uv.lock` for reproducible dependency resolution and commit it to Git.
- Use `uv add <package>` to add runtime dependencies.
- Use `uv add --dev <package>` to add development/test dependencies.
- Use `uv remove <package>` to remove dependencies.
- Use `uv sync` to synchronize the development environment.
- Run Python commands through `uv run`.
- Run tests with `uv run pytest`.
- Do not create or maintain `requirements.txt` unless explicitly requested.
- Do not use `pip install` directly for project dependencies.
- Do not manually modify the `.venv` environment.
- If the project has not yet been initialized for uv, initialize/configure it using `pyproject.toml` before adding dependencies.
- Before coding, synchronize the environment with `uv sync` and run the existing test suite to establish a clean baseline.
- If dependency updates are explicitly requested, update them first and run the complete test suite before modifying application code.
- Do not upgrade dependencies opportunistically as part of an unrelated task.

## Development

- Use Python.
- Keep playlist parsing, API access, expiration-date extraction, caching, and Excel generation reasonably separated.
- Keep network behavior explicit and conservative.
- Do not introduce unnecessary concurrency or asynchronous code.
- Run the complete non-integration test suite after changes.

## Code quality

- Use type hints for public APIs.
- Prefer dataclasses when they genuinely clarify domain data.
- Do not introduce dataclasses or abstractions merely for architectural symmetry.
- Do not introduce abstractions unless justified by the current requirements in `SPEC.md`.
- Handle missing or unexpected API fields gracefully where required by `SPEC.md`.
- Follow PEP 8 for Python code style and naming conventions unless an existing project convention intentionally differs.
- Follow PEP 257 conventions for docstrings where docstrings are useful; do not add redundant docstrings to self-explanatory code.

## Testing

Use pytest.

Normal tests must not make real network requests.

- Unit tests and HTTP-client behavior tests must use mocks.
- Mock sleeps/backoff where appropriate so tests remain fast and deterministic.
- Real API tests must be explicitly marked with `pytest.mark.integration`.
- Integration tests must not run as part of the default `uv run pytest` command.
- Keep real API integration tests few in number and limited to representative content types defined in `SPEC.md`.
- Do not deliberately trigger API rate limiting from automated tests.
- Tests should validate behavior rather than unnecessary implementation details.
- When fixing a bug, add a regression test before or alongside the fix.
- Do not modify or weaken an existing test merely to make the implementation pass.
- Run the complete normal test suite with `uv run pytest` before considering a task complete.
- Run integration tests only when explicitly requested or when the task specifically requires validating behavior against the real API.

## Git and generated files

- Do not commit or modify files outside the repository.
- Do not commit `.venv`, caches, generated Excel output, coverage output, IDE metadata, or other generated artifacts unless explicitly required.
- Keep `.gitignore` appropriate for a Python/uv project.
- Do not create Git commits unless explicitly requested.

## Scope discipline

- Implement only behavior required by `SPEC.md` or explicitly requested by the user.
- Do not automate retrieval of the authenticated playlist unless explicitly requested.
- Do not attempt to bypass authentication, authorization, or API rate limiting.
- Do not add dependencies when the Python standard library is sufficient, except for dependencies explicitly required by the project or `SPEC.md`.
- If `SPEC.md` is ambiguous in a way that materially affects the architecture or external API behavior, stop and ask rather than silently choosing a major interpretation.
- Small implementation details may be decided autonomously when they do not materially affect the public behavior or architecture.

## Logging

Reuse the provided `log.py` logging implementation instead of creating a new logging system.

Use the project logging infrastructure for runtime diagnostics.

- Obtain loggers with `get_logger(...)` from the project's `log.py`.
- Do not add new `print()` calls for diagnostics, debugging, API progress, cache activity, parsing, retries, or errors.
- Prefer structured logging over formatted strings.

Preferred:

```python
log.info(
    "content_processed",
    index=index,
    total=total,
    title=title,
    expiration=expiration,
)
```

Avoid:

```python
print(f"[{index}/{total}] {title}: {expiration}")
```

Use appropriate log levels:

- `debug`: API details, cache behavior, parsing details, internal diagnostics
- `info`: meaningful application progress and final summaries
- `warning`: unexpected but recoverable situations, retries, or missing information
- `error`: failures affecting an individual content item or requested operation
- `exception`: unexpected exceptions when the traceback is useful

Pass data as structured fields instead of interpolating it into the event name.

Preferred:

```python
log.warning(
    "api_retry",
    content_id=content_id,
    status_code=status_code,
    attempt=attempt,
    delay=delay,
)
```

Avoid:

```python
log.warning(
    f"Retrying {content_id} after HTTP {status_code}, attempt {attempt}"
)
```

Multiline structured values are supported by the project's logging renderer. Pass them as normal structured fields when needed.

`print()` is allowed only when stdout is intentionally part of a user-facing CLI interface. It must not be used as a substitute for logging.

Do not change the logging infrastructure, `MultilineConsoleRenderer`, or console output formatting unless the task explicitly requires a logging change.

Do not duplicate logging-formatting logic elsewhere in the project. Keep application code unaware of console alignment, ANSI colors, multiline indentation, or other presentation details handled by the logging infrastructure.

Tests must not depend on cosmetic console log formatting unless they are specifically testing the logging renderer.

When adding new runtime diagnostics, follow the existing event naming and structured-field conventions used by the project.