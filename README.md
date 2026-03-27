# SafeLint

SafeLint is a configurable static analysis tool that enforces safety-critical coding practices inspired by Gerard J. Holzmann’s "Power of Ten" rules at NASA/JPL. These principles are especially relevant in the era of AI-generated code — where correctness, bounded behavior, and explicit error handling are often overlooked. SafeLint integrates with pre-commit and CI pipelines to catch unsafe patterns before they enter your codebase.

## Why SafeLint?

AI tools generate code that looks correct — but often violates fundamental safety principles:

- Unbounded loops
- Silent error handling
- Hidden side effects
- Poor resource management

SafeLint ensures these issues are caught early, automatically.

## Philosophy

> “When it really counts, it may be worth going the extra mile and living within stricter limits than may be desirable.”
> — Gerard J. Holzmann, NASA/JPL

## What it does
SafeLint provides a small AST-based lint engine for Python projects with rules focused on code that tends to become fragile under rapid iteration:

- oversized functions
- excessive nesting depth
- weak exception handling
- module-level side effects
- unsafe resource lifecycle patterns

## Quick start
```bash
python -m pip install -e .
safelint check src
```

To use a project config:

```bash
safelint check src --config examples/.ai-safety.yaml
```

## Configuration
The configuration file is YAML or JSON. Example:

```yaml
max_function_lines: 40
max_nesting_depth: 3
allow_top_level_side_effects: false
enabled_rules:
	- function-length
	- nesting-depth
	- error-handling
	- side-effects
	- resource-lifecycle
```

## Rule set
- `function-length`: flags functions whose source span exceeds the configured limit
- `nesting-depth`: flags deeply nested control flow in functions
- `error-handling`: flags bare `except:` and `except ...: pass`
- `side-effects`: flags executable statements at module import time
- `resource-lifecycle`: flags `open()` calls that are not wrapped in a `with`

## Development
```bash
pytest
```
