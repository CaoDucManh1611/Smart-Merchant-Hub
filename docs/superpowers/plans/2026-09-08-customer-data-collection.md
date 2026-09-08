# Customer Data Collection Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tenant-scoped customer data collection model that can collect, verify, and audit contact, address, consent, and collection-session data without storing raw OTP values.

**Architecture:** Keep the current `business_id` tenant boundary and existing `Customer`/`CustomerIdentity` records. Add normalized child tables for contacts, addresses, collection sessions, OTP challenges, and consents. Expose these through the existing `/api/customers` router and reuse the current development-compatible write permission and audit services.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, SQLite test database, PostgreSQL production database.

## Global Constraints

- Do not change existing identity or merge behavior in this slice.
- Store only an HMAC/hash of normalized contact values for matching; store encrypted contact values for display and never return the encrypted payload.
- Store only an OTP hash; never persist or return the raw OTP.
- Every read/write must be scoped to the current business.
- Keep provider delivery (SMS/email) behind a queued challenge record; no fake external provider call.

## Tasks

- [x] Add SQLAlchemy models and relationships for customer contacts, addresses, collection sessions, verification challenges, and consents.
- [x] Add Pydantic request/response schemas with masking and status validation.
- [x] Add an Alembic migration with indexes and tenant-safe foreign keys.
- [x] Add customer collection API endpoints for contacts, addresses, sessions, consents, and OTP challenge verification.
- [x] Add audit records for contact/address/consent/challenge mutations.
- [x] Add focused API tests for tenant isolation, contact masking, session lifecycle, consent, and OTP hashing/verification.
- [x] Run the focused tests and the full backend test suite; report any pre-existing failures separately.

## Verification

- `python -m pytest -q tests/test_customer_data_collection_api.py`
- `python -m pytest -q`
- `alembic upgrade head` when a configured database is available.
