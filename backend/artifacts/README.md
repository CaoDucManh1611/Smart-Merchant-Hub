# Recommendation artifacts

The Colab outputs identified in Google Drive are:

- `unsupervised/uci_customer_segmentation.joblib`
- `reinforcement/linucb_bandit_state.joblib`
- `deep_learning/ncf_best.pt`

These three files were trained with public UCI identifiers. They must not be
applied to a real shop until the artifact manifest contains the tenant's
feature schema and product/customer ID mapping. Put the files in the folders
above only for a demo or warm-start experiment, then set:

```env
RECOMMENDATION_ARTIFACT_DIR=artifacts
RECOMMENDATION_ARTIFACT_MODE=demo
```

For production, retrain per tenant and ship a tenant-scoped artifact with a
manifest. The live recommendation path continues to use tenant-safe catalog
filtering, RAG candidates and database feedback until that artifact exists.

`manifest.json` records the imported checkpoint hashes and feature contracts.
The LinUCB policy and NCF model deliberately score only an exact UCI SKU (and,
for NCF, customer-ID) match. Therefore, a normal CRM tenant falls back safely
to the tenant-native recommendation scorer even when demo mode is enabled.
