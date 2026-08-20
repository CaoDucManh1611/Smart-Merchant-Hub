"""Generate the deterministic demo knowledge base used by local and Docker runs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


CATEGORY_ROWS = """
Điện thoại|2500000|Điện thoại 5G;Điện thoại pin lớn;Điện thoại chụp ảnh|RAM 8GB, bộ nhớ 128GB, pin 5000mAh;RAM 12GB, bộ nhớ 256GB, màn hình AMOLED;hỗ trợ 5G, camera chống rung, sạc nhanh
Laptop|8500000|Laptop văn phòng;Laptop học tập;Laptop đồ họa|RAM 16GB, SSD 512GB, màn hình 14 inch;RAM 16GB, SSD 1TB, màn hình 15.6 inch;RAM 8GB, SSD 512GB, pin dùng cả ngày
Máy tính bảng|3200000|Máy tính bảng học tập;Máy tính bảng giải trí;Máy tính bảng làm việc|màn hình 10.5 inch, bộ nhớ 128GB;màn hình 11 inch, bộ nhớ 256GB;hỗ trợ bút cảm ứng và bàn phím rời
Tai nghe|250000|Tai nghe Bluetooth;Tai nghe chụp tai;Tai nghe chống ồn|Bluetooth 5.3, pin 30 giờ;chống ồn chủ động, micro kép;đệm tai mềm, hỗ trợ kết nối đa thiết bị
Phụ kiện|79000|Sạc nhanh đa cổng;Cáp kết nối bền;Giá đỡ đa năng|chuẩn sạc nhanh, vỏ chống cháy;cáp bọc dù dài 1.5m;thiết kế gập gọn, chống trượt
Thời trang|149000|Áo thun cotton;Áo khoác nhẹ;Quần dáng suông|cotton thoáng khí, size S-XL;vải polyester ít nhăn, size M-XXL;vải co giãn nhẹ, đường may gia cố
Giày dép|229000|Giày chạy bộ;Giày đi bộ;Dép quai ngang|vải lưới thoáng khí, size 36-43;đế cao su chống trượt, size 37-44;da tổng hợp dễ vệ sinh, size 36-42
Túi ví|189000|Túi đeo chéo;Balo nhiều ngăn;Ví cầm tay|vải canvas chống bám bụi;da tổng hợp, nhiều ngăn;polyester chống thấm nhẹ
Mỹ phẩm|99000|Son dưỡng ẩm;Kem nền mỏng nhẹ;Phấn phủ kiềm dầu|dung tích 15ml, kết cấu mỏng nhẹ;dung tích 30ml, thành phần dưỡng ẩm;dung tích 50ml, phù hợp da thường
Chăm sóc cá nhân|89000|Sữa rửa mặt dịu nhẹ;Dầu gội phục hồi;Kem dưỡng ẩm|dung tích 250ml, công thức dịu nhẹ;dung tích 500ml, không chứa paraben;dung tích 100ml, dùng hằng ngày
Gia dụng|119000|Kệ lưu trữ đa năng;Hộp đựng chống ẩm;Bộ vệ sinh gia đình|nhựa PP an toàn, dễ vệ sinh;thép không gỉ, chịu lực tốt;thiết kế mô-đun, lắp ráp nhanh
Nội thất|499000|Bàn làm việc gọn;Ghế tựa công thái học;Tủ kệ lắp ráp|gỗ công nghiệp phủ chống xước;khung thép sơn tĩnh điện;đệm mút đàn hồi, bọc vải thoáng khí
Nhà bếp|159000|Nồi chống dính;Bộ dao nhà bếp;Hộp bảo quản thực phẩm|thép không gỉ dùng cho thực phẩm;lớp chống dính, tay cầm cách nhiệt;nhựa PP không BPA, nắp kín
Thiết bị điện|179000|Ổ cắm chống quá tải;Đèn LED tiết kiệm điện;Quạt tuần hoàn|công suất 20W, tiết kiệm điện;điện áp 220V, bảo vệ quá tải;động cơ vận hành êm, 3 mức điều chỉnh
Văn phòng phẩm|29000|Bộ bút viết;Sổ ghi chép;Khay hồ sơ|bộ 10 món, mực khô nhanh;giấy định lượng 80gsm, 200 trang;nhựa ABS bền, thiết kế xếp chồng
Sách|59000|Sách kỹ năng;Sách kinh doanh;Sách thiếu nhi|bìa mềm, 280 trang;bìa cứng, 320 trang;khổ 14x20cm, in màu
Đồ chơi|99000|Bộ xếp hình;Đồ chơi giáo dục;Mô hình lắp ráp|nhựa ABS bo tròn, từ 6 tuổi;gỗ tự nhiên, từ 3 tuổi;120 chi tiết, kèm hướng dẫn
Mẹ và bé|119000|Bộ chăm sóc em bé;Bình uống nước;Túi đựng đồ cho bé|nhựa không BPA, dễ tiệt trùng;vải cotton mềm, an toàn cho bé;dung tích 350ml, chống rò rỉ
Thể thao|129000|Thảm tập luyện;Bộ dây kháng lực;Bình nước thể thao|cao su đàn hồi, tải lực 15kg;TPE chống trượt, dày 8mm;thép không gỉ, dung tích 750ml
Du lịch|199000|Vali kéo gọn nhẹ;Gối cổ du lịch;Túi phụ kiện hành lý|vỏ ABS chống va đập, khóa số;vải polyester, nhiều ngăn;memory foam, vỏ tháo giặt
Xe đạp|149000|Mũ bảo hiểm xe đạp;Đèn xe đạp;Túi treo khung xe|hợp kim nhôm, chống nước IPX4;nhựa ABS, dây điều chỉnh;vải chống thấm, khóa chắc chắn
Ô tô xe máy|129000|Giá đỡ điện thoại xe;Bơm lốp mini;Bộ vệ sinh nội thất xe|nhựa ABS chịu nhiệt, xoay 360 độ;áp suất tối đa 150 PSI;bộ 5 món, dùng cho nội thất xe
Thú cưng|89000|Thức ăn dinh dưỡng;Đệm nằm thú cưng;Dây dắt điều chỉnh|gói 1kg, bổ sung vitamin;vải mềm, đáy chống trượt;dây nylon chịu lực, dài 1.5m
Đồ ăn thức uống|49000|Hạt dinh dưỡng;Trà trái cây;Bánh ăn nhẹ|khối lượng 250g, hạn dùng 12 tháng;hộp 20 gói, vị thanh nhẹ;khối lượng 500g, bao bì khóa kín
Thiết bị văn phòng|1900000|Máy tính để bàn;Máy in văn phòng;Máy hủy tài liệu|kết nối mạng, hỗ trợ in hai mặt;RAM 16GB, SSD 512GB;công suất 10 tờ, thùng chứa 20 lít
Điện máy|990000|Máy lọc không khí;Máy hút bụi;Nồi chiên không dầu|công suất 1200W, bảo hành 24 tháng;dung tích 5 lít, bảng điều khiển điện tử;bộ lọc nhiều lớp, vận hành êm
Trang sức|159000|Vòng tay tối giản;Dây chuyền thanh lịch;Bông tai nhỏ gọn|bạc 925, thiết kế tối giản;thép không gỉ, khóa chắc chắn;hợp kim mạ sáng, hộp bảo quản
Quà tặng|129000|Hộp quà sinh nhật;Bộ quà cảm ơn;Set quà doanh nghiệp|gồm 3 sản phẩm, hộp giấy cứng;gói sẵn kèm thiệp;tùy chọn in tên theo yêu cầu
Dịch vụ|299000|Gói tư vấn trực tuyến;Gói bảo trì định kỳ;Gói thiết kế theo yêu cầu|thời lượng 60 phút, thực hiện trực tuyến;thời hạn 3 tháng, hỗ trợ định kỳ;bàn giao theo yêu cầu đã xác nhận
Khóa học|399000|Khóa học kỹ năng số;Khóa học bán hàng;Khóa học thiết kế|20 bài học video, học trong 6 tháng;12 buổi trực tuyến, có bài tập;30 giờ nội dung, cấp chứng nhận hoàn thành
""".strip()

COLORS = ("đen", "trắng", "xám", "xanh dương", "xanh lá", "đỏ", "be", "hồng")
NO_COLOR = {"Sách", "Đồ ăn thức uống", "Dịch vụ", "Khóa học"}
ELECTRONICS = {
    "Điện thoại", "Laptop", "Máy tính bảng", "Tai nghe", "Thiết bị điện",
    "Thiết bị văn phòng", "Điện máy",
}
HEAVY = {"Laptop", "Nội thất", "Thiết bị văn phòng", "Điện máy"}
LIGHT = {
    "Điện thoại", "Máy tính bảng", "Tai nghe", "Mỹ phẩm",
    "Chăm sóc cá nhân", "Văn phòng phẩm", "Trang sức",
}
NON_PHYSICAL = {"Dịch vụ", "Khóa học"}

SUPPORT_DOCUMENTS = {
    "policies.md": """# Chính sách bán hàng

- Giá sản phẩm hiển thị bằng VND và có thể thay đổi theo chương trình khuyến mãi.
- Nhân viên xác nhận tồn kho trước khi chốt đơn.
- Sản phẩm lỗi hoặc không đúng mô tả được hỗ trợ đổi trả trong 7 ngày.
- Không tự suy đoán thông tin khi kho tri thức không có dữ liệu phù hợp.
""",
    "shipping.md": """# Vận chuyển

- Giao tiêu chuẩn trong 2-5 ngày làm việc tùy khu vực.
- Phí vận chuyển được tính theo địa chỉ, khối lượng và chương trình hỗ trợ hiện hành.
- Khách có thể kiểm tra tình trạng đơn hàng sau khi đơn được xác nhận.
""",
    "product_guidelines.md": """# Hướng dẫn tư vấn sản phẩm

- Ưu tiên trả lời theo SKU, tên sản phẩm, giá và tồn kho trong kho tri thức.
- Nếu khách chưa cung cấp đủ thông tin, hỏi lại danh mục, ngân sách hoặc nhu cầu sử dụng.
- Không khẳng định còn hàng nếu dữ liệu tồn kho chưa được cập nhật.
""",
    "promotions.md": """# Khuyến mãi

- Mã giảm giá và ưu đãi chỉ áp dụng trong thời gian chương trình còn hiệu lực.
- Điều kiện sử dụng cần được kiểm tra trước khi xác nhận cho khách.
- Không cộng dồn nhiều ưu đãi nếu chính sách chương trình không cho phép.
""",
}


def category_data() -> list[dict[str, object]]:
    result = []
    for row in CATEGORY_ROWS.splitlines():
        category, base_price, names, specifications = row.split("|")
        result.append(
            {
                "category": category,
                "base_price": int(base_price),
                "names": names.split(";"),
                "specifications": specifications.split(";"),
            }
        )
    return result


CATEGORIES = category_data()


def product(index: int) -> dict[str, object]:
    data = CATEGORIES[(index - 1) % len(CATEGORIES)]
    category = str(data["category"])
    names = data["names"]
    specifications = data["specifications"]
    name_type = names[((index - 1) // len(CATEGORIES)) % len(names)]
    color = "" if category in NO_COLOR else COLORS[(index * 3) % len(COLORS)]
    specification = specifications[index % len(specifications)]
    base_price = int(data["base_price"])
    sku = f"SMH-{index:06d}"
    name = (
        f"{name_type} {color} - mẫu {(index % 999) + 1:03d}"
        if color
        else f"{name_type} - mã {(index % 999) + 1:03d}"
    )
    if category in ELECTRONICS:
        warranty = ("12 tháng", "18 tháng", "24 tháng")[index % 3]
    elif category in NON_PHYSICAL:
        warranty = "Theo thời hạn gói"
    else:
        warranty = "Không áp dụng"
    if category in NON_PHYSICAL:
        weight = 0
    elif category in HEAVY:
        weight = 1500 + ((index * 23) % 8501)
    elif category in LIGHT:
        weight = 100 + ((index * 23) % 901)
    else:
        weight = 300 + ((index * 23) % 2701)
    return {
        "sku": sku,
        "name": name,
        "category": category,
        "description": (
            f"{name}; danh mục {category}"
            f"{'; màu ' + color if color else ''}; thông số: {specification}."
        ),
        "price": base_price + ((index * 1379) % (base_price + 500_000)),
        "stock": 5 + ((index * 17) % 196),
        "color": color,
        "specification": specification,
        "weight_gram": weight,
        "warranty": warranty,
        "shipping": "Giao tiêu chuẩn 2-5 ngày, hỗ trợ kiểm tra khi nhận hàng",
        "return_policy": "Đổi trả trong 7 ngày nếu lỗi hoặc không đúng mô tả",
    }


def write_products(output_dir: Path, count: int) -> None:
    fields = (
        "sku", "name", "category", "description", "price", "stock", "color",
        "specification", "weight_gram", "warranty", "shipping", "return_policy",
    )
    with (output_dir / "products.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for index in range(1, count + 1):
            writer.writerow(product(index))


def write_faq(output_dir: Path, count: int) -> None:
    with (output_dir / "faq.md").open("w", encoding="utf-8", newline="\n") as file:
        file.write("# Câu hỏi thường gặp theo sản phẩm\n")
        for index in range(1, count + 1):
            item = product(index)
            question_type = index % 5
            if question_type == 0:
                question = f"{item['sku']} giá bao nhiêu và còn hàng không?"
                answer = (
                    f"{item['name']} có giá {item['price']:,} đồng và tồn kho "
                    f"{item['stock']} sản phẩm."
                )
            elif question_type == 1:
                question = f"{item['name']} được bảo hành bao lâu?"
                answer = f"Thời hạn bảo hành của mã {item['sku']}: {item['warranty']}."
            elif question_type == 2:
                question = f"Thời gian giao hàng của {item['sku']} là bao lâu?"
                answer = "Sản phẩm được giao tiêu chuẩn trong 2-5 ngày tùy khu vực."
            elif question_type == 3:
                question = f"{item['sku']} có được đổi trả không?"
                answer = "Có, hỗ trợ đổi trả trong 7 ngày nếu sản phẩm lỗi hoặc không đúng mô tả."
            else:
                question = f"{item['sku']} có thông số gì?"
                answer = f"{item['name']} có thông số: {item['specification']}."
            file.write(f"## FAQ-{index:05d}\n**Hỏi:** {question}\n**Đáp:** {answer}\n\n")


def generate(output_dir: Path, products: int, faqs: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_products(output_dir, products)
    write_faq(output_dir, faqs)
    for filename, content in SUPPORT_DOCUMENTS.items():
        (output_dir / filename).write_text(content, encoding="utf-8", newline="\n")
    print(f"Generated {products} products and {faqs} FAQs in {output_dir}")


def main() -> None:
    backend_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=backend_dir / "sample_data" / "knowledge_base",
    )
    parser.add_argument("--products", type=int, default=100_000)
    parser.add_argument("--faqs", type=int, default=10_000)
    args = parser.parse_args()
    generate(args.output, args.products, args.faqs)


if __name__ == "__main__":
    main()
