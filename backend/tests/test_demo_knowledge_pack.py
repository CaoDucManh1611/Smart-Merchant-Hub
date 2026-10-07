import csv
import json
from pathlib import Path


PACK = Path(__file__).resolve().parents[2] / "knowledge_base"


def test_demo_catalog_is_labeled_synthetic_and_has_unique_placeholder_links():
    with (PACK / "demo-products.vi-en.csv").open(encoding="utf-8", newline="") as source:
        products = list(csv.DictReader(source))

    assert len(products) >= 80
    assert len({product["sku"] for product in products}) == len(products)
    assert len({product["product_url"] for product in products}) == len(products)
    assert {product["source_label"] for product in products} == {"demo_synthetic"}
    assert all(product["product_url"].startswith("https://example.com/demo/") for product in products)
    assert any(product["color"] == "hồng" and int(product["demo_stock"]) > 0 for product in products)
    assert any(product["color"] == "hồng" and int(product["demo_stock"]) == 0 for product in products)
    assert {product["industry"] for product in products} >= {
        "fashion", "beauty", "electronics", "home", "food", "pet", "stationery", "services"
    }


def test_demo_rag_cases_cover_bilingual_industries_and_safe_handoff():
    cases = [
        json.loads(line)
        for line in (PACK / "demo-rag-evaluation.vi-en.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 40
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["language"] for case in cases} == {"vi", "en"}
    assert any("allergen" in case["id"] and case["must_not_include"] for case in cases)
    assert any("police" in case["id"] for case in cases)
    assert "synthetic" in (PACK / "README.md").read_text(encoding="utf-8").lower()
    assert all(case.get("query") and case.get("expected_sources") for case in cases)
    assert all(isinstance(case.get("must_include"), list) and isinstance(case.get("must_not_include"), list) for case in cases)


def test_demo_upload_documents_cover_policy_and_safe_retrieval_at_useful_depth():
    profile = (PACK / "demo-store-profile.vi-en.md").read_text(encoding="utf-8")
    policy = (PACK / "demo-support-policies.vi-en.md").read_text(encoding="utf-8")
    playbook = (PACK / "demo-industry-playbook.vi-en.md").read_text(encoding="utf-8")

    assert len(profile) >= 5000
    assert len(policy) >= 7000
    assert len(playbook) >= 7000
    assert all(term in policy.lower() for term in ("delivery", "payment", "wholesale", "refund", "privacy"))
    assert all(term in playbook.lower() for term in ("recency", "frequency", "monetary", "handoff", "preference"))
