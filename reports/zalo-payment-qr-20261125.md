# Zalo payment QR delivery — 2026-11-25

## Verified cause
Shop 8, conversation 28, CHAT-9: outbound messages 740 and 743 were failed sends, not delivered messages. Jobs 361/363 recorded Zalo's explicit `The photo URL is invalid` rejection. The payment instructions were attached to the rejected image, so the customer received neither.

## Scoped changes
- `auto_reply_service.py`: retry the already shop-validated original VietQR URL only after a definite photo-URL rejection. If both photo sources are explicitly rejected, send payment instructions with QR link and mark the result `qr_delivery=link_only`. Timeouts and other failures are not blindly resent.
- `api/conversations.py`: support HEAD for public uploaded media. Previously GET returned an image but HEAD returned 405. Public HEAD now returns 200 image/jpeg. No authentication gate has been removed.
- Backups of both changed source files were saved under backups before editing. Existing unrelated edits were preserved.

## Evidence
- 103 channel/adapter/regression tests passed; 5 HEAD and QR fallback tests passed after the route change.
- Backend and worker healthy; backend /health 200.
- User explicitly authorized resending CHAT-9 to their Zalo conversation.
- LIVE PASS: payment instructions plus QR link accepted by Zalo with a provider message ID. Recovery key prevents duplicate resends.
- LIVE FAIL: direct inline QR photo remains rejected, including after fixing HEAD. Do not claim this fixed image delivery.
- Public ngrok image gives JPEG to non-browser clients but HTML warning to a fresh Mozilla client. Original VietQR endpoint currently gives SVG despite the .png path. These are remaining image-delivery compatibility constraints; another image host has not been introduced without user direction.
- No new order, payment or stock change. No key, token or shop banking configuration changed.

## Remaining work
Provide a stable publicly reachable raster-image origin accepted by the Zalo photo fetcher, then retest one QR image. Until then, the verified fallback delivers the instructions and QR link. The local generation/validation path remains in use.

An earlier worker `Tenant is not active` log was also observed; this is not the verified cause of the two QR failures and no unrelated worker security gate was changed.

## Additional image-origin investigation
- Confirmed all tested VietQR URL variants returned SVG despite raster-style extensions; did not switch the automatic sender to any unverified variant.
- Tried an isolated, loopback-only QR-file server with a Cloudflare Quick Tunnel. Official cloudflared Windows binary had a valid Cloudflare signature. Quick Tunnel provisioning failed with HTTP 429, so no application integration or startup-script change was applied. Stopped the trial server and removed its script.
- A candidate image proxy returned HTTP 403; it was not integrated.
- Inline image delivery remains unresolved. Requested user-provided stable HTTPS media hosting or Cloudinary configuration. Do not claim that QR image delivery is fixed.

## Comparison with successful historical QR sends
- Shop 7 has multiple Zalo outbound image messages marked sent, with provider IDs and 800x800 RGB JPEGs, on the previous ngrok-free.app tunnels. This disproves any claim that this application never supported Zalo QR photos.
- Same historical image file is available through the current domain with non-browser GET, 200 image/jpeg.
- Reproduced current fetch behavior with the image fetcher User-Agent and Accept from ngrok inspection: HEAD returns 200 image/jpeg and the correct byte length; GET returns 200 text/html (2918-byte ngrok warning), rather than JPEG.
- Thus HEAD support is necessary compatibility work but does not solve the current GET warning. No further source or configuration changes in this diagnostic pass. Inline QR remains unresolved; a public raster origin without the interstitial or a provider-supported way to set fetch headers is required.

## Inline QR delivery resolved with separate QR-only HTTPS origin
- A subsequent Cloudflare Quick Tunnel provision succeeded. Verified GET with a fresh browser User-Agent returns 200 image/jpeg and decodes as 800x800 RGB JPEG.
- LIVE PASS: resent authorized CHAT-9 QR image to shop 8 conversation 28. Zalo returned a provider message ID; persisted outbound record is `sent`, media_type `image`. No new order or payment was created. Visual receipt in the Zalo app has not been independently inspected.
- `_public_payment_qr` now reads a local runtime origin file, allows only credential-free HTTPS trycloudflare hostnames, copies shop-validated QR JPEGs to a dedicated QR directory, and retains existing fallback behavior.
- `scripts/qr_media_server.py`: loopback-only, generated hash-named JPEGs and health only; no listings/application routes. Public root, /api/conversations and /.env all verified 404.
- `KHOI_DONG_QR.ps1`: verifies the official cloudflared executable signature, detects running server/tunnel, probes HTTPS health, publishes the runtime origin atomically, reports failures. Does not change .env, main ngrok domain or webhooks.
- `KHOI_DONG_SMH.bat` invokes QR startup and clearly warns if QR startup is unavailable, without blocking other services.
- 94 related backend tests passed, including runtime-origin allowlist and existing channel/QR regressions. Repeated launcher invocation reused the existing QR path. Backend/worker restarted; automatic QR publishing verified again after restart.
- Limitation: Quick Tunnel is temporary development infrastructure with no uptime guarantee. URL changes on tunnel recreation; launcher updates it. Production should use a stable media origin. Cloudinary setup is no longer required for this local demo fix.
