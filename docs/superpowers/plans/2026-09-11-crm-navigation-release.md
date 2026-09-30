# CRM Navigation and Release Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep common CRM work within three actions and provide a release gate for next week's rollout.

**Architecture:** Keep the existing Vue shell and add a global quick-action palette plus context-aware Customer 360 actions. Release readiness is documented and tested through configuration checks and smoke-test scripts; deployment remains user-controlled.

**Tech Stack:** Vue 3/Vite, Node test runner, PowerShell, Docker Compose, Alembic.

**Spec:** `docs/superpowers/specs/2026-09-11-crm-completion-followups-design.md`

## Global Constraints

- Common tasks must be reachable in no more than three deliberate user actions.
- Do not remove existing navigation routes; quick actions are an accelerator.
- Do not execute production deployment or provider calls from tests.
- Release docs must distinguish local demo checks from production-only checks.

---

### Task 1: Add quick-action palette

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/tests/crm-shell.test.mjs`

- [ ] **Step 1: Write failing source tests** for keyboard shortcut, open Customer 360, create ticket, draft order, pause bot, and focus search.
- [ ] **Step 2: Add a compact palette opened by the header action or `Ctrl/Cmd+K`, with actions filtered by current customer/conversation.**
- [ ] **Step 3: Wire each action to existing functions and close the palette after execution.**
- [ ] **Step 4: Add responsive styling and focus-visible keyboard navigation.**
- [ ] **Step 5: Run frontend tests and Vite build.**

### Task 2: Add release gate documentation and smoke checks

**Files:**
- Create: `docs/release-checklist.md`
- Create: `scripts/smoke_check.ps1`
- Modify: `README.md`
- Test: `backend/tests/test_release_configuration.py`

- [ ] **Step 1: Write config tests** for required production secrets, explicit CORS/hosts, HTTPS, rate-limit enablement, and provider key presence.
- [ ] **Step 2: Add a PowerShell smoke script that checks `/health`, `/docs`, frontend HTTP 200, Alembic head, and required environment variables without printing secret values.**
- [ ] **Step 3: Document migration, Docker health, channel smoke tests, AI commerce scenarios, backup, rollback, and secret rotation.**
- [ ] **Step 4: Run the script in local-safe mode and run the config tests.**

### Task 3: Final verification

**Files:**
- No implementation files; inspect all modified files.

- [ ] **Step 1: Run backend tests excluding only the environment-blocked security test if `uvicorn` remains unavailable.**
- [ ] **Step 2: Run all frontend tests and Vite build.**
- [ ] **Step 3: Run `alembic heads`, `git diff --check`, and inspect ignored secret files.**
- [ ] **Step 4: Report uncommitted state and any production-only manual checks.**
