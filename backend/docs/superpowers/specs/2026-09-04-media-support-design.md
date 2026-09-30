# Omnichannel media support design

## Goal

Make image, audio, sticker, video, and file messages reliable across Facebook,
Instagram, Telegram, and Zalo without losing tenant ownership or exposing
provider credentials. Existing text-message behavior and the legacy
`messages.media_type`/`messages.media_url` fields remain backward compatible.

## Scope and invariants

- Every attachment belongs to the same `business_id`, `channel_id`, and
  `message_id` as its parent message.
- Provider payloads are normalized into the existing `NormalizedAttachment`
  contract. All attachments are preserved in their original order.
- Provider file IDs and URLs are stored as metadata; access tokens are never
  returned to the frontend or persisted in raw message payloads.
- Duplicate webhook deliveries remain idempotent using the existing channel
  event/message identity constraints.
- Unsupported outbound media is rejected with a useful 4xx response and is
  never written as a successful outbound message.

## Data model

Add a tenant-scoped `message_attachments` table with:

- `id`, `business_id`, `message_id`, `channel_id`
- `media_type`, `mime_type`, `file_name`, `duration_ms`
- `external_attachment_id`, `source_url`, `storage_key`
- `metadata`, `created_at`

The existing message media columns continue to mirror the first attachment for
legacy list/detail responses. A migration creates the table and indexes by
`business_id`, `message_id`, and the provider identity tuple.

## Inbound flow

Each channel adapter maps provider-specific payloads to the canonical media
types. Meta keeps all attachment entries; Telegram keeps file IDs and resolves
file metadata through its Bot API when a URL is required; Zalo handles its
image/audio/sticker payload variants. The webhook route binds the normalized
event to the trusted Channel before inserting message attachments.

## Media retrieval

Expose a tenant-scoped media endpoint that resolves an attachment through its
Channel adapter. It may stream a provider URL or resolve a provider file ID,
but it never accepts a token from the client. This avoids relying on expiring
Meta/Zalo URLs and gives Telegram audio/sticker files a stable CRM URL.

## Outbound flow

Extend the common conversation-send contract with a media type and source. The
service selects the active Channel by `business_id` and conversation ownership,
then delegates provider-specific payload construction to the adapter. Text,
image, audio, sticker, video, and file support is implemented only where the
provider API supports it; other combinations return an explicit 422/409.

## Frontend

Render media by canonical type: image preview, native audio player, sticker
image, video player, and downloadable file. The composer sends media through the
same tenant-scoped endpoint and displays provider errors without creating a
phantom message.

## Testing

- Adapter tests for every provider and each media type, including multiple
  attachments and provider IDs without public URLs.
- Webhook tests for tenant binding, idempotency, and bot/echo filtering.
- Database tests for attachment ownership and cross-tenant 404 behavior.
- Media proxy tests proving credentials are selected server-side.
- Outbound tests for supported and explicitly rejected media types.
- Frontend tests for rendering and composer payload mapping.
