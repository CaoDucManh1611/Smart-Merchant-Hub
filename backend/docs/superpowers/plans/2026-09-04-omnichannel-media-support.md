# Omnichannel Media Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably ingest, store, retrieve, render, and send image/audio/sticker/video/file messages for Facebook, Instagram, Telegram, and Zalo while preserving tenant isolation.

**Architecture:** Keep `messages.media_type` and `messages.media_url` as a compatibility mirror of the first attachment, and add a tenant-owned `message_attachments` table for the complete ordered list. Provider adapters produce canonical attachments; a media resolver streams provider URLs or resolves provider file IDs server-side; outbound and frontend flows use the same canonical media contract.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/pgvector, Pydantic contracts, httpx, Vue 3.

**Spec:** `backend/docs/superpowers/specs/2026-09-04-media-support-design.md`

## Global Constraints

- Every attachment belongs to the same `business_id`, `channel_id`, and `message_id` as its parent message.
- Provider file IDs and URLs are stored as metadata; access tokens are never returned to the frontend or persisted in raw message payloads.
- Duplicate webhook deliveries remain idempotent using the existing channel event/message identity constraints.
- Unsupported outbound media is rejected with a useful 4xx response and is never written as a successful outbound message.
- Existing text-message behavior and the legacy `messages.media_type`/`messages.media_url` fields remain backward compatible.

---

### Task 1: Add the tenant-scoped attachment schema and migration

**Files:**
- Create: `backend/app/models/message_attachment.py`
- Modify: `backend/app/models/message.py` (relationship)
- Modify: `backend/app/models/__init__.py` (export)
- Create: `backend/alembic/versions/20260904_0008_message_attachments.py`
- Test: `backend/tests/test_message_attachments.py`

**Interfaces:**
- Produces `MessageAttachment` with `id`, `business_id`, `message_id`, `channel_id`, `media_type`, `mime_type`, `file_name`, `duration_ms`, `external_attachment_id`, `source_url`, `storage_key`, `metadata_`, and `created_at`.
- The unique provider identity is `(channel_id, external_attachment_id)` when the external ID is present.

- [ ] **Step 1: Write the failing schema test**

```python
def test_message_attachment_requires_same_tenant_parent(engine):
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="One", slug="one")
        db.add(business)
        db.flush()
        message = Message(conversation_id=1, channel="telegram", direction="inbound")
        db.add(message)
        db.flush()
        attachment = MessageAttachment(
            business_id=business.id,
            message_id=message.id,
            channel_id=1,
            media_type="audio",
            external_attachment_id="voice-1",
        )
        db.add(attachment)
        db.commit()
        assert db.get(MessageAttachment, attachment.id).business_id == business.id
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `backend`:
`$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"; & 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_message_attachments.py -q`

Expected: collection failure because `MessageAttachment` is not defined.

- [ ] **Step 3: Implement the model and Alembic migration**

Use SQLAlchemy fields matching the spec and add foreign keys to `businesses`, `messages`, and `channels`. The migration must create indexes for `business_id`, `message_id`, and `(channel_id, external_attachment_id)` and must be reversible.

- [ ] **Step 4: Run the test and migration checks**

Run the test above and `python -m alembic upgrade head` against the project PostgreSQL database. Expected: test passes and head advances to `20260904_0008`.

- [ ] **Step 5: Commit**

```text
git add app/models/message_attachment.py app/models/message.py app/models/__init__.py alembic/versions/20260904_0008_message_attachments.py tests/test_message_attachments.py
git commit -m "feat: add tenant-scoped message attachments"
```

### Task 2: Preserve every normalized attachment during inbound ingestion

**Files:**
- Create: `backend/app/services/media_service.py`
- Modify: `backend/app/services/message_service.py:1176` (`process_and_save_message`)
- Modify: `backend/app/api/facebook.py`, `backend/app/api/instagram.py`, `backend/app/api/telegram.py`, `backend/app/api/zalo.py`
- Test: `backend/tests/test_media_persistence.py`

**Interfaces:**
- `save_message_attachments(db, *, message_id: int, business_id: int, channel_id: int, attachments: list[NormalizedAttachment]) -> list[MessageAttachment]`.
- `process_and_save_message` accepts an `attachments` list and mirrors only the first item to legacy message columns.

- [ ] **Step 1: Write the failing persistence test**

```python
def test_ingestion_persists_all_attachments_in_order(client, db):
    payload = telegram_payload_with_photo_voice_and_sticker()
    response = client.post("/api/webhooks/telegram", headers=valid_headers(), json=payload)
    assert response.status_code == 200
    rows = db.scalars(select(MessageAttachment).order_by(MessageAttachment.id)).all()
    assert [row.media_type for row in rows] == ["image", "audio", "sticker"]
```

- [ ] **Step 2: Run the test to verify it fails**

Expected: the webhook may create a message, but the attachment query returns no rows.

- [ ] **Step 3: Implement persistence**

Convert each `NormalizedAttachment` with `model_dump(mode="json")`, insert rows after the parent message has an ID, and pass the full attachment list from all webhook routes. Preserve `media_type`/`media_url` from the first attachment for existing list/detail responses.

- [ ] **Step 4: Run the targeted tests**

Run `pytest tests/test_media_persistence.py tests/test_zalo_webhook.py tests/test_channel_contracts.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```text
git add app/services/media_service.py app/services/message_service.py app/api/facebook.py app/api/instagram.py app/api/telegram.py app/api/zalo.py tests/test_media_persistence.py
git commit -m "feat: persist complete inbound media lists"
```

### Task 3: Normalize image, audio, and sticker variants in every adapter

**Files:**
- Modify: `backend/app/integrations/_meta.py`
- Modify: `backend/app/integrations/telegram.py`
- Modify: `backend/app/integrations/zalo.py`
- Modify: `backend/app/integrations/base.py`
- Tests: `backend/tests/test_channel_contracts.py`, `backend/tests/test_telegram_adapter.py`, `backend/tests/test_zalo_adapter.py`, `backend/tests/test_meta_media_contracts.py`

**Interfaces:**
- Every adapter returns `NormalizedAttachment(media_type, url, external_attachment_id, metadata)`.
- `metadata` carries provider-only fields such as MIME type, duration, file name, and Telegram/Zalo file IDs.

- [ ] **Step 1: Add failing adapter cases**

```python
def test_telegram_audio_and_sticker_are_normalized():
    event = TelegramAdapter().parse_events(
        {"update_id": 1, "message": {"message_id": 2, "from": {"id": 3}, "chat": {"id": 3},
         "audio": {"file_id": "audio-1", "duration": 4},
         "sticker": {"file_id": "sticker-1"}}},
        external_account_id="bot-1",
    )[0]
    assert [a.media_type.value for a in event.messages[0].attachments] == ["audio", "sticker"]
```

- [ ] **Step 2: Run adapter tests and verify the new cases fail**

Expected: current Telegram parser returns at most one attachment and does not normalize audio/sticker together.

- [ ] **Step 3: Implement provider mappings**

Meta must map `photo`, `audio`, `voice`, `sticker`, `video`, and `file` aliases. Telegram must preserve `photo`, `audio`, `voice`, `sticker`, `document`, and `video` IDs. Zalo must accept `photo_url`/`image_url`, `audio_url`/`voice`/`audio`, and sticker URL/ID variants. Ignore bot/echo events.

- [ ] **Step 4: Run all adapter tests**

Run `pytest tests/test_channel_contracts.py tests/test_telegram_adapter.py tests/test_zalo_adapter.py tests/test_meta_media_contracts.py -q`. Expected: all pass.

- [ ] **Step 5: Commit**

```text
git add app/integrations/_meta.py app/integrations/telegram.py app/integrations/zalo.py app/integrations/base.py tests/test_channel_contracts.py tests/test_telegram_adapter.py tests/test_zalo_adapter.py tests/test_meta_media_contracts.py
git commit -m "feat: normalize media variants across channel adapters"
```

### Task 4: Add a tenant-safe media resolver and streaming endpoint

**Files:**
- Create: `backend/app/services/media_resolver.py`
- Create: `backend/app/api/media.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/integrations/base.py`, `backend/app/integrations/telegram.py`
- Test: `backend/tests/test_media_proxy.py`

**Interfaces:**
- `resolve_media_response(db, *, attachment_id: int, tenant: TenantContext) -> StreamingResponse`.
- `GET /api/media/{attachment_id}` returns the attachment bytes using the tenant-owned Channel credential; a cross-tenant or missing attachment returns 404.

- [ ] **Step 1: Write failing media proxy tests**

```python
def test_media_proxy_rejects_cross_tenant_attachment(client, other_tenant_attachment):
    response = client.get(f"/api/media/{other_tenant_attachment.id}", headers={"X-Business-Id": "1"})
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests and verify the endpoint is missing**

Expected: 404 because the route is not registered.

- [ ] **Step 3: Implement resolver and route**

Query attachment, parent message, and Channel with matching `business_id`; stream `source_url` when present, otherwise call an adapter resolver. Telegram adds `getFile` resolution for file IDs. Never accept a token or arbitrary remote URL from query parameters.

- [ ] **Step 4: Run proxy tests**

Run `pytest tests/test_media_proxy.py -q`. Expected: tenant isolation, content type, and provider-ID resolution pass.

- [ ] **Step 5: Commit**

```text
git add app/services/media_resolver.py app/api/media.py app/api/router.py app/integrations/base.py app/integrations/telegram.py tests/test_media_proxy.py
git commit -m "feat: add tenant-safe media streaming"
```

### Task 5: Implement unified outbound media sending

**Files:**
- Modify: `backend/app/integrations/base.py`, `backend/app/integrations/facebook.py`, `backend/app/integrations/instagram.py`, `backend/app/integrations/telegram.py`, `backend/app/integrations/zalo.py`
- Modify: `backend/app/services/telegram_service.py`, `backend/app/services/zalo_service.py`, `backend/app/services/facebook_service.py`, `backend/app/services/instagram_service.py`
- Modify: `backend/app/api/conversations.py`
- Tests: `backend/tests/test_outbound_media.py`, existing provider outbound tests

**Interfaces:**
- `send_media(db, *, business_id, conversation_id, recipient_id, media_type, source_url, caption=None) -> dict`.
- Channel credentials are selected only by tenant and conversation ownership.

- [ ] **Step 1: Write failing outbound tests**

```python
def test_telegram_audio_uses_tenant_channel_and_file_endpoint(client, telegram_conversation):
    response = client.post(
        f"/api/conversations/{telegram_conversation.id}/send-media",
        headers={"X-Business-Id": "1"},
        data={"media_type": "audio", "media_url": "https://cdn.example/audio.ogg", "caption": "Nghe thử"},
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run the test and verify it fails**

Expected: endpoint is missing or reports unsupported media.

- [ ] **Step 3: Implement adapter-specific outbound payloads**

Use the provider API's supported media operation for each type, preserve provider message IDs, and raise a 422/409 for unsupported combinations before inserting a message. Reuse the existing tenant credential helpers and outbound persistence.

- [ ] **Step 4: Run outbound tests**

Run `pytest tests/test_outbound_media.py tests/test_telegram_outbound.py tests/test_zalo_outbound.py tests/test_instagram_outbound.py -q`. Expected: supported sends persist correctly and unsupported sends create no rows.

- [ ] **Step 5: Commit**

```text
git add app/integrations app/services/*_service.py app/api/conversations.py tests/test_outbound_media.py
git commit -m "feat: add tenant-scoped outbound media"
```

### Task 6: Render and compose media in the Vue inbox

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Create: `frontend/tests/media.spec.js`

**Interfaces:**
- `normalizedMediaType(message)`, `mediaUrl(message)`, and `mediaProxyUrl(message)` support image/audio/sticker/video/file.
- Composer sends `POST /api/conversations/{id}/send-media` and only adds an optimistic message after a successful response.

- [ ] **Step 1: Write failing frontend tests**

```javascript
it('renders audio and sticker messages with the correct native element', () => {
  expect(mediaPresentation({ media_type: 'audio', media_url: '/api/media/1' })).toBe('audio')
  expect(mediaPresentation({ media_type: 'sticker', media_url: '/api/media/2' })).toBe('sticker')
})
```

- [ ] **Step 2: Run frontend tests and verify the new cases fail**

Expected: the current media helper only recognizes image/video.

- [ ] **Step 3: Implement rendering and composer controls**

Use `<img>`, `<audio controls>`, `<video controls>`, and a downloadable file link. Use the media proxy URL for attachments with an ID, and show a text fallback when a provider file is unavailable.

- [ ] **Step 4: Run the frontend build and browser smoke check**

Run `npm run build` from `frontend`, then open the inbox in the dev server and verify one image, one audio player, one sticker image, one video, and one file link. This repository has no frontend test runner configured, so the browser smoke check is the executable UI verification for this task.

- [ ] **Step 5: Commit**

```text
git add ../frontend/src/App.vue ../frontend/src/style.css ../frontend/tests/media.spec.js
git commit -m "feat: render and compose omnichannel media"
```

### Task 7: End-to-end verification and operational documentation

**Files:**
- Modify: `backend/README.md`
- Modify: `README.md`
- Test: `backend/tests/test_media_end_to_end.py`

- [ ] **Step 1: Add an end-to-end tenant/media contract test**

Cover one inbound multi-attachment event for each provider, one media proxy request, one supported outbound request, duplicate delivery, and a cross-tenant 404.

- [ ] **Step 2: Run backend verification**

Run targeted media tests, then the full backend suite with the same environment used by Docker. Expected: zero media regressions; document any unrelated environment-only failures separately.

- [ ] **Step 3: Document deployment and manual checks**

Document Alembic upgrade, backend/frontend rebuild, provider webhook requirements, and the expected 200/401/404 behavior.

- [ ] **Step 4: Commit**

```text
git add README.md backend/README.md backend/tests/test_media_end_to_end.py
git commit -m "test: verify omnichannel media flow"
```
