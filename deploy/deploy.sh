#!/usr/bin/env bash
# Deploys everything: the Lambda + Function URL, the S3 + CloudFront site, and the budget alert.
#
#   ALERT_EMAIL=you@example.com ./deploy/deploy.sh
#
# Needs: AWS CLI v2 (signed in), AWS SAM CLI, Node.js, and the secrets from put_secrets.sh.
# Optional custom domain (see deploy/README.md):
#   CUSTOM_DOMAIN=idt.example.com CERT_ARN=arn:aws:acm:us-east-1:... ALERT_EMAIL=... ./deploy/deploy.sh
# Run it again any time; it only changes what changed.
set -euo pipefail
cd "$(dirname "$0")/.."

# Settings you'd otherwise retype every deploy (ALERT_EMAIL, CUSTOM_DOMAIN, CERT_ARN) can live in
# deploy/config.env, which git ignores. Copy deploy/config.env.example to start.
if [[ -f deploy/config.env ]]; then
  # shellcheck disable=SC1091
  source deploy/config.env
fi

STACK="${STACK:-idt-copilot}"
REGION="${AWS_REGION:-us-east-1}"
: "${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should get the budget alert}"

echo "==> Building the Lambda package"
./deploy/build_lambda.sh

echo "==> Deploying stack $STACK to $REGION"
sam deploy \
  --template-file deploy/template.yaml \
  --stack-name "$STACK" \
  --region "$REGION" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-fail-on-empty-changeset \
  --parameter-overrides "AlertEmail=$ALERT_EMAIL" ${EXTRA_ORIGIN:+"ExtraAllowedOrigin=$EXTRA_ORIGIN"} \
    ${CUSTOM_DOMAIN:+"CustomDomain=$CUSTOM_DOMAIN"} ${CERT_ARN:+"CertificateArn=$CERT_ARN"}

output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
SITE_URL=$(output SiteUrl)
LIVE_URL=$(output LiveApiUrl)
BUCKET=$(output SiteBucketName)
DIST=$(output DistributionId)

echo "==> Building the site (live API: $LIVE_URL)"
if [[ ! -f web/public/data/index.json ]]; then
  echo "web/public/data is empty. Export briefs first, e.g.:"
  echo "  python -m idt_copilot.export.static_bundle --briefs-dir evals/runs/<run>/briefs --eval-results evals/runs/<run>/results.json"
  exit 1
fi
(cd web && npm ci --silent && VITE_LIVE_API_URL="$LIVE_URL" npm run build --silent)

echo "==> Uploading to s3://$BUCKET"
# Hashed assets never change, so browsers can keep them; everything else is checked on each visit.
aws s3 sync web/dist/assets "s3://$BUCKET/assets" --region "$REGION" --delete \
  --cache-control "public, max-age=31536000, immutable"
aws s3 sync web/dist "s3://$BUCKET" --region "$REGION" --delete --exclude "assets/*" \
  --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" \
  --query "Invalidation.Id" --output text >/dev/null

echo
echo "Site:     $SITE_URL"
if [[ -n "${CUSTOM_DOMAIN:-}" ]]; then
  echo "DNS:      CNAME $CUSTOM_DOMAIN -> $(output CloudFrontDomain)"
fi
echo "Live API: $LIVE_URL"
echo "Check:    curl -s ${LIVE_URL%/}/   (should print {\"ok\": true})"
