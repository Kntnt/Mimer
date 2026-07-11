# Coding standard — Python

Read before writing or changing Python.

Applies whenever the project contains Python code.

### Baseline

- Standalone scripts: pin runtime via `requires-python` in PEP 723 inline metadata, provisioned by `uv`. Newest Python can lack wheels for some dependencies — don't force absolute latest at install time.
- Full type hints on every function signature and module-level declaration. Checked statically (see *Python tooling*).

### Style

- Idiomatic, modern Python. Prefer standard library where it suffices.
- `pathlib.Path` over `os.path`.
- `dataclasses` over hand-rolled `__init__`; `pydantic` only when validation is part of the contract.
- f-strings; never `%` or `.format()`.
- Context managers (`with`) for any resource with a close/release lifecycle.
- No bare `except:`. Name the exception, or `except Exception` with a comment explaining why a broad catch is appropriate.
- Early returns to flatten nesting.

### Doc comments

Docstrings on every module, class, and public function. Document the contract and the why; type hints show the shape. Pick a docstring convention (Google or NumPy style) per project, stay consistent. Use `Args:` / `Returns:` / `Raises:` where they add real value.

### Standalone-script metadata (PEP 723)

Single-file scripts: declare dependencies and required Python version inline at the top:

```python
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "httpx==0.27.0",
#     "rich==13.7.1",
# ]
# ///
```

Pin exact versions. `uv run` resolves and caches the environment automatically.

A script meant to run from the terminal uses the env-based shebang `#!/usr/bin/env -S uv run --script`, so `uv` provisions the environment from this PEP 723 metadata on invocation. Packaging shape (command-style in `bin/` vs internal) follows the universal *Standalone-script packaging* rules in the general module.

### Python tooling

- **uv** as runtime, package manager, and virtualenv tool. `uv run` executes a PEP 723 script directly; for project work, `uv` manages the project venv and lockfile.
- **ruff** as the single linter and formatter (replaces black, isort, flake8, pylint).
- **mypy** or **pyright** for static type checking — pick one per project. Strict mode on new code.
- **pytest** for tests.
