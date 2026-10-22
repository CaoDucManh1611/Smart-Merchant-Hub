#!/usr/bin/env python3
"""Create deterministic, explicitly synthetic bilingual sales rows for demos."""

from __future__ import annotations

import argparse
import csv
import gzip
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


CATALOG = (
    ("beauty", "Chăm sóc da", "Skin care", 90_000, 650_000),
    ("clothing", "Thời trang", "Clothing", 120_000, 1_500_000),
    ("home", "Đồ gia dụng", "Home goods", 60_000, 1_200_000),
    ("accessories", "Phụ kiện", "Accessories", 35_000, 900_000),
    ("electronics", "Điện tử", "Electronics", 180_000, 8_000_000),
    ("food", "Thực phẩm", "Food", 20_000, 700_000),
)
COLORS = (
    ("pink", "hồng", "pink"), ("black", "đen", "black"),
    ("white", "trắng", "white"), ("blue", "xanh dương", "blue"),
    ("green", "xanh lá", "green"), ("red", "đỏ", "red"),
    ("beige", "be", "beige"), ("other", "không áp dụng", "not applicable"),
)
CHANNELS = ("Shopee", "TikTok Shop", "Instagram", "Facebook", "Zalo", "Website")
STATUSES = ("completed", "completed", "completed", "cancelled", "returned")
FIELDS = (
    "order_id", "line_id", "order_time_utc", "synthetic_customer_id", "locale",
    "channel", "sku", "category_code", "category_vi", "category_en",
    "product_vi", "product_en", "color_code", "color_vi", "color_en",
    "quantity", "unit_price_vnd", "line_total_vnd", "status", "is_synthetic",
)


def generate(output: Path, rows: int, seed: int) -> None:
    if rows < 1:
        raise ValueError("rows must be positive")
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    open_output = gzip.open if output.suffix.lower() == ".gz" else open
    if output.suffix.lower() == ".gz":
        file = open_output(output, "wt", newline="", encoding="utf-8-sig")
    else:
        file = output.open("w", newline="", encoding="utf-8-sig")
    with file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        for index in range(1, rows + 1):
            category_code, category_vi, category_en, low, high = rng.choice(CATALOG)
            color_code, color_vi, color_en = rng.choice(COLORS)
            customer = rng.randint(1, max(10, rows // 8))
            unit_price = rng.randrange(low // 1000, high // 1000 + 1) * 1000
            quantity = rng.randint(1, 4)
            product_id = rng.randint(1, 80)
            sku = f"SKU-{category_code[:3].upper()}-{product_id:03d}"
            date = now - timedelta(days=rng.randrange(730), minutes=rng.randrange(1440))
            writer.writerow({
                "order_id": f"DEMO-{index:09d}",
                "line_id": f"DEMO-{index:09d}-01",
                "order_time_utc": date.isoformat(),
                "synthetic_customer_id": f"CUST-{customer:08d}",
                "locale": rng.choice(("vi-VN", "en-US")),
                "channel": rng.choice(CHANNELS),
                "sku": sku,
                "category_code": category_code,
                "category_vi": category_vi,
                "category_en": category_en,
                "product_vi": f"Sản phẩm {category_vi} mẫu {product_id:03d}",
                "product_en": f"Demo {category_en} item {product_id:03d}",
                "color_code": color_code,
                "color_vi": color_vi,
                "color_en": color_en,
                "quantity": quantity,
                "unit_price_vnd": unit_price,
                "line_total_vnd": unit_price * quantity,
                "status": rng.choice(STATUSES),
                "is_synthetic": "true",
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1_000_000, help="number of synthetic order lines (default: 1,000,000)")
    parser.add_argument("--seed", type=int, default=20261007, help="random seed for repeatable output")
    parser.add_argument("--output", type=Path, default=Path("build/demo_sales_bilingual_1m.csv"))
    args = parser.parse_args()
    generate(args.output, args.rows, args.seed)
    print(f"Wrote {args.rows:,} synthetic rows to {args.output.resolve()}")
    print("Demo data only: not real sales, customers, or a source of factual RAG answers.")


if __name__ == "__main__":
    main()
