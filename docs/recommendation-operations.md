# Recommendation operations

`POST /api/recommendations` serves tenant-owned in-stock products through a fixed order:
source (catalog plus optional RAG candidates), hydration (purchase history and profile), filter
(tenant, active, available stock, recently bought), scorer (item affinity, popularity, RAG relevance),
selector (top K), then the durable request record is written.

The scorer adds a time-decayed customer interaction signal (`view`, `click`,
`cart`, `purchase`, `skip`, `refund`) to co-purchase affinity. It also uses a
small lexical signal from that customer's earlier `ask` and `search` queries.
All candidates are still filtered to the active tenant catalog and available
stock before either signal is evaluated.

The RAG service should pass its candidate product ids and normalized relevance scores in
`rag_candidates`. It must not bypass the availability and tenant filters.

Every rendered item must call `POST /api/recommendations/{request_id}/feedback` with an
idempotency key. Terminal `purchase`, `skip`, and `refund` feedback updates an attached
epsilon-greedy experiment policy once; clicks and carts remain useful audit events without
prematurely fixing the bandit's reward.

## Behavioral event contract

`POST /api/recommendations/interactions` accepts tenant-scoped product events
from the frontend or chatbot. Send a stable `idempotency_key` on every retry.

```json
{
  "customer_id": 42,
  "product_id": 71,
  "event_type": "click",
  "source": "web",
  "idempotency_key": "web:session-123:click-71"
}
```

`ask` and `search` may omit `product_id` and include `query`; the query is
stored only within that tenant and used as a lightweight historical-interest
signal. `GET /api/recommendations/interactions/summary` exposes a tenant-safe
summary for validation dashboards.

The RAG `POST /api/chat` and `/api/chat/stream` requests accept an optional
`customer_id`. When supplied, the question is automatically recorded as an
`ask` event with source `rag`. A completed Sales Order automatically emits one
idempotent `purchase` event per order item. A fully refunded order emits the
matching negative `refund` events.

`POST /api/recommendations/training/segments` queues a tenant-scoped deterministic RFM KMeans
job. The CRM worker executes `recommendations.train_segments` and stores `cluster_N` profiles.
Run it after importing orders and on a scheduled cadence. This profile model is isolated from the
NCF checkpoint: a real tenant NCF artefact is attached only after training on that tenant's product ids.
