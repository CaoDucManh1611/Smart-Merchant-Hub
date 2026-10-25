# Social connection stability

## 2026-10-25 follow-up

Meta now forwards image-only bubbles. Outbound delivery reuses a separate serialized sender tab, re-navigates on thread or Page changes, and retains reload verification. Visible monitor-tab recovery stays within the same Page asset and excludes the sender. Facebook meter-image and sequential text tests are recorded in `artifacts/chatbot-image-latency-fixes-2026-10-25.md`; other channels and bank settlement are not yet accepted end to end.

Priority selected by user: Facebook first, other channels afterward.

## Confirmed defect and fix
Periodic heartbeat overwrote connector error with online. Shared heartbeat now retains last explicit state/error. Meta reports login_required or inbox_not_open until inbox is available, and recovers state after navigation.

## Verification
50 connector/Meta tests passed; 2 skipped. Updated Meta executable packaging in progress.

## Remaining acceptance
- Apply rebuilt executable, one active session; verify heartbeat, incoming message, reply, history echo.
- Test network loss, browser close and login expiry with user-controlled session.
- Instagram, Telegram, Zalo, Shopee, TikTok require separate configured sessions and test messages.
- Legacy Shopee/TikTok official webhook endpoints are not equivalent to the authenticated connector ingress; do not count their ACK as CRM persistence.

## Facebook application
Updated Messenger EXE packaged and self-test passed. Installed in existing Downloads connector directory with backup and restarted using saved pairing. One parent/child EXE pair observed. Authenticated heartbeat online after launch. Awaiting user inbound test before end-to-end signoff.
