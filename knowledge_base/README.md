# Smart Merchant RAG demo pack

This pack is a **synthetic test shop**, not market research and not a source of real prices, stock, warranties, or legal/industry rules. All product links use `example.com` placeholders. Do not use these sample promises with real customers.

Upload only these four source files to Kho kiến thức to test retrieval and citations:

1. `demo-store-profile.vi-en.md` — shop identity, data boundaries, source precedence, response flow, glossary, and examples.
2. `demo-products.vi-en.csv` — 90 fabricated product rows across fashion, beauty, electronics, home, food, pet, stationery, and services; includes colors, attributes, prices, stock, and placeholder links.
3. `demo-support-policies.vi-en.md` — fictional delivery, payment, wholesale, return/refund, service, privacy, and support rules with bilingual FAQ retrieval cards.
4. `demo-industry-playbook.vi-en.md` — retrieval rules, safe recommendation patterns, RFM definitions, and examples for retail, beauty, electronics, home, food, pet, services, and B2B.

The four documents are intentionally separate so each category can be replaced without re-uploading unrelated policy. Add them one at a time and check the plan's document and chunk quotas; more pages do not automatically mean better retrieval.

Use `demo-rag-evaluation.vi-en.jsonl` (40 bilingual cases) and `rag_test_cases_vi-en.md` as evaluation guides. **Do not upload either evaluation file as a knowledge source.** They contain expected answer constraints, not shop facts. `sales_support_vi-en.md` is a fill-in template for a real shop; do not upload it until every placeholder is replaced and the content is approved.

The expected behavior is more important than exact wording: answer only from the relevant demo source, cite it, ask when a required fact is missing, and hand off when needed. The 40 demo cases are a manual answer-quality checklist; they do not call an LLM during automated tests.

The files are separate so a shop can replace only its own catalogue or policy. For a real shop, replace every demo value with approved shop data before enabling customer-facing auto-reply. Do not upload transaction rows or raw chats as general RAG documents; use structured sales tables for RFM/analytics and keep customer facts tenant-scoped with consent and retention controls.
