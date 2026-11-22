#!/usr/bin/env bash
# Stores the three secrets in SSM Parameter Store as encrypted SecureStrings (free, standard tier).
# Values are typed at a hidden prompt, so they never land in your shell history or in git.
set -euo pipefail
PREFIX="${IDT_SSM_PREFIX:-/idt-copilot}"
REGION="${AWS_REGION:-us-east-1}"

put() {
  local name="$1" prompt="$2" value
  read -r -s -p "$prompt: " value; echo
  if [[ -z "$value" ]]; then echo "  skipped $name (empty)"; return; fi
  aws ssm put-parameter --region "$REGION" --name "$PREFIX/$name" --type SecureString \
    --value "$value" --overwrite >/dev/null
  echo "  saved $PREFIX/$name"
}

echo "Saving secrets under $PREFIX in $REGION. Leave a value empty to keep what is there."
put ANTHROPIC_API_KEY "Anthropic API key for the site (a separate key, not your dev key)"
put DATABASE_URL      "Neon connection string (postgresql://...?sslmode=require)"
put IDT_ACCESS_CODE   "Owner access code for live runs (long and random; for you)"
put IDT_ADMIN_TOKEN   "Admin password for the /admin console (long and random; never share it)"
echo "Done. The Lambda reads these at startup; redeploy or wait for a cold start to pick up changes."
