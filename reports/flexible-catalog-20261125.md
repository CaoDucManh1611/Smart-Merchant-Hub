# Flexible catalogue and purchase identity corrections — 2026-11-25

- Reproduced the reported transcript's critical product substitution on the live shop catalogue in read-only mode: the serum purchase resolved to clay mask because accent-folded command `đặt` was treated as a rare product token `đất`.
- Product mention matching now strips a leading purchase command, count and classifier before identity scoring. Does not alter names, prices or stored catalogue data. Added regression preserving a literal product name starting with Đất and genuine purchases of it.
- Basic price requests accept natural filler `là đc/được` instead of falling back to remote interpretation.
- Availability questions asking whether a shop sells a category are answered from current available catalogue entries; a missing category receives a direct catalogue-based absence answer, not an unrelated-task refusal. Generic catalogue questions retain their previous route.
- Exact transcript tests disable remote AI and assert correct serum ID, quantity 3, total 687000 and no order creation before confirmation. Category tests verify both absent and present categories using data rather than hardcoded industry names.
- Broad regression suite: 162 passed. A separate focused run covers the additional literal-soil-name preservation case.
- Live read-only verification now resolves the exact original purchase to Serum dưỡng da ban đêm 30ml (229000) and the natural price request only includes items above 200000.
- Live conversation 30 already had a corrected active serum session when inspected; no historical/session/order/customer data changed and no customer message sent.
