#!/usr/bin/env sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required. Install it from https://docs.astral.sh/uv/"
    exit 1
fi

echo "Synchronizing the locked MDL environment..."
uv sync --locked --project "$project_dir"

printf "Install the Playwright Chromium browser? [Y/n]: "
read -r answer
case "$answer" in
    n|N|no|NO) ;;
    *) uv run --project "$project_dir" playwright install chromium ;;
esac

echo "MDL is ready. Run: uv run --project \"$project_dir\" python main.py --help"
