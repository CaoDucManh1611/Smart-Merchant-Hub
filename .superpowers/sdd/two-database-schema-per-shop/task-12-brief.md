# Task 12 — Kết nối và định tuyến Telegram, Zalo, Facebook, Instagram theo từng shop

## Files
- Create `backend/app/tenancy/registry.py`.
- Modify `backend/app/tenancy/webhook.py`, provider/channel/meta config services, Telegram/Zalo/Facebook/Instagram/Meta OAuth/Shopee/TikTok/onboarding APIs and onboarding schema.
- Modify `frontend/src/App.vue`, `frontend/src/style.css`.
- Modify onboarding/webhook/Meta OAuth tests and `frontend/tests/crm-shell.test.mjs`.

## Interface
```python
@dataclass(frozen=True)
class WebhookRoute:
    business_id: int
    schema_name: str
    channel_id: int

def resolve_webhook_route(platform_db: Session, provider: str, route_key: str) -> WebhookRoute | None: ...
```

- `GET /api/onboarding/shops/{business_id}/channels` returns one normalized connection record per linked provider account with state `disconnected`, `verifying`, `connected`, `reconnect_required` or `error`.
- `POST /api/onboarding/shops/{business_id}/channels/verify` accepts only `telegram` or `zalo` plus a one-time token; response never echoes token.
- Meta OAuth start/callback bind OAuth state to authenticated shop.

## Required work
- Contract tests for shared four-provider connection card, normalized states, masked account details and no tokens in responses.
- Telegram: QR/deep-link BotFather, one-time token, getMe, generated secret, setWebhook/getWebhookInfo, reconnect/disconnect.
- Zalo: QR/deep-link Bot Manager, one-time Bot Creator token, identity verification, webhook registration/status, reconnect/disconnect.
- Meta: CSRF-bound state, shop binding, Page selection, Instagram Business Account discovery, required permissions, long-lived/Page token storage, webhook subscription, reconnect-required on expiry/revocation.
- UI: Telegram/Zalo QR/deep-link + token field; Facebook/Instagram OAuth button; no manual Meta access-token input.
- Routing: Telegram secret hash and provider account hash, ambiguous/no-route rejection, inactive-shop rejection, no scan over tenant channel tables.
- Normalize provider DTOs while keeping adapters independent; provider failures isolated.
- Atomically coordinate encrypted tenant token storage and platform route creation with idempotency/compensating cleanup.
- Verify provider signature before persistence; platform route first, then tenant-only payload/event storage.
- Route keys use keyed HMAC with secret separate from `CHANNEL_ENCRYPTION_KEY`.
- Encrypt Telegram/Zalo bot tokens and Meta user/page tokens in tenant schema; store expiry/scopes/provider metadata without exposing secrets.
- Scheduled health checks mark reconnect_required; never fall back to global/default credential.
- Provider retry/idempotency remains schema-local; duplicate webhook succeeds without duplicate message/reply.
- Run backend channel/onboarding suites from the plan and `node --test tests/crm-shell.test.mjs`.
- Commit `feat: connect and route tenant-owned messaging channels`.

## Global constraints
Platform stores only minimal hashed routing metadata; tenant schema owns tokens/content. Schemas server-generated only. TDD required. Preserve existing self-service Telegram/Zalo onboarding behavior while making it tenant-owned.

