# Category plus price filtering — 2026-11-25

- Root cause: category-listing shortcuts returned before explicit price constraints were applied. A second parsing gap omitted the ordinary comparison phrase giá hơn.
- Added deterministic data-driven family matching and price filtering before broad group replies. Supports current catalogue families, strict/inclusive comparison operators, and returns an empty result for that family rather than widening to unrelated products.
- Added hơn to explicit comparison parsing; existing longer negated/inclusive phrases retain precedence.
- 17 category/comparison tests and 32 existing catalogue/basic tests passed. Exact three reported queries were also checked read-only against shop 8 catalogue and returned the 125000 cleanser while excluding the 89000 cleanser.
- Backend and worker restarted. No customer messages, orders, products, inventory, secrets or business configuration changed.
