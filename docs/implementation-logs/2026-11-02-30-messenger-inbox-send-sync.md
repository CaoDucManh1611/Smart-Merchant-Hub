# Messenger inbox send and sync

Date: 2026-11-02

## Changes

- After the send endpoint confirms success, the composer clears and returns to its normal label immediately. Conversation and delivery-status refreshes run in the background, so a slow inbox refresh no longer keeps the composer busy. The button remains disabled while the actual send request is pending to prevent duplicate sends.
- The send operation keeps the conversation ID it started with. A late response or failure does not update the newly selected conversation or clear its draft and attachments.
- Removed the pending-message `đang gửi` label from the message bubble.
- Messenger/Instagram inbox rows use a provider thread ID when exposed by Meta, then a profile identity fallback, instead of the row's changing DOM position. New-message detection compares the prior preview for that same conversation.
- The live reader posts only unseen message IDs. Failed live/history sync attempts use exponential retry delays capped at 30 seconds, avoiding a request on every one-second poll. The active conversation is excluded from the changed-row reader in the same poll to avoid duplicate sync attempts.
- The Meta DOM reader now recognizes native audio/video elements and supported accessible voice controls. When Meta exposes an HTTPS media URL from its CDN, audio/video is persisted through the existing attachment contract so the CRM can render its player. When Meta exposes no usable URL, the message is retained as an audio/video item without a playable source.

## Verification and limits

- `git diff --check` completed without whitespace errors. Git emitted only existing LF/CRLF conversion warnings for unrelated RAG files.
- No tests or build were run.
- The supplied connector output contains repeated HTTP 500 responses with only `Internal Server Error`; it does not include the server exception. The local Docker/WSL runtime was unavailable during this work, so the underlying backend 500 is not confirmed fixed. This change prevents rapid repeat requests and stabilizes incremental reading, but the server stack trace is still needed to identify the 500 root cause.
- Meta may provide expiring media URLs or hide voice bytes behind an in-page player; the connector cannot guarantee playback for those messages without a provider download/API path.
- No credentials, pairing codes, message bodies, or customer identifiers are included in this log.
- No commit or push was made.
