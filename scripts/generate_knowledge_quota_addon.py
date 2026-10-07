"""Generate a synthetic RAG pack that fills the remaining Premium quota."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "knowledge-base-stress-test-addon-vietnamese.md"
PRODUCTS_PER_CATEGORY = 38
EXPECTED_CHUNKS = 2307

sys.path.insert(0, str(ROOT / "backend"))
from app.rag.semantic_chunker import chunk_document  # noqa: E402
from generate_knowledge_stress_test import CATEGORIES, product_entry  # noqa: E402

EXTRA_TOPICS = [
    ("Tra cứu đúng SKU", "Luôn đối chiếu mã SKU trước khi trả lời về tên, giá hoặc tồn kho. Nếu khách chỉ mô tả chung, hỏi thêm tên/mẫu hoặc gửi tối đa ba lựa chọn để khách xác nhận."),
    ("Không bịa đường dẫn", "Chỉ gửi đường dẫn có trong dữ liệu sản phẩm đã được shop xác nhận. Mã example.com trong bộ thử là dữ liệu minh họa, không phải website mua hàng thật."),
    ("Kiểm tra số lượng", "Với đơn nhiều sản phẩm, xác nhận riêng mã hàng và số lượng từng dòng. Không cộng gộp các mẫu khác SKU thành một mặt hàng."),
    ("Khách mua sỉ", "Khi khách hỏi giá sỉ, hỏi số lượng và mã sản phẩm trước. Chỉ báo mức giá sỉ nếu tài liệu có nêu rõ; nếu chưa có thì chuyển nhân viên xác nhận."),
    ("Sản phẩm hết hàng", "Nếu tồn kho mô phỏng bằng không hoặc dữ liệu không xác nhận được, không nhận đơn như hàng có sẵn. Có thể đề nghị nhân viên kiểm tra lịch nhập hoặc mẫu thay thế."),
    ("Màu sắc khách thích", "Chỉ ghi nhận màu khách tự nói hoặc chọn. Khi đề xuất, ưu tiên đúng màu được nêu nhưng phải kiểm tra biến thể và tồn kho riêng; không suy ra sở thích từ giới tính hay độ tuổi."),
    ("An toàn mỹ phẩm", "Không chẩn đoán bệnh hoặc cam kết sản phẩm phù hợp với mọi loại da. Hỏi về dị ứng đã biết, đề nghị khách xem thành phần và chuyển chuyên viên khi có phản ứng bất thường."),
    ("An toàn điện gia dụng", "Không hướng dẫn tháo thiết bị đang cắm điện hoặc tự sửa phần điện. Với mùi khét, tia lửa, quá nhiệt hay rò điện, ngừng sử dụng và chuyển nhân viên/bảo hành."),
    ("Thông tin trẻ em", "Với đồ dùng trẻ em, chỉ cung cấp độ tuổi và cảnh báo nếu tài liệu xác nhận. Không tự kết luận đồ chơi, vật liệu hoặc thực phẩm an toàn khi thiếu chứng nhận."),
    ("Bảo vệ thông tin cá nhân", "Chỉ hỏi dữ liệu cần cho yêu cầu hiện tại. Không yêu cầu mật khẩu, mã OTP, số thẻ đầy đủ hoặc ảnh giấy tờ không cần thiết qua hội thoại."),
    ("Kiểm soát đơn nháp", "Đọc lại sản phẩm, số lượng, giá tham khảo, địa chỉ và cách liên hệ trước khi tạo đơn nháp. Chỉ coi đơn là xác nhận khi quy trình của shop ghi nhận trạng thái đó."),
    ("Khiếu nại giao hàng", "Ghi nhận mã đơn, thời điểm nhận, tình trạng kiện hàng và bằng chứng khách chủ động cung cấp. Không kết luận lỗi thuộc khách, shop hay đơn vị vận chuyển trước khi kiểm tra."),
    ("Khách yêu cầu hoàn tiền", "Không xác nhận đã hoàn tiền chỉ vì đã nhận được yêu cầu. Thu thập mã đơn và lý do, sau đó chuyển nhân viên theo chính sách; trạng thái thanh toán cần được kiểm tra trong hệ thống."),
    ("Ngôn ngữ phản hồi", "Trả lời bằng ngôn ngữ khách đang dùng, ngắn gọn và tự nhiên. Nếu chưa đủ dữ liệu, nêu rõ phần nào cần kiểm tra thay vì lặp lại nhiều câu trả lời mẫu."),
]


def build_document() -> str:
    sections = [
        "# Bộ bổ sung kiểm thử quota RAG Premium\n\n"
        "Dữ liệu hoàn toàn giả lập, chỉ dùng để kiểm tra tải tài liệu, chia đoạn, tìm kiếm và quota. "
        "Không dùng giá, tồn kho, chính sách hoặc liên kết trong đây để tư vấn khách thật."
    ]
    number = 1501
    for category_name, category_description in CATEGORIES:
        sections.append(
            f"## Danh mục bổ sung: {category_name}\n\n"
            f"Phạm vi mẫu: {category_description.capitalize()}. "
            "Các SKU bên dưới chỉ phục vụ kiểm thử khả năng tìm đúng mã và so sánh sản phẩm."
        )
        for variant in range(126, 126 + PRODUCTS_PER_CATEGORY):
            sections.append(product_entry(number, (category_name, category_description), variant))
            number += 1
    sections.extend(f"## Hướng dẫn kiểm thử: {title}\n\n{body}" for title, body in EXTRA_TOPICS)
    return "\n\n---\n\n".join(sections) + "\n"


if __name__ == "__main__":
    content = build_document()
    chunks = chunk_document(content, OUTPUT.name)
    if len(chunks) != EXPECTED_CHUNKS:
        raise SystemExit(f"Expected {EXPECTED_CHUNKS} chunks, got {len(chunks)}; file not written.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size:,} bytes, {len(chunks):,} chunks)")
