from pathlib import Path


OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "knowledge-base-stress-test-vietnamese.md"

CATEGORIES = [
    ("Thời trang", "áo sơ mi, quần, váy, áo khoác và phụ kiện"),
    ("Mỹ phẩm", "sữa rửa mặt, serum, kem chống nắng và mặt nạ"),
    ("Điện gia dụng", "máy xay, nồi chiên, máy lọc không khí và máy hút bụi"),
    ("Điện tử", "tai nghe, webcam, bàn phím và phụ kiện máy tính"),
    ("Đồ gia dụng", "bình nước, hộp bảo quản, đèn và vật dụng nhà bếp"),
    ("Mẹ và bé", "đồ dùng ăn dặm, khăn, bình sữa và đồ chơi an toàn"),
    ("Thể thao", "thảm tập, dây kháng lực, bình thể thao và túi tập"),
    ("Văn phòng phẩm", "sổ, bút, kẹp tài liệu và bộ dụng cụ học tập"),
    ("Thực phẩm khô", "hạt, trà, cà phê, gia vị và thực phẩm đóng gói"),
    ("Thú cưng", "thức ăn, vòng cổ, đồ chơi và phụ kiện chăm sóc"),
    ("Nội thất nhỏ", "kệ, ghế, bàn gấp và phụ kiện trang trí"),
    ("Du lịch", "vali, túi đeo, bình giữ nhiệt và phụ kiện hành lý"),
]

SCENARIOS = [
    "Khách hỏi giá và muốn biết sản phẩm có đang được giảm giá hay không.",
    "Khách muốn biết hàng còn sẵn không, thời gian chuẩn bị và ngày giao dự kiến.",
    "Khách cần tư vấn sản phẩm phù hợp ngân sách và mục đích sử dụng.",
    "Khách hỏi cách đặt hàng, phương thức thanh toán và cách kiểm tra trạng thái đơn.",
    "Khách nhận hàng rồi muốn đổi màu, đổi kích thước hoặc đổi sang mẫu khác.",
    "Khách báo sản phẩm có dấu hiệu lỗi và cần hướng dẫn bảo hành.",
    "Khách hỏi phí vận chuyển, khu vực giao hàng và thời gian giao ngoài giờ hành chính.",
    "Khách phản hồi chưa nhận được tin nhắn xác nhận và cần nhân viên kiểm tra.",
]

POLICY = """
## Chính sách chung của Demo Knowledge Hub

- Giá trong tài liệu là giá thử nghiệm, đơn vị tiền tệ là đồng Việt Nam và chưa bao gồm phí vận chuyển.
- Shop xác nhận tồn kho trước khi chốt đơn. Tồn kho trên hệ thống có thể thay đổi trong ngày.
- Đơn nội thành thường giao trong 1–2 ngày làm việc; đơn tỉnh thường giao trong 2–5 ngày làm việc.
- Khách được kiểm tra tình trạng kiện hàng khi nhận. Nếu kiện rách, móp hoặc ướt, khách nên chụp ảnh trước khi mở.
- Yêu cầu đổi trả cần có mã đơn, ảnh sản phẩm và mô tả vấn đề. Không hứa hoàn tiền trước khi nhân viên kiểm tra.
- Khi câu hỏi liên quan đến bảo hành, khiếu nại hoặc giao nhầm hàng, trợ lý phải chuyển nhân viên nếu chưa đủ thông tin.
- Trợ lý không được tự đặt giá ngoài tài liệu, tự xác nhận hoàn tiền hoặc yêu cầu khách gửi mật khẩu, mã OTP hay mã thẻ.
- Khi không tìm thấy câu trả lời, trợ lý phải nói rõ chưa có thông tin và tạo yêu cầu cho nhân viên.
""".strip()


def product_entry(number: int, category: tuple[str, str], variant: int) -> str:
    name, catalog = category
    code = f"DH-{number:04d}-{variant:02d}"
    price = 89000 + ((number * 173 + variant * 911) % 38) * 10000
    stock = 4 + ((number * 7 + variant * 13) % 96)
    delivery = 1 + ((number + variant) % 4)
    return f"""
### Sản phẩm {code}: {name} mẫu {variant:02d}

**Mô tả:** Đây là sản phẩm mẫu thuộc nhóm {name.lower()}, dùng cho kiểm thử khả năng tra cứu của trợ lý. Danh mục tham khảo gồm {catalog}. Sản phẩm có thể được tư vấn theo mục đích, ngân sách, màu sắc, kích thước, độ bền và mức độ tiện dụng. Khi khách chưa nêu rõ nhu cầu, hãy hỏi tối đa ba câu làm rõ trước khi đề xuất.

**Thông tin bán hàng:**
- Mã sản phẩm: `{code}`.
- Giá niêm yết tham khảo: **{price:,}đ**.
- Tồn kho mô phỏng: **{stock} sản phẩm**.
- Thời gian chuẩn bị dự kiến: **{delivery} ngày làm việc**.
- Kênh hỗ trợ: website, Facebook, Instagram, Telegram và Zalo.
- Có thể tạo đơn nháp sau khi xác nhận tên khách, số điện thoại, sản phẩm, số lượng và địa chỉ giao.

**Tư vấn:** Khi khách hỏi “có tốt không”, không khẳng định tuyệt đối. Hãy nêu ưu điểm, giới hạn sử dụng và hỏi bối cảnh thực tế. Khi khách hỏi sản phẩm tương tự, có thể đề xuất tối đa ba mã cùng nhóm nhưng phải cho biết giá và điểm khác nhau. Không được suy đoán màu hoặc kích thước còn hàng nếu dữ liệu chưa có.

**Thanh toán và giao nhận:** Shop hỗ trợ thanh toán khi nhận hàng ở khu vực được đơn vị vận chuyển phục vụ, chuyển khoản theo thông tin chính thức của shop và phương thức thanh toán được hiển thị trên đơn. Không yêu cầu khách gửi mã OTP. Phí giao hàng được xác định ở bước chốt địa chỉ; không tự cam kết miễn phí nếu tài liệu không ghi chương trình.

**Đổi trả và bảo hành:** Khách liên hệ trong vòng 7 ngày kể từ lúc nhận nếu sản phẩm lỗi, sai mẫu hoặc thiếu phụ kiện. Sản phẩm cần còn tình trạng phù hợp, có mã đơn và bằng chứng hình ảnh. Thời hạn xử lý dự kiến 2–7 ngày làm việc sau khi shop nhận đủ thông tin. Hàng đã qua sử dụng hoặc hư do bảo quản sai có thể không đủ điều kiện; nhân viên sẽ kiểm tra từng trường hợp.

**Câu hỏi thường gặp:**
1. “Sản phẩm {code} giá bao nhiêu?” Trả lời giá tham khảo {price:,}đ và hỏi khách cần số lượng nào.
2. “Còn hàng không?” Trả lời tồn kho mô phỏng {stock} sản phẩm và nhắc nhân viên cần xác nhận lại trước khi chốt.
3. “Bao lâu nhận được?” Trả lời thời gian chuẩn bị khoảng {delivery} ngày làm việc, sau đó thời gian vận chuyển phụ thuộc địa chỉ.
4. “Nếu nhận lỗi thì sao?” Hướng dẫn khách gửi mã đơn, ảnh/video và mô tả lỗi để nhân viên xử lý đổi trả hoặc bảo hành.

**Tình huống cần chuyển người thật:** khách yêu cầu bồi thường, tranh chấp thanh toán, đơn có dấu hiệu gian lận, giao nhầm nhiều lần, sản phẩm gây ảnh hưởng sức khỏe, hoặc khách yêu cầu thay đổi thông tin nhạy cảm sau khi đơn đã giao cho vận chuyển.

**Mẫu trả lời an toàn:** “Mình đã ghi nhận yêu cầu về sản phẩm {code}. Giá tham khảo hiện là {price:,}đ, nhưng shop sẽ kiểm tra lại tồn kho và phí giao trước khi xác nhận. Bạn cho mình xin khu vực nhận hàng và số lượng cần mua nhé.”
""".strip()


def build_document() -> str:
    sections = [
        "# Kho tri thức kiểm thử RAG – Demo Knowledge Hub\n\n"
        "Tài liệu này hoàn toàn giả lập, dùng để kiểm tra upload, chia đoạn, embedding, tìm kiếm ngữ nghĩa và trả lời có nguồn. Không dùng làm chính sách thật của bất kỳ shop nào.\n\n"
        + POLICY,
        "## Quy trình chăm sóc khách hàng\n\n"
        + "\n\n".join(
            f"### Kịch bản {index:02d}: {scenario}\n\n"
            "Trợ lý cần xác nhận thông tin khách đang hỏi, tìm tài liệu liên quan, trả lời ngắn gọn và ghi nhận bước tiếp theo. "
            "Nếu câu hỏi thiếu mã đơn, mã sản phẩm hoặc thông tin định danh cần thiết, hãy hỏi bổ sung thay vì đoán. "
            "Nếu khách thể hiện bức xúc, xin lỗi về trải nghiệm, tóm tắt vấn đề và chuyển nhân viên khi có nguy cơ tranh chấp."
            for index, scenario in enumerate(SCENARIOS, 1)
        ),
    ]
    number = 1
    for category in CATEGORIES:
        sections.append(f"## Danh mục {category[0]}\n\n{category[1].capitalize()}.\n")
        for variant in range(1, 126):
            sections.append(product_entry(number, category, variant))
            number += 1
    sections.append(
        "## Quy tắc phản hồi cuối tài liệu\n\n"
        "Trợ lý phải ưu tiên thông tin có mã sản phẩm, mã đơn và thời điểm cập nhật rõ ràng. Nếu hai phần tài liệu mâu thuẫn, không tự chọn giá hoặc chính sách; hãy nói dữ liệu cần được nhân viên xác nhận. Mọi câu trả lời về giá, tồn kho, giao hàng, đổi trả và bảo hành phải giữ đúng phạm vi của tài liệu hiện tại."
    )
    return "\n\n---\n\n".join(sections) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = build_document()
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"{OUTPUT} ({len(text.encode('utf-8'))} bytes)")
