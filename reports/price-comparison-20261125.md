# Explicit price comparison fix — 2026-11-25

- Root cause: a scalar budget was treated as a maximum by the semantic catalogue route; explicit greater-than constraints could fall through the simple budget handler and be inverted.
- Added explicit comparison parsing (> >= < <= ≥ ≤ and supported Vietnamese comparison phrases) using Decimal VND values, with k/nghìn/ngàn/tr/triệu suffixes and threshold tests.
- Simple generic comparison queries now filter current available goods without calling AI. Semantic category/recommendation filters also honor explicit price comparisons rather than unconditionally applying <= budget.
- 44 catalogue/comparison/basic outage tests passed. Boundary cases include 199k/200k/201k and negated comparison phrases. Intersection tested for >200k and <=300k.
- Read-only live catalogue check for the exact user query returned only Serum dưỡng da ban đêm 30ml (229000) and Dầu tẩy trang làm sạch hằng ngày 200ml (239000).
- Backend/worker restarted. No customer message, order, stock, environment or credentials changed.
