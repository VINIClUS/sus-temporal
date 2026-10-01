#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export HYPOTHESIS_PROFILE="${HYPOTHESIS_PROFILE:-ci}"

uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked python -m scripts.check_ownership
uv run --locked pytest -q "$@"
