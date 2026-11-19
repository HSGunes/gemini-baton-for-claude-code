# Contributing

Thank you for your interest in contributing to Gemini Baton!

## Setup and Checks

Python 3.10+ on Linux or macOS is required.

```bash
git clone https://github.com/HSGunes/gemini-baton-for-claude-code.git
cd gemini-baton-for-claude-code
python3 -m pytest
ruff check .
claude plugin validate --strict .
```

The test suite runs against a fake `agy` binary and never invokes the real CLI. CI runs `ruff check .`, `python -m pytest -q` (Linux and macOS, Python 3.10–3.13), packaging checks, and `claude plugin validate --strict .`.

## Guidelines

- **Standard library only:** `ajan.py` must have zero runtime dependencies (Python 3.10+ stdlib only). Do not add third-party runtime dependencies; `PIL` is only used in the showcase script under `scripts/`.
- **Test behavior changes:** Include tests for bug fixes and new or changed behavior. Do not weaken existing tests.
- **Language:** The default CLI language (primary subcommands and messages) is Turkish, with `AJAN_DIL=en` and English subcommand aliases supported. Issues, pull requests, and contributions in English are welcome.
- **Small, focused changes:** Keep commits and pull requests small and focused on one change at a time.
