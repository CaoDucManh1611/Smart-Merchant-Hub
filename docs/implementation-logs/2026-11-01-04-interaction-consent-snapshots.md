# 04 — Generic interaction, consent, and display snapshots

## Implemented

- Extended tenant interaction rows and the API contract with `object_type`, generic object ID, catalog revision, and model version while preserving product IDs for existing callers.
- Click/cart/purchase/skip/refund style item events are checked against shop ownership and, when tied to a recommendation request, against the exact object IDs served by that request.
- Personal customer IDs, query text, and caller metadata are retained for personalization signals only when the latest shop-scoped consent is explicitly `granted`; otherwise the event is anonymized and personalized feature snapshots are removed.
- Impression records capture object type/ID, position, score, model version, blend version, catalog revision when available, retrieval trace, and only the products/services actually visible in the saved outbound chat message.
- Recommendation responses now tag product objects and carry their catalog revision from the synced canonical product metadata. Every request starts with `baseline_only_v1`; an applied learned model records `normalized_baseline_blend_v1` on the request and each displayed impression.
- Impression snapshots include both the pairwise reranker and LightFM algorithm traces, including blend/model version and training run ID.
- Revoking personalization consent or opting out erases learned reranker artifacts for that shop, clears cached LightFM factors, disables the shop model, and requires a fresh consent-filtered train before activation.
- Completed appointments emit idempotent service conversion events. Product purchase/refund events now carry generic object IDs and the recommendation/model/catalog snapshot when attributed.

## Limits / follow-up

- Rental offers can use the generic interaction API, but the application has no canonical rental transaction lifecycle to emit a purchase/refund event automatically.
- Legacy catalog rows have no revision until their products are synchronized; a backfill is still needed after migration.
- The tenant migration has not been applied, so the new interaction columns must be migrated before deploying this code against an existing tenant schema.

## Verification

- Static AST syntax parsing passed for 24 changed source modules and the tenant migration.
- The initial source checkpoint preceded the runtime migration, training attempt, and full suite recorded below. Backfill and sufficient real consented events remain unavailable.
- No commit or push was made.

## Runtime result (2026-11-01)

- Test focused `test_live_reranker_blend.py`: 6 passed. Bao gồm kiểm tra blend-version trên impression và lọc consent/opt-out khi tạo tập train.
- Huấn luyện thực trên DB cho thấy chỉ shop 4 có 11 exposure groups nhưng một khách consent; không đủ ngưỡng 10 khách. Các shop còn lại không có đủ exposure đã consent.
- Không ghi nhận hay dùng dữ liệu mẫu để giả lập kết quả train.

## Kiểm tra cuối

- Full PostgreSQL backend suite: **1,625 passed, 6 skipped, 37 subtests passed**; log `2026-11-01-backend-tests-postgres-final.log`.
- Các kiểm thử bao gồm snapshot blend version trên impression và loại dữ liệu khách đã opt-out khỏi feature train. Dữ liệu thật vẫn chưa đủ để chứng minh hiệu quả cá nhân hóa.
