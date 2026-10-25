# CRM 360, recommendation and conversational rollout

## Runtime contract
- PostgreSQL remains the source of record for messages, customer identities, requests, orders, invoices and feedback. No secondary conversation database was introduced.
- Current catalog owns prices and unreserved inventory; current business configuration owns required fields and allowed payment methods. Only ready knowledge documents are retrieved; replacing/disabling documents uses the existing document lifecycle.
- Recent conversation is context, not a source of current prices or proof an action succeeded.
- Recommendation tool calls the existing ranker and adds the current catalog. It does not create orders, appointments, reservations or payments.
- Memory requires shop-level personalization enabled, latest customer grant and no customer opt-out. Expired, future, low-confidence and foreign-tenant facts are excluded. Verified/current fact sources remain explicit; current stated needs override older preferences.
- The structured customer profile tool also exposes current permitted facts, while keeping operational contact lookup bound to the authenticated conversation.

## Learning contract
- Existing recommendation strategy bandit and approved chatbot response-style bandit are connected to the new graph. Policies must already be explicitly active and experiments running. No live tenant was opted into an experiment by this rollout.
- Warmup uses the first declared approved control arm, not alphabetical arm order. Existing minimum outcome thresholds and terminal-event attribution remain in force.
- Message metadata carries recommendation request and bandit decision identifiers, persisted on the durable turn job for delivery retries. Explicit refusal can be attributed only to the preceding sent recommendation and requires a current consent grant.
- Reply-style experiments do not change workflow review/confirmation, permissions, prices or payment reconciliation. No source chunks are discarded based on a style arm.
- K-means clustering requires at least 20 eligible purchasing customers; below this technical minimum, deterministic RFM remains available and metrics report learning_ready=false. This threshold is not proof of predictive quality.
- No automatic LLM weight training/fine-tuning was introduced. Future model promotion still requires offline evaluation, review and rollback criteria.

## Multi-industry operations
Use the existing business-profile configuration for goods/service/rental, per-offering billing units, required fields, payment methods and charge policies. The same guarded workflow collects details, obtains a payment choice, reviews the request, creates a draft, publishes eligible payment instructions, then waits for reconciliation before staff confirmation. Existing explicit COD and manual-bill branches remain configured behaviors.

Knowledge template: frontend/public/templates/tai-lieu-mau-kho-kien-thuc.txt. Fill policy descriptions and suitability/alternatives; update mutable price/stock in CRM and bank details in settings. Do not upload unfilled placeholders as business facts.

## Diagnostics and rollback
Each graph run records source-document ids and content hashes/types, without copying personal facts into logs. Existing runtime revision checks verify backend/worker alignment. Disable the relevant experiment or restore its approved control arm to stop learning selection. CHATBOT_GRAPH_ENABLED remains the existing runtime switch; preserve the legacy path and its tests during rollout.

## Acceptance
See artifacts/context-rollout-model.log and the current verification report. Synthetic tests cover price/stock changes in the same conversation, consent/revocation, tenant boundaries, recommendation trace, cold start, all three business types, payment gates, merge/undo and retry behavior. Real bank transfers and long-running production load are outside these checks.
