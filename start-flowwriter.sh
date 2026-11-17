#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi
exec .venv/bin/python -m flowwriter
