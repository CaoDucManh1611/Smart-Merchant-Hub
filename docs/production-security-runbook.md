# Production security runbook

This repository now fails fast when `ENVIRONMENT=production` is missing the
required security settings. The runbook below still requires an operator with
access to the real secret manager, Git remote and PostgreSQL instance.

## 1. Rotate secrets and tokens

Do this in the provider dashboard/secret manager, not in source code:

1. Revoke and regenerate Meta app secret, Facebook Page token, Instagram
   token, Telegram bot token, Zalo token and any LLM/API keys.
2. Generate fresh random `AUTH_SECRET` and `CHANNEL_ENCRYPTION_KEY` values.
   Never replace `CHANNEL_ENCRYPTION_KEY` blindly if existing encrypted channel
   rows still need to be decrypted; re-encrypt them in a controlled migration.
3. Change the PostgreSQL password and update `DATABASE_URL` atomically with the
   deployment secret.
4. Update the webhook verify token and provider webhook configuration.
5. Redeploy, verify health/webhooks, then revoke every old credential.

For LLM/embedding providers, place a comma-separated pool in the secret
manager (`GROQ_API_KEYS`, `LLM_API_KEYS` or `EMBEDDING_API_KEYS`). The runtime
round-robins keys, cools down transiently failing keys and redacts key values;
replace the pool and restart the deployment to complete a rotation.

For encrypted rows, use the repository rotation command instead of changing
`CHANNEL_ENCRYPTION_KEY` in place. Put the old and new values in protected
secret-manager variables (never command-line arguments), take a backup, run a
dry-run, then commit the rotation:

```powershell
$env:OLD_CHANNEL_ENCRYPTION_KEY = '<old value from the secret manager>'
$env:CHANNEL_ENCRYPTION_KEY = '<new value from the secret manager>'
python backend/scripts/rotate_channel_secrets.py
python backend/scripts/rotate_channel_secrets.py --confirm
```

The command re-encrypts channel tokens, MFA/contact material and OA secret
configuration; outstanding OTP challenges are expired so they cannot be
verified with the old key.

Example generators (the output must stay private):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 2. Audit Git history

From the repository root, run:

```powershell
python backend/scripts/security_audit.py --history --fail-on-findings
```

The scanner intentionally prints only a commit/path/pattern label. Any real
finding must be treated as compromised: rotate it first, then remove it from
history with an approved `git filter-repo`/remote cleanup procedure. Do not
rewrite the shared remote history from this task automatically.

`.env` and `backend/.env` are ignored. Keep only placeholders in
`backend/.env.example`; never paste a live value into an issue, chat, commit or
terminal transcript.

## 3. Retire legacy credentials

After the encrypted `channels.access_token_encrypted` rows are verified and a
PostgreSQL backup exists, run a dry-run:

```powershell
python backend/scripts/retire_legacy_credentials.py
```

Only after checking the counts and channel mapping:

```powershell
python backend/scripts/retire_legacy_credentials.py --confirm
```

## 4. P1 tenant and SaaS operations

Run the additive migration before starting application replicas:

```powershell
alembic upgrade head
alembic check
```

The current head is `20260913_0042_p1_saas_platform`. On PostgreSQL it enables
tenant RLS policies for applicable `business_id` tables. Application requests
set a transaction-local `app.business_id`; platform-admin operations must use
the explicit platform context. Do not run the application with a database role
that bypasses RLS in production.

For a new shop, use the onboarding API in this order:

1. `GET /api/onboarding/plans` and display only the plan metadata.
2. `POST /api/onboarding/shops` to create the shop owner and subscription.
3. Add channels through the tenant-authenticated channel endpoint; verify that
   the response contains no token or secret.
4. Import products and confirm the returned imported/updated/skipped counts.
5. Check `GET /api/usage` and `/api/usage/warnings` before enabling campaigns.

Platform operators should page `/api/platform/shops`, review quota warnings and
provider-error metadata, and use the privacy lifecycle endpoints for export,
anonymization or deletion. These endpoints intentionally return counts and
status only; never copy customer payloads or credentials into tickets or logs.

The command deletes only the known legacy token keys in `app_settings` and
never prints their values. It refuses to delete anything when no encrypted
channel credential exists.

## 4. CORS, HTTPS and rate limiting

Set these in the production secret/config manager:

```dotenv
ENVIRONMENT=production
CORS_ORIGINS=https://crm.example.com
ALLOWED_HOSTS=api.example.com
PUBLIC_BASE_URL=https://api.example.com
FRONTEND_BASE_URL=https://crm.example.com
FORCE_HTTPS=true
HSTS_ENABLED=true
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=120
RATE_LIMIT_WINDOW_SECONDS=60
```

Terminate TLS at the load balancer/reverse proxy and forward only HTTPS to the
application network. The application also redirects HTTP when
`FORCE_HTTPS=true`, adds HSTS when enabled, rejects unlisted hosts and applies
a per-IP sliding-window limit to `/api` requests. The built-in limiter is
per-process; multi-replica deployments must also enforce a shared proxy/Redis
limit.

For a multi-replica deployment, configure the load balancer/API gateway with
the same window and burst policy, set `RATE_LIMIT_BACKEND=proxy` and
`RATE_LIMIT_TRUSTED_PROXY=true`, and make the proxy overwrite (not append)
`X-Forwarded-For`. The app keeps its local guard as a second line of defense;
do not rely on in-process state as the shared quota.

If the gateway does not provide a shared limiter, use the included Redis
backend instead. Redis is provisioned by `docker-compose.yml`; set:

```dotenv
RATE_LIMIT_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

The limiter uses one atomic Redis script per hashed client key. A Redis outage
fails API requests closed with `503` and is visible in `/health/details`,
`/health/alerts` and `/metrics`.

## 5. Provider webhook signature gate

Before enabling a channel in staging, run the provider contract suite. It
computes the same signed raw request bytes used by the adapters and verifies
both acceptance and rejection for Facebook/Instagram Meta HMAC, Telegram bot
secret headers and Zalo Bot/OA signatures:

```powershell
$env:CHANNEL_ENCRYPTION_KEY = '<test-only value>'
python -m pytest backend/tests/test_unified_inbox_webhooks.py `
  backend/tests/test_webhook_oauth_security.py `
  backend/tests/test_zalo_webhook.py `
  backend/tests/test_instagram_webhook.py -q
```

The final staging gate must additionally deliver one real callback from each
provider dashboard and confirm a single `channel_events` row/message per
delivery. Do not put provider secrets or callback payloads in Git or logs.

## 6. Real OTP delivery

Production rejects disabled or in-chat OTP. Configure a real SMTP provider
(Gmail requires an App Password) in the secret manager and keep the fallback
disabled:

```dotenv
OTP_DELIVERY_MODE=smtp
OTP_DELIVERY_FALLBACK=disabled
OTP_FROM_EMAIL=your-shop@example.com
OTP_SMTP_HOST=smtp.example.com
OTP_SMTP_PORT=587
OTP_SMTP_USERNAME=your-shop@example.com
OTP_SMTP_PASSWORD=<provider app password>
OTP_SMTP_USE_TLS=true
```

Run one staging checkout verification to the controlled test mailbox, then
check the provider delivery result and the redacted application audit event.

## 7. Logs and customer audit history

Application handlers install a redaction filter for authorization headers,
tokens, passwords, secrets and database URLs. Do not log raw webhook payloads
or exception bodies from provider SDKs. Customer profile/tag changes are
append-only audit events and are exposed in the tenant-scoped Customer 360
timeline.

Mounting a JSON secret object is also supported for Docker/Kubernetes secret
volumes. Set `SECRET_MANAGER_MODE=file` and `SECRET_MANAGER_FILE` to the
mounted path; unknown fields are ignored and non-scalar values are rejected.

## 8. PostgreSQL backup and restore

Create and validate a custom-format backup:

```powershell
./backend/scripts/backup_postgres.ps1 -DatabaseUrl $env:DATABASE_URL -OutputDirectory ./backups
```

Restore only into a freshly provisioned staging database first:

```powershell
./backend/scripts/restore_postgres.ps1 `
  -BackupFile ./backups/crm_chatbot_YYYYMMDD_HHMMSS.dump `
  -TargetDatabaseUrl $env:STAGING_DATABASE_URL `
  -ConfirmRestore
```

Verify row counts, tenant isolation, login, webhook delivery and application
smoke tests. Promote the restored database only through the normal change
window. The restore script requires an explicit switch because `--clean` is
destructive.

For a repeatable rehearsal that verifies the archive, restores it, applies
migrations, and runs tenant/webhook smoke tests:

```powershell
./scripts/staging-rehearsal.ps1 `
  -BackupFile ./backups/crm_chatbot_YYYYMMDD_HHMMSS.dump `
  -StagingDatabaseUrl $env:STAGING_DATABASE_URL
```

Pass `-Overwrite` only when the staging database is isolated and the change
window explicitly allows cleaning existing objects.

## Deployment order

1. Take and validate the PostgreSQL backup.
2. Run the Git history audit.
3. Rotate provider/database/application credentials.
4. Verify encrypted channel rows, then retire legacy token rows.
5. Apply `alembic upgrade head` on PostgreSQL.
6. Deploy with production settings and run smoke tests.
7. Confirm monitoring, redacted logs and backup retention.

## 9. Monitoring and alerting

Scrape `GET /metrics` from Prometheus and route these alert names from
`GET /health/alerts` to Alertmanager: `database_unavailable`,
`queue_backlog`, `queue_failed_jobs`, `provider_circuit_open`,
`shared_rate_limit_unavailable` and `ai_cost_threshold`. Thresholds are
configured with `ALERT_QUEUE_PENDING_THRESHOLD` and
`ALERT_AI_COST_THRESHOLD`; payloads contain counters and error classes only,
never customer content or credentials.

