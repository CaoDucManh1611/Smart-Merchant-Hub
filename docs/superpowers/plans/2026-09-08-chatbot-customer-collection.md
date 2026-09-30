# Chatbot Customer Collection Flow Plan

**Goal:** Connect the customer collection model to inbound chat messages using progressive profiling.

**Scope:** Detect an order-intent message, create one collection session per customer conversation, ask one missing field at a time, persist each answer, and record name, phone, email, and address data with the existing customer collection tables. Order creation and real OTP delivery remain separate follow-up work.

## Tasks

- [x] Add failing unit tests for order-intent detection, field progression, interruption/resume, and persisted contact/address data.
- [x] Implement deterministic extraction and collection-session state transitions.
- [x] Trigger the flow from inbound message processing before RAG auto-reply.
- [x] Add outbound prompt persistence through the existing channel sender.
- [x] Run focused and full backend tests.
