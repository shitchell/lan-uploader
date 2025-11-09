# Type Checking with mypy

This project uses [mypy](http://mypy-lang.org/) for static type checking to catch type-related bugs before runtime.

## Quick Start

### Installation

Install development dependencies including mypy:

```bash
pip install -r requirements-dev.txt
```

### Running mypy

Run mypy on all Python files:

```bash
mypy app.py models.py thumbnails.py
```

Or run on the entire project:

```bash
mypy .
```

## Configuration

Type checking is configured in `mypy.ini` with the following strict settings:

- Python version: 3.11+
- Strict optional checking enabled
- Disallow untyped function definitions
- Warn on redundant casts and unused ignores
- Check untyped definitions
- Show error codes and column numbers

### Third-party Library Stubs

Some third-party libraries don't have type stubs. These are configured in `mypy.ini` to ignore missing imports:

- `werkzeug.*`
- `uvicorn.*`

Type stubs are installed for:

- Pillow (`types-Pillow`)
- Werkzeug (`types-werkzeug`)

## Integration Options

### Pre-commit Hook

Add mypy to your pre-commit hooks to run before each commit:

1. Install the pre-commit framework:
   ```bash
   pip install pre-commit
   ```

2. Create `.pre-commit-config.yaml`:
   ```yaml
   repos:
     - repo: https://github.com/pre/mirrors-mypy
       rev: 'v1.7.0'
       hooks:
         - id: mypy
           additional_dependencies: [types-Pillow, types-werkzeug]
           args: [--config-file=mypy.ini]
   ```

3. Install the hooks:
   ```bash
   pre-commit install
   ```

### Git Hook (Manual)

Add mypy to your git hooks directly. Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
echo "Running mypy type checker..."
mypy app.py models.py thumbnails.py
if [ $? -ne 0 ]; then
    echo "Type checking failed. Commit aborted."
    exit 1
fi
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### CI/CD Integration

#### GitHub Actions

Add to `.github/workflows/tests.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements-dev.txt
      - name: Run mypy
        run: mypy app.py models.py thumbnails.py
```

#### GitLab CI

Add to `.gitlab-ci.yml`:

```yaml
type-check:
  image: python:3.11
  script:
    - pip install -r requirements-dev.txt
    - mypy app.py models.py thumbnails.py
```

## Type Hints Summary

All Python files now have complete type annotations:

### app.py
- All function signatures have return types
- Route handlers properly typed with FastAPI types
- Configuration functions typed with proper dictionaries
- Helper functions include all parameter and return types

### models.py
- SQLAlchemy models use typed `Mapped` columns
- All database methods have proper type signatures
- Optional parameters correctly marked with `Optional[T]`
- Callback types properly specified

### thumbnails.py
- Image processing functions fully typed
- Path handling with proper type annotations
- Optional return values correctly specified

## Common Type Checking Issues

### Fixing Type Errors

If you encounter type errors:

1. Read the error message carefully - mypy provides the file, line, and error code
2. Check the [mypy error codes documentation](https://mypy.readthedocs.io/en/stable/error_code_list.html)
3. Add proper type annotations to fix the issue
4. Use `# type: ignore[error-code]` ONLY as a last resort with a comment explaining why

### Example Type Annotations

```python
from typing import Optional, List, Dict, Any

def get_files(directory: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get files from directory."""
    files: List[Dict[str, Any]] = []
    # ... implementation
    return files
```

## Best Practices

1. Always add type hints to new functions
2. Use `Optional[T]` for nullable values (not `T = None`)
3. Use specific types from `typing` module: `List`, `Dict`, `Tuple`, `Set`
4. For complex return types, use `Union[A, B]` or `A | B` (Python 3.10+)
5. Run mypy before committing code
6. Don't use `Any` unless absolutely necessary
7. Add docstrings with type information in prose as well

## Resources

- [mypy documentation](https://mypy.readthedocs.io/)
- [Python typing module](https://docs.python.org/3/library/typing.html)
- [FastAPI type hints](https://fastapi.tiangolo.com/python-types/)
- [SQLAlchemy 2.0 type mapping](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html)
