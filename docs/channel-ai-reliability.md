# Channel and AI reliability handoff

## Webhook event state and retry contract

Inbound Facebook, Instagram, Telegram, and Zalo deliveries are normalized into
the tenant's `channel_events` inbox. The unique `(channel_id,
external_event_id)` key deduplicates provider redelivery. An event moves through
`processing` to `processed` or `failed`; a `processing` claim expires after five
minutes so a crashed worker can be recovered. Message-level external IDs and
the conditional event claim prevent repeated webhook/retry work from creating
duplicate CRM messages.

An owner-approved support session may retry a failed event:

```http
POST /api/support/channel-events/{event_id}/retry
Authorization: Bearer <short-lived support session>
```

The shop owner must grant `channels:retry` to a platform support user. The
session is short-lived/revocable and is checked against the platform database
on each request. A successful replay returns
`{"event_id": 51, "status": "processed", "messages_created": 1}`. `404`
means the event is not visible in that shop; `409` means it is not retryable,
its channel is inactive, its stored identity is invalid, or another worker
claimed it; `502` means processing failed and the event remains retryable.
The handler never accepts a tenant ID or replacement payload from the caller.

## Outbound retry behavior

Facebook/Instagram use the shared Meta request path; Telegram and Zalo use their
tenant-owned channel credentials. Automatic retry is bounded and applies only
to connection-establishment failures and explicit HTTP `425`/`429` rejection.
Read timeouts and `5xx` responses are treated as ambiguous and are not retried
automatically because the provider may already have accepted the message.
TikTok continues to use the existing local bridge; this work does not rebuild
or change that bridge.

Every staff send through the supported conversation APIs requires a random
`client_id`, retained by the browser when retrying the same optimistic message.
The tenant-scoped `channel_outbound_attempts` row is committed before provider
I/O and stores only the key, conversation/channel IDs, status, a safe error
code, and the local message ID—never message text, recipient IDs, media URLs,
or provider response bodies. `sent` retries return the already-saved message;
`retryable_failed` may claim the same key again only for known rejection or
pre-delivery connection failures. `processing` and `unknown` return `409` and
must be reconciled against the provider before another send. This intentionally
prefers a possible manual check over a duplicate message after a crash or an
ambiguous timeout.

Shop-scoped status can be inspected without message content:

```http
GET /api/conversations/{conversation_id}/delivery-attempts
```

Text and media send/retry endpoints return a safe `409` code/message when the
same key is in progress, conflicts with another conversation, or has an
ambiguous result. A retry in the composer resubmits the existing `client_id`;
new messages use `crypto.randomUUID()` keys.

Logs for the touched send/replay paths identify the provider, operation, status,
and exception class only. They do not print message text, recipient IDs, signed
media URLs, tokens, or raw provider exception bodies.

## Media and RAG contracts

The normalized media types are `text`, `image`, `video`, `audio`, `sticker`,
`file`, and `unknown`. Unsupported media is stored as an attachment/known type
and is not passed to text-only AI reply generation as an empty question.

Document ingestion and chat response fields, error codes, retry endpoints,
citations, no-context behavior, and human-handoff semantics are documented in
[`backend/app/rag/README.md`](../backend/app/rag/README.md). Documents, chunks,
failed runs, and retrieval are scoped to the tenant schema and business ID.

Generated answers are withheld unless they cite an in-range retrieved source.
Money values must also occur in the cited passages with the same VND/USD unit;
otherwise chat and auto-reply return the safe no-context/handoff contract. This
is an attribution/price guard, not a full semantic fact checker.

RAG operational logs retain counters, timings, provider/model names, question
length/hash and exception type. They do not retain question/answer content,
prompts, document filenames or raw exception messages.

## Proactive follow-up safety

Marketing/win-back follow-ups require the latest `marketing` consent to be
`granted`; any latest `proactive_messages=revoked` record blocks all proactive
messages. Granting either purpose through the API requires an inbound textual
customer message as evidence. The Customer 360 UI shows the latest state and
requires that message ID before recording consent.

Follow-ups are rate-limited per customer. A durable `sending` claim is committed
before provider I/O. A timeout, server error, process interruption, or failure
to persist the provider result becomes `delivery_unknown` and is never retried
automatically. Operators can filter `scheduled`, `failed`, `delivery_unknown`
and `sent` in Settings; ambiguous items explicitly require checking the channel.

## Verification record

All channel checks below are fixture/mock tests. No channel has been verified
against a live provider, no real message was sent, and no OAuth/API token was
used or changed.

| Channel | Mock/fixture coverage | Live verification |
| --- | --- | --- |
| Facebook | Signed webhook fixture, normalized event path, dedupe/replay, and shared Meta retry behavior (`test_unified_inbox_webhooks.py`, `test_channel_reliability.py`) | Not run; requires a shop-owned sandbox page/app |
| Instagram | Webhook parsing/signature and mocked outbound send (`test_instagram_webhook.py`, `test_instagram_outbound.py`) | Not run; requires a shop-owned sandbox account/app |
| Telegram | Adapter/webhook parsing plus mocked outbound, media, idempotent retry/replay (`test_telegram_adapter.py`, `test_telegram_outbound.py`) | Not run; requires a shop-owned test bot |
| Zalo | Adapter/webhook parsing, media and mocked outbound (`test_zalo_adapter.py`, `test_zalo_webhook.py`, `test_zalo_media.py`, `test_zalo_outbound.py`) | Not run; requires a shop-owned sandbox OA/app |
| TikTok | Existing bridge callback signature/contract only (`test_tiktok_webhook.py`); bridge was not rebuilt | Not run; no live bridge credentials or delivery test |

The backend regression run completed with **683 passed, 5 environment-gated
skips**. The two PostgreSQL-only cases passed separately against a disposable
PostgreSQL 16 database; the three Windows PowerShell tests for
`backup-verify.ps1` passed on the host. Tenant backup/restore script contract
tests passed in the backend suite, but those scripts were not invoked against
PostgreSQL because native PostgreSQL client tools are not installed on the
host. Frontend checks completed with **191 tests passed** and a
successful Vite production build. Vite reports a large minified JavaScript
chunk (about 681 kB). Tests use fixtures, SQLite, mocked provider calls and
fake support sessions; they do not make real OAuth/API calls.

Live provider connection, callback registration, token-refresh and delivery
checks remain intentionally unclaimed: they require channel-owner sandbox
credentials and explicit approval to use those environments.

Backup and restore scripts and their checksum/revision checks are described in
[`docs/runbooks/tenant-backup-restore.md`](runbooks/tenant-backup-restore.md).
A PostgreSQL 16 disposable-container migration downgrade/upgrade and
dump/restore rehearsal passed on 2026-09-30. The active shop database was not
accessed. Repeat on the exact deployment PostgreSQL major version before
release, and never point verification restore at the currently used shop DB.
