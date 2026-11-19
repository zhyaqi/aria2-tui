#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec uv run --project "$PROJECT_DIR" aria2-tui "$@"
