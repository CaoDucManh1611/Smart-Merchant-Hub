export function customerInsightView(recommendation, interactions, products = []) {
  const segment = String(recommendation?.segment || "").trim();
  const totalEvents = Math.max(0, Number(interactions?.total_events) || 0);
  const productNames = new Map(products.map((product) => [Number(product.id), product.name]));
  const interests = (Array.isArray(interactions?.top_product_ids) ? interactions.top_product_ids : [])
    .map((id) => ({
      id: Number(id),
      name: productNames.get(Number(id)) || "",
      known: productNames.has(Number(id)),
    }))
    .filter((item) => Number.isFinite(item.id) && item.id > 0);

  return {
    segment,
    segmentKnown: Boolean(segment),
    totalEvents,
    interestsKnown: totalEvents > 0,
    interests,
    recommendations: (Array.isArray(recommendation?.items) ? recommendation.items : []).map((item) => ({
      productId: Number(item.product_id),
      name: String(item.name || "").trim(),
      reason: String(item.reason || "").trim(),
      score: Number(item.score),
    })),
  };
}