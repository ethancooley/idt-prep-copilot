# Deploying to AWS

The public site costs nothing to visit: it is static files on S3 behind CloudFront, serving briefs that were
generated ahead of time. Live runs go to one Lambda function that streams the agent's progress to the
browser, and only people with the access code can start one.

```
Browser ──► CloudFront ──► S3            static site + saved briefs (JSON)
   │
   └─────► Lambda Function URL           POST /live-run/stream, newline-delimited JSON
             └─ Lambda Web Adapter ──► idt_copilot.api.server ──► LangGraph agent ──► Claude
                                                       │
                     SSM Parameter Store (secrets) ────┤
                     Neon Postgres (chart + run log) ──┘
```

Python Lambdas cannot stream responses on their own, so the function runs the
[Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) layer. It forwards requests to the
same HTTP server you run locally (`python -m idt_copilot.api.server`), with response streaming on.

## What it costs

Everything here fits in AWS's always-free usage, and the template adds a budget that emails you as soon as
the account is charged a single cent.

| Piece | Why it stays free |
| --- | --- |
| CloudFront | Always free up to 1 TB and 10 million requests a month |
| Lambda | Always free up to 1 million requests and 400,000 GB-seconds a month. A live run uses about 30 GB-seconds, so even 20 a day is under 5% of that |
| S3 | A few megabytes of site files, plus the deploy packages SAM uploads: fractions of a cent |
| SSM Parameter Store | Standard parameters are free |
| CloudWatch Logs | Kept for 7 days, well under the free 5 GB |
| Neon | Free plan; the database is a few megabytes |
| Claude | About $0.04 per live run. Capped by the daily limit (20) and your Anthropic spend limit |

## One-time setup

You need the AWS CLI v2 and the AWS SAM CLI (`brew install awscli aws-sam-cli`), signed in as an IAM or
Identity Center user, not the root user. Everything below uses `us-east-1`.

**1. Database on Neon.** Create a free project at [neon.com](https://neon.com) in AWS `us-east-1` (same region
as the Lambda), copy the connection string, and load the synthetic cohort into it:

```bash
DATABASE_URL='postgresql://...neon.tech/neondb?sslmode=require' python -m idt_copilot.db.load
```

Add `--embed` if you also want semantic search when you point local tools at Neon. Live runs use keyword
search, which keeps the Lambda small.

**2. A separate Anthropic key for the site.** In the Anthropic Console, create a new API key just for the
deployed site (ideally in its own workspace with a monthly spend limit, such as $20). If it ever leaks, you
revoke it without touching your development key.

**3. Secrets.** These go into SSM Parameter Store as encrypted SecureStrings. You type them at a hidden prompt,
so they never appear in your shell history, the repo, or the Lambda's environment variables:

```bash
./deploy/put_secrets.sh
```

Pick an access code that is long and random (`openssl rand -base64 18`), and share it only with people you
want to run the agent.

**4. Real briefs for the site.** Run the eval once and export its briefs, so the site opens on real agent
output and real accuracy numbers:

```bash
python -m idt_copilot.evals.run_evals
python -m idt_copilot.export.static_bundle --briefs-dir evals/runs/<run>/briefs \
    --eval-results evals/runs/<run>/results.json
```

## Deploy

```bash
ALERT_EMAIL=you@example.com ./deploy/deploy.sh
```

It builds the Lambda package, deploys the stack, builds the site with the live API's URL, uploads it, and
prints the site URL. Run it again after any change. Then check:

```bash
curl -s https://<function-url>/            # {"ok": true}
```

and open the site, pick a participant, and choose **Watch the agent build one live**.

## Use your own domain

The site works at its `cloudfront.net` address, but a subdomain of a domain you own, such as
`idt.ethancooley.com`, looks better and costs nothing extra: the certificate is free, and the DNS records go
wherever your domain's DNS already lives.

1. **Request a certificate** in us-east-1 (CloudFront only accepts certificates from there):
   ```bash
   aws acm request-certificate --region us-east-1 --domain-name idt.example.com --validation-method DNS \
     --query CertificateArn --output text
   ```
2. **Prove you own the domain.** Get the validation record:
   ```bash
   aws acm describe-certificate --region us-east-1 --certificate-arn <arn> \
     --query "Certificate.DomainValidationOptions[0].ResourceRecord"
   ```
   At your DNS provider, add a **CNAME** with that `Name` and `Value`. Leave it in place: ACM uses it to renew
   the certificate automatically. Wait until the status is `ISSUED` (usually 5 to 30 minutes):
   ```bash
   aws acm describe-certificate --region us-east-1 --certificate-arn <arn> --query Certificate.Status
   ```
3. **Deploy with the domain.** Put `CUSTOM_DOMAIN` and `CERT_ARN` in `deploy/config.env` and run
   `./deploy/deploy.sh`. It prints the record to add next.
4. **Point the subdomain at CloudFront.** At your DNS provider, add a **CNAME** from `idt` to the
   `xxxx.cloudfront.net` address the deploy printed. Once DNS updates (minutes, sometimes an hour), the site
   is live at your domain, with HTTPS.

The `cloudfront.net` address keeps working too.

## Deploy on every push to main

Once this is set up, pushing to `main` runs the tests and the web build on GitHub Actions and, only if they
pass, runs `deploy.sh`. GitHub signs in to AWS with short-lived credentials (OIDC), so no AWS keys are stored
in GitHub.

1. **Create the role GitHub will use** (once):
   ```bash
   aws cloudformation deploy --template-file deploy/github-oidc.yaml --stack-name idt-copilot-github \
     --capabilities CAPABILITY_IAM
   aws cloudformation describe-stacks --stack-name idt-copilot-github \
     --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text
   ```
   Only pushes to `main` in `ethancooley/idt-prep-copilot` can use this role. If the repo has another name,
   add `--parameter-overrides GitHubRepo=owner/repo`.
2. **Add repository variables** on GitHub: **Settings → Secrets and variables → Actions → Variables**:
   `AWS_DEPLOY_ROLE_ARN` (from step 1), `ALERT_EMAIL`, and, if you use one, `CUSTOM_DOMAIN` and `CERT_ARN`.
   None of these are secrets. The real secrets stay in SSM Parameter Store.
3. **Push to `main`.** Watch it under the repo's **Actions** tab. The **Run workflow** button redeploys without
   a new commit.

Until `AWS_DEPLOY_ROLE_ARN` is set, the deploy job is skipped and CI runs as before.

## Day to day

| Task | How |
| --- | --- |
| Change a secret or the access code | `./deploy/put_secrets.sh`, then force a cold start: `aws lambda update-function-configuration --function-name idt-copilot-live --description "secrets updated $(date +%F)"` |
| Turn live runs off | Delete `/idt-copilot/IDT_ACCESS_CODE` and force a cold start. The site keeps working; live runs answer 503 |
| Change the caps | `sam deploy ... --parameter-overrides DailyLiveLimit=10 PerVisitorLimit=2` (or edit and rerun `deploy.sh`) |
| See live-run usage | `SELECT created_at, status, cost_usd, seconds FROM live_runs ORDER BY id DESC;` on Neon |
| Read logs | `sam logs --stack-name idt-copilot --tail` |
| Call the live API from `npm run dev` | `EXTRA_ORIGIN=http://localhost:5173 ALERT_EMAIL=... ./deploy/deploy.sh`, then `VITE_LIVE_API_URL=<function-url> npm run dev` |
| Remove everything | Empty the site bucket, then `sam delete --stack-name idt-copilot` |

## What protects your credits

- **Access code**, compared in constant time, with a half-second delay after a wrong guess
- **Caps** in Postgres: 3 live runs per visitor per day and 20 per day in total. Visitors are counted by a
  salted hash of their IP address; the address itself is never stored
- **Anthropic spend limit** on the site's own key, as a hard ceiling
- **$1 AWS budget** that emails you at the first cent
- A visitor who closes the window mid-run cannot dodge the caps: the run is counted when it starts
