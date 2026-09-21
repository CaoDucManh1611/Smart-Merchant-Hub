"""Generate a structured demo product catalog for the CRM product importer."""

from csv import DictWriter
from pathlib import Path

from generate_knowledge_stress_test import CATEGORIES


OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "products-stress-test.csv"


def rows():
    number = 1
    for category_name, catalog in CATEGORIES:
        for variant in range(1, 126):
            sku = f"DH-{number:04d}-{variant:02d}"
            price = 89000 + ((number * 173 + variant * 911) % 38) * 10000
            stock = 4 + ((number * 7 + variant * 13) % 96)
            yield {
                "Mã sản phẩm": sku,
                "Tên sản phẩm": f"{category_name} mẫu {variant:02d}",
                "Giá": price,
                "Tồn kho": stock,
                "Mô tả": (
                    f"Sản phẩm demo thuộc nhóm {category_name.lower()}; "
                    f"danh mục tham khảo gồm {catalog}."
                ),
                "Danh mục": category_name,
                "Đối tượng phù hợp": "da nhạy cảm, nhu cầu hằng ngày" if category_name == "Mỹ phẩm" else "nhu cầu hằng ngày",
                "Màu": "đen, trắng, xanh nhạt",
                "Kích thước": "S, M, L",
                "Từ khóa": f"{category_name.lower()}, mẫu {variant:02d}, demo",
                "Trạng thái": "Đang bán",
            }
            number += 1


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "Mã sản phẩm", "Tên sản phẩm", "Giá", "Tồn kho", "Mô tả",
        "Danh mục", "Đối tượng phù hợp", "Màu", "Kích thước", "Từ khóa",
        "Trạng thái",
    ]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows())
    print(f"{OUTPUT} ({OUTPUT.stat().st_size} bytes)")
