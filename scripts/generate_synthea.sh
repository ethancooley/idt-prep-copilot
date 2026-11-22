#!/usr/bin/env bash
# Generates the base synthetic population with Synthea (https://github.com/synthetichealth/synthea).
# Everything it produces is fictional. Requires Java 17+.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JAR="$ROOT/vendor/synthea.jar"
OUT="$ROOT/data/synthea"
SEED="${SEED:-20261121}"
COUNT="${COUNT:-40}"

if [ ! -f "$JAR" ]; then
  mkdir -p "$ROOT/vendor"
  curl -sSL -o "$JAR" \
    https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar
fi

rm -rf "$OUT" && mkdir -p "$OUT"
java -jar "$JAR" \
  -p "$COUNT" -a 68-92 -s "$SEED" -cs "$SEED" \
  --exporter.baseDirectory="$OUT/" \
  --exporter.csv.export=true \
  --exporter.fhir.export=false \
  --exporter.hospital.fhir.export=false \
  --exporter.practitioner.fhir.export=false \
  --exporter.years_of_history=3 \
  --generate.only_alive_patients=true \
  California

echo "Synthea CSVs written to $OUT/csv"
