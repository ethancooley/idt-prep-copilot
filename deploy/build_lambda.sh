#!/usr/bin/env bash
# Builds the live-run Lambda package in build/lambda: Linux wheels for Python 3.13 plus the app.
# Works on a Mac without Docker because pip downloads prebuilt Linux wheels.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=build/lambda
rm -rf "$OUT"
mkdir -p "$OUT"
python -m pip install --quiet --upgrade \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.13 --only-binary=:all: \
  --target "$OUT" -r deploy/requirements-lambda.txt
cp -R src/idt_copilot "$OUT/"
cp deploy/run.sh "$OUT/run.sh"
chmod 755 "$OUT/run.sh"
find "$OUT" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -f "$OUT/.env"
echo "Built $OUT ($(du -sh "$OUT" | cut -f1))"
