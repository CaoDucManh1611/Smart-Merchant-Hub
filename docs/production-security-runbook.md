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

## 5. Logs and customer audit history

Application handlers install a redaction filter for authorization headers,
tokens, passwords, secrets and database URLs. Do not log raw webhook payloads
or exception bodies from provider SDKs. Customer profile/tag changes are
append-only audit events and are exposed in the tenant-scoped Customer 360
timeline.

## 6. PostgreSQL backup and restore

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

## Deployment order

1. Take and validate the PostgreSQL backup.
2. Run the Git history audit.
3. Rotate provider/database/application credentials.
4. Verify encrypted channel rows, then retire legacy token rows.
5. Apply `alembic upgrade head` on PostgreSQL.
6. Deploy with production settings and run smoke tests.
7. Confirm monitoring, redacted logs and backup retention.

