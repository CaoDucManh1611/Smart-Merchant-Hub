# CRM/RAG UI completion and QA record

Branch: `feat/crm-ui-completion`
Repository: `C:\Users\DUC_STRONG\Smart-Merchant-Hub-full-stack-ready`
Reviewed: 2026-09-30

## Current verification — 2026-09-30

- Frontend: `npm run test` — 191 passed, 0 failed. Production Vite build
  succeeded; its current minified JavaScript bundle is about 681 kB and still
  triggers Vite's chunk-size advisory.
- Browser: the app loaded to its sign-in screen. At 375×812, 768×900 and
  1440×900, the document had no horizontal overflow. The 1440 px console had
  zero errors. No sign-in form was submitted.
- Runtime: frontend, backend, worker, Redis and database containers all
  reported healthy after the verification run.
- This pass did not have an authenticated CRM session. It verifies only the
  sign-in page at these sizes; it does not supersede the earlier authenticated
  CRM screenshots/observations below or prove every latest CRM setting screen
  visually at all breakpoints.
- No new screenshot was saved as a PNG artifact. Existing in-app captures are
  session-only. Live offline and HTTP 403 scenarios were not induced.

## Screen inventory

| Screen | Existing before this work | Gap found / action |
| --- | --- | --- |
| Inbox and Customer 360 | Conversation paging, empty selection state, customer detail panel | Verified Vietnamese/English UI and opened the correct unassigned conversation from the work queue. Customer-authored messages remain unchanged by design. |
| Sales pipeline | Loading and empty states | Added retry and insufficient-permission branches. Live QA found untranslated default stage names; all five now use consistent English labels in summary cards and selectors. |
| Support tickets | Loading, empty, history and SLA summary | Added retry, insufficient-permission and work-queue record focus. Live QA confirmed the empty state and native required-field validation without creating a record. |
| Appointments and services | Existing list and forms | Improved loading, error, permission, empty, keyboard-focus and responsive states; added record focus from the work queue. |
| Quotes, projects and invoices | Existing list and forms | Improved localization, loading, error, permission, empty and responsive states; added quote record focus beyond the first page. |
| Knowledge base | Document loading, empty and RAG-run retry | Distinguished list errors from empty results, added permission feedback, made upload keyboard accessible, and contained the wide table in a horizontal scroller. Added a route to the existing RAG assistant. |
| RAG chat | Request loading and inline responses | Localized request failures, retained Shift+Enter for newlines, added return navigation, corrected the English active toggle label, and stacked the layout below 760px. |
| Work queue | Added | Reads existing overdue tickets, unassigned conversations, appointments in the next seven days, sent quotes, and failed document processing. Each record opens its handling screen. Per-group loading, empty, error and permission states are present. |

## Live browser QA

Date: 2026-09-28–2026-09-29
Runtime: `http://127.0.0.1:5173/`, authenticated local shop; screenshot viewport observed at approximately 829 × 921 pixels. Journeys were read-only except submitting the empty support-ticket form, which native required-field validation blocked before any request.

- Inbox: Vietnamese and English chrome loaded; existing conversations were visible. Opening an unassigned work-queue item selected that exact conversation. No reply, assignment, or profile edit was submitted.
- Sales pipeline: empty state and form rendered; all default stages changed language consistently (New, Qualified, Proposal sent, Won, Lost), and English currency/date formatting was visible.
- Support tickets: loading resolved to the empty state. Keyboard Tab/Shift+Tab reached the form controls; empty submission focused the required title and showed the browser validation message without creating a ticket.
- Work queue: 0 overdue tickets, 2 unassigned conversations, 0 failed document imports. The first conversation link opened the corresponding inbox record. Appointment and quote sections are omitted because those modules are disabled for the current shop; no placeholder records are shown.
- Knowledge base: 0 documents; empty state, import choices and new assistant entry were visible. No document was uploaded.
- RAG assistant: opened from Knowledge base and returned successfully. English copy and the active ON state were verified. The automatic-reply setting was not toggled and no prompt was sent to the live assistant.
- Screenshots were captured in the browser session for the pipeline, work queue, knowledge base (including the corrected refresh button), RAG assistant and native validation state; the available in-app browser capture displays them in the session but does not save PNG files into the repository.

## Verification and limits

- Frontend unit tests: `npm test` — 180 passed, 0 failed.
- Production build: `npm run build` — passed. Vite still reports a large JavaScript chunk warning (about 665 kB minified).
- The current shop supplied real data only for conversations. Tickets and knowledge documents had valid empty states. Appointments and quotes were not enabled for this shop, so their API-backed groups could not be exercised.
- Live QA covered the available 829 × 921 screenshot viewport, not exact 375, 768 and 1440 px breakpoints. CSS now stacks RAG chat at widths up to 760 px and the work queue grid auto-fits, but those exact widths remain unverified visually. Chrome DevTools was unavailable because Google Chrome is not installed in this environment; do not treat the viewport sweep as passed.
- Network-offline and HTTP 403 states were not forced against the authenticated shop; their localized retry/permission branches were source- and test-reviewed, not live-triggered. Browser console collection was unavailable for the same DevTools limitation.
- Screenshots are session captures, not repository artifacts. No backend files were changed as part of the UI work.

## Work-queue data rules

- Overdue: open/pending tickets whose `sla_due_at` has passed.
- Unassigned: non-closed conversations without `assigned_user_id`.
- Upcoming appointments: non-completed appointments starting within seven days.
- Quotes to follow up: sent quotes awaiting an outcome.
- Failed documents: document status or latest RAG run is `failed`.

The screen reads tenant-scoped existing APIs and does not seed records.

## In-app browser retest after reopening Codex

Date: 2026-09-29

- Codex's in-app browser control is working again. The conversation header reflow fix was visually rechecked at the embedded browser width (~943 px) and the controls fit without the earlier compression.
- Work queue rendered in Vietnamese and English: 0 overdue tickets, 2 unassigned conversations, and 0 failed document imports. The live workspace configuration has appointment services and quotes/projects switched off, so those groups are correctly omitted; the corresponding API-backed modules exist but were not enabled or changed.
- Knowledge Base empty state and RAG assistant navigation were checked. English labels/date formatting appeared localized; the interface language was restored to Vietnamese. No assistant prompt was sent and no business setting was intentionally changed.
- Unexpected state change during inspection: after interacting near the Knowledge Base import controls, the document list changed from empty to one ready DOCX (29 chunks). No file was intentionally selected or submitted by this agent, so the cause is uncertain. The document was left intact; the uploader will not be touched again until the user confirms this is expected.
- The available live view was ~943 × 664 px. Exact 375/768/1440 px checks, offline/403 scenarios, and browser-console review remain outstanding. The in-app screenshot capture does not persist PNG files into the repository.

Updated verdict: **partial, not complete**. Live Work Queue and RAG localization checks resumed; responsive breakpoint coverage and error-state simulations still need a browser viewport/test harness, and the unexpected document state needs user confirmation.

## In-app browser retest after reopening Codex

Date: 2026-09-29

- Codex's in-app browser control is working again. The conversation header reflow fix was visually rechecked at the embedded browser width (~943 px) and the controls fit without the earlier compression.
- Work queue rendered in Vietnamese and English: 0 overdue tickets, 2 unassigned conversations, and 0 failed document imports. The live workspace configuration has appointment services and quotes/projects switched off, so those groups are correctly omitted; the corresponding API-backed modules exist but were not enabled or changed.
- Knowledge Base empty state and RAG assistant navigation were checked. English labels/date formatting appeared localized; the interface language was restored to Vietnamese. No assistant prompt was sent and no business setting was intentionally changed.
- Unexpected state change during inspection: after interacting near the Knowledge Base import controls, the document list changed from empty to one ready DOCX (29 chunks). No file was intentionally selected or submitted by this agent, so the cause is uncertain. The document was left intact; the uploader will not be touched again until the user confirms this is expected.
- The available live view was ~943 × 664 px. Exact 375/768/1440 px checks, offline/403 scenarios, and browser-console review remain outstanding. The in-app screenshot capture does not persist PNG files into the repository.

Updated verdict: **partial, not complete**. Live Work Queue and RAG localization checks resumed; responsive breakpoint coverage and error-state simulations still need a browser viewport/test harness, and the unexpected document state needs user confirmation.

## Verification after machine restart

- Restored Docker Desktop and started the existing Compose project `smart-merchant-hub-runtime`; frontend, backend, database and Redis reported healthy, and the worker was running. Rebuilt only the frontend with `--no-deps`; no backend source or database volume was changed.
- Confirmed `GET /` and `GET /api/onboarding/plans` both return HTTP 200 through `http://127.0.0.1:5173/`. An initial HTTP 500 came from a temporary host-side Vite process whose `/api` proxy could not resolve Docker's `backend` hostname; that process was stopped, and the project URL now reaches the healthy Docker frontend.
- Re-ran `npm test`: 180 passed, 0 failed. Re-ran `npm run build`: passed (31 modules); the existing 664.64 kB minified JS chunk warning remains.
- In an isolated, unauthenticated browser context, checked the login gate at 375 × 812: document and body widths were both 375 px, with no horizontal page overflow. This does **not** verify CRM/RAG screens at mobile, tablet or desktop sizes.
- The prior authenticated browser session did not survive the restart. No credentials were entered or copied by the agent. The app was queued in Codex's right-side browser panel for the user to sign in directly; authenticated post-restart CRM/RAG screenshots and exact 375/768/1440 px checks remain outstanding.
- The browser-control helper could not start after restart (`helper_unknown_error: apply deny-read ACLs`). Existing screenshots remain session-only; no PNG artifact was saved to the repository in this continuation.

## Continuation: conversation layout and locale consistency

Date: 2026-09-29

- Added a compact-width conversation-header layout so customer details and chat actions wrap instead of compressing into the 621–860 px embedded-browser range. Added a regression assertion for that breakpoint. This is a source/test-verified correction; the user's reported broken conversation view still needs a live visual re-check.
- Replaced CRM/RAG date and VND displays that bypassed the shared locale helpers with `formatDateTime`, `formatDate`, and `formatMoney`. Kept the assistant-cost value as a locale-formatted number because that field is not a VND amount.
- `npm test`: 181 passed, 0 failed. `npm run build`: passed; Vite reports the existing large JavaScript chunk warning (663.30 kB minified). `git diff --check`: clean.
- Rebuilt only the Docker frontend using `--no-deps`; `http://127.0.0.1:5173/` returns HTTP 200. Backend, database, and Redis remained healthy; the worker remained running.
- The browser-control helper continues to fail before opening the UI (`helper_unknown_error: apply deny-read ACLs`), despite the user's authorization to operate the right-side browser. Therefore this continuation did not produce new visual screenshots or claim a live conversation-layout pass. The multi-breakpoint CRM/RAG visual sweep and saved PNG artifacts remain outstanding.

## Requested in-app browser retest

Date: 2026-09-29

- Tried to initialize the Codex in-app browser control again. The helper exited before returning the tab state with `windows sandbox failed: helper_unknown_error: apply deny-read ACLs`; no mouse or keyboard action was sent.
- Read-only smoke checks returned HTTP 200 for `/` and `/api/onboarding/plans`.
- Re-ran `npm test`: 181 passed, 0 failed. Re-ran `npm run build`: passed; the 663.30 kB minified JavaScript chunk warning remains.
- Because the embedded-browser helper could not start, authenticated navigation, console/network inspection, breakpoint screenshots, and live error/permission/keyboard scenarios remain **unverified**. HTTP 200 only confirms the app shell and public plans endpoint respond; it is not an end-to-end pass.

## QA continuation: responsive sweep and conversation header

Date: 2026-09-29

- Authenticated browser checks used exact 375 × 812, 768 × 1024, and 1440 × 900 viewports. Work queue, sales pipeline, support tickets, inbox/conversation, Knowledge Base, and RAG assistant had no document-level horizontal overflow at those widths. Knowledge Base tables use their own horizontal scroller on narrow screens.
- Work queue showed 0 overdue tickets, 2 unassigned conversations, and 0 failed document imports. Appointment and quote groups remain omitted because those modules are disabled for the current shop. No records were created or changed.
- Before refreshing the frontend, the conversation action row overflowed its 460 px center column at 1440 px. Added a container-query CSS fix and regression assertion so wrapping follows the chat column width, not only the viewport width.
- Rebuilt and recreated only `crm_chatbot_frontend` in the existing Compose project (`--no-deps`); backend, database, Redis, worker, and their data were left running and untouched. The app returned HTTP 200 and all five services reported healthy.
- Live retest after frontend refresh: at 1440 px, the action row ends at x=1034 inside the chat header ending at x=1052; header height is 181 px and controls wrap below the customer heading. At 375 and 768 px, controls also remain inside the header. No document-level horizontal overflow at any of the three widths.
- Browser console snapshot after the retest showed 0 errors and 0 warnings. Offline and HTTP 403 behavior were not induced in the authenticated app; the frontend has localized handling in source, but these remain unverified as live scenarios.
- Responsive screenshots were captured and displayed in the QA session at all three widths. They are not saved PNG files in the repository; the available in-app capture surface returned images but no file destination.
- `npm test`: 181 passed, 0 failed. `npm run build`: passed; Vite reports the existing 663.30 kB minified JS chunk warning. The earlier attempt to build without elevated access failed on the repo's parent-directory read restriction; the approved build then succeeded.
- No backend source or live shop settings were changed.

Updated verdict: **partial, not complete**. The conversation header fix is live-verified at 375/768/1440 px. Remaining: induce offline/403 states safely and save PNG artifacts to disk.

## Follow-up: conversation and Customer 360 palette

Date: 2026-09-29

- Replaced decorative coral/pink styling across the inbox conversation and Customer 360 with the existing blue/teal design tokens: composer tabs/actions, send and idle voice controls, fallback avatars, profile section headings, contact/history cards, filters, facts/tags/segments, statistics, and scrollbars.
- Kept semantic colors for unread/urgent badges, validation/API errors, destructive merge/remove actions, active recording, and success/pending statuses.
- Rechecked the authenticated app at `http://127.0.0.1:5173/` in the Codex in-app browser. The conversation header remains wrapped; the composer, Customer 360 contact cards, lower profile forms, and statistics render in the blue/teal palette. The screenshot view was 1380 × 668; no customer records or settings were changed.
- `npm test`: 182 passed, 0 failed. `npm run build`: passed; Vite's existing large-JavaScript-chunk warning remains (663.30 kB minified). `git diff --check`: clean.
- Rebuilt/recreated only `crm_chatbot_frontend` with `--no-deps`; backend, database, Redis, and worker remained running and healthy.
- The visual capture was reviewed in-session but is not saved as a PNG artifact in the repository. Offline/403 scenarios also remain unverified.

Updated verdict: **partial, not complete**. The requested palette and conversation wrapping are live; saved screenshot files and safe live network/permission error simulations remain open QA items.

## Channel/RAG reliability continuation

Date: 2026-09-30

- Added Customer 360 contact-permission controls. Recording marketing or
  proactive consent requires an inbound textual customer-message ID; opt-out is
  recorded without inventing evidence. Vietnamese/English labels were checked
  in the in-app browser.
- Added proactive follow-up filters for scheduled, failed, delivery-unknown and
  sent records. Delivery-unknown rows cannot be cancelled/retried from this
  screen and show an explicit instruction to check the provider first.
- Added admin-only customer CSV preview/import/export UI. The preview reports
  create/skip/error counts and the commit button remains disabled while row
  errors exist. The server import is atomic and repeat-safe.
- Console review found an expired bearer token causing repeated 401 polling.
  The shared API client now clears the token, emits one session-expired event,
  stops tenant polling and returns to the sign-in gate. Live reload displayed
  the localized expired-session message instead of continuing requests.
- Exact 375/768/1440 checks for the core CRM screens were completed in the prior
  responsive sweep. The current browser provider did not expose viewport
  override, so the newly added Settings/consent controls were visually checked
  only at the current embedded width. Their layout uses wrapping/native controls
  and the production build succeeds, but exact breakpoint screenshots for these
  new controls remain unclaimed.
- Backend: **682 passed, 5 skipped**. Frontend: **191 passed, 0 failed**.
- Switching the login gate after an expired session now retranslates the
  session notice with the active interface language; the live browser was
  reloaded in Vietnamese and no authenticated polling resumed.
  Production build passes; the existing large JavaScript chunk warning remains.

Verdict: **ship with environment gates**. Mock/fixture flows and local UI are
ready; live Facebook/Instagram callback, token refresh and outbound delivery,
plus a rehearsal on the exact production PostgreSQL major version, remain
required before production release. A synthetic PostgreSQL 17 dump/restore
rehearsal passed in an isolated disposable container. No real provider message
or active-database migration was performed in this work.
