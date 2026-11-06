"""Short, general explanations for common commerce and product terms.

This glossary defines terminology only. It must not be used to assert a shop's
product specifications, compatibility, policies, allergen controls, or safety.
"""
from __future__ import annotations

import re

from app.rag.topics import fold_topic_text


_DEFINITIONS = (
    (("size chart", "size guide", "bang size", "bang co"),
     "Bảng size là bảng số đo cho một mẫu cụ thể, dùng để đối chiếu trước khi chọn cỡ. Nên xem số đo của đúng sản phẩm vì bảng không bảo đảm mọi dáng người mặc vừa như nhau.",
     "A size chart lists measurements for a specific style and helps compare sizes before choosing. Check the exact item because the chart cannot guarantee the same fit for everyone."),
    (("fit", "form", "phom", "vua van"),
     "Fit là phom và mức độ ôm hoặc rộng của trang phục. Tên phom không bảo đảm vừa với mọi vóc dáng; hãy đối chiếu số đo sản phẩm.",
     "Fit describes a garment's cut and how close or loose it sits. The name alone cannot guarantee fit, so compare the garment measurements."),
    (("oversized", "oversize", "form rong"),
     "Oversized là kiểu dáng được thiết kế rộng hơn thông thường. Hãy xem số đo áo thay vì tự động tăng thêm một size.",
     "Oversized means the garment is intentionally cut roomy. Check its measurements instead of automatically sizing up."),
    (("inseam", "inside leg", "inner leg length", "dai ong trong", "duong ong trong"),
     "Inseam là chiều dài đường may phía trong ống quần, thường dùng để đối chiếu chiều dài quần.",
     "Inseam is the inner-leg seam measurement, commonly used to compare trouser length."),
    (("shoe upper", "upper shoe", "upper", "than giay", "phan than giay"),
     "Upper là phần thân phía trên của giày, bao quanh và giữ bàn chân; nó khác với đế giày.",
     "The upper is the part of a shoe above the sole that covers and holds the foot."),
    (("rated power", "nominal power", "cong suat dinh muc"),
     "Công suất định mức là mức công suất nhà sản xuất ghi cho thiết bị trong điều kiện quy định. Con số này không tự nó cho biết chính xác tiền điện thực tế.",
     "Rated power is the manufacturer's power specification under stated conditions. It does not by itself determine the actual electricity cost."),
    (("voltage", "dien ap"),
     "Điện áp là thông số nguồn điện thiết bị yêu cầu; cần đối chiếu nhãn thiết bị và nguồn cấp. Chỉ tên sản phẩm chưa đủ để xác nhận tương thích.",
     "Voltage is the electrical supply specification a device requires; compare the device label with the power source. A product name alone cannot confirm compatibility."),
    (("firmware", "phan mem dieu khien", "phan mem thiet bi"),
     "Firmware là phần mềm được lưu trong thiết bị để điều khiển hoạt động của thiết bị. Chỉ cập nhật theo hướng dẫn của nhà sản xuất.",
     "Firmware is software stored on a device that controls its operation. Update it only by following the manufacturer's instructions."),
    (("compatibility", "tuong thich"),
     "Tương thích nghĩa là hai thiết bị hoặc phụ kiện đáp ứng đúng các model và yêu cầu được nêu trong tài liệu. Cần đối chiếu đúng mã/model, không suy ra chỉ từ tên gọi.",
     "Compatibility means the devices or accessories meet the models and requirements stated in the documentation. Check the exact model rather than infer it from a name."),
    (("model number", "device model", "product model", "model", "ma model", "dong may"),
     "Model là mã định danh một mẫu thiết bị, thường dùng để tra cấu hình và phụ kiện phù hợp. Hãy đọc đầy đủ thông tin trên nhãn máy.",
     "A model identifies a device variant and is used to look up its specifications and accessories. Use the full model shown on the label."),
    (("footprint", "space footprint", "dien tich chiem cho", "khoang dat"),
     "Footprint là khoảng không gian món đồ chiếm khi đặt hoặc lắp, thường được ước tính từ kích thước công bố. Nhớ tính thêm khoảng trống lắp đặt nếu hướng dẫn yêu cầu.",
     "Footprint is the space an item occupies when placed or installed, usually based on its stated dimensions. Include installation clearance when the instructions require it."),
    (("load capacity", "weight capacity", "maximum load", "tai trong", "kha nang chiu tai"),
     "Load capacity là tải trọng tối đa nhà sản xuất công bố cho đúng mẫu sản phẩm. Cần xem tài liệu hoặc nhãn của mẫu đó; không suy từ hình dáng hay tên gọi.",
     "Load capacity is the maximum load the manufacturer specifies for that exact product. Check its label or documentation; do not infer it from appearance or name."),
    (("flat pack", "flat-pack", "ready to assemble", "dong goi phang", "lap rap tai nha"),
     "Flat-pack là cách giao hàng khi sản phẩm được đóng gói tháo rời để lắp ráp sau khi nhận. Làm theo hướng dẫn đi kèm sản phẩm.",
     "Flat-pack means the item is shipped disassembled for assembly after delivery. Follow the product's instructions."),
    (("surface finish", "surface treatment", "finish", "hoan thien be mat", "lop hoan thien"),
     "Finish là lớp hoặc cách xử lý bề mặt cuối cùng, ảnh hưởng đến vẻ ngoài và cách vệ sinh. Riêng từ này không xác nhận sản phẩm chống nước.",
     "Finish is the final surface treatment, which affects appearance and care. The term alone does not confirm that an item is water-resistant."),
    (("food contact", "food-contact", "food contact material", "vat lieu tiep xuc thuc pham", "tiep xuc thuc pham"),
     "Food-contact mô tả vật liệu được chỉ định để tiếp xúc với thực phẩm. Với một món cụ thể, cần căn cứ nhãn hoặc hồ sơ của nhà sản xuất để xác nhận.",
     "Food-contact describes material intended to touch food. For a specific item, confirmation must come from its label or manufacturer documentation."),
    (("allergen", "allergens", "di nguyen", "di ung"),
     "Allergen là chất có thể gây phản ứng dị ứng ở một số người. Hãy kiểm tra đầy đủ nhãn và thông tin xử lý thực phẩm của sản phẩm cụ thể.",
     "An allergen is a substance that can trigger an allergic reaction in some people. Check the full label and handling information for the specific product."),
    (("cross contact", "cross-contact", "allergen transfer", "nhiem cheo di nguyen", "nhiem cheo di ung"),
     "Cross-contact là việc dị nguyên vô tình truyền sang thực phẩm khác qua dụng cụ hoặc bề mặt dùng chung. Mức kiểm soát phải được xác nhận theo nhãn hoặc quy trình của cơ sở.",
     "Cross-contact is the unintended transfer of an allergen to another food through shared equipment or surfaces. Controls must be confirmed from the label or facility process."),
    (("net weight", "net quantity", "khoi luong tinh", "trong luong tinh"),
     "Net weight là khối lượng phần hàng bên trong, không tính bao bì. Với sản phẩm cụ thể, lấy số ghi trên nhãn.",
     "Net weight is the weight of the contents, excluding packaging. Use the amount printed on the specific product's label."),
    (("best before", "best-before", "best by", "dung tot nhat truoc", "su dung tot nhat truoc"),
     "Best before là mốc chất lượng do nhà sản xuất ghi trên nhãn. Hãy đọc cùng hướng dẫn bảo quản và các mốc sử dụng khác trên chính sản phẩm.",
     "Best before is a manufacturer-stated quality date. Read it together with the storage instructions and other date markings on the product."),
    (("batch lot", "batch number", "lot number", "batch code", "ma lo", "so lo", "truy xuat lo"),
     "Batch/lot là mã nhận diện một lô sản xuất, hỗ trợ truy xuất khi cần. Mã cụ thể thường được in trên bao bì.",
     "A batch or lot code identifies a production batch and supports traceability. The specific code is usually printed on the package."),
)


def answer_general_industry_question(query: str, *, english: bool = False) -> str | None:
    """Answer only general terminology questions, never shop-specific facts."""
    folded = fold_topic_text(query)
    if re.search(r"\b(?:gia|price|cost|ton kho|con hang|stock|bao hanh|warranty)\b", folded):
        return None
    if re.search(r"\b(?:this product|this device|this model|san pham nay|mau nay|thiet bi nay|ma sku)\b", folded):
        return None
    if re.search(r"\b(?=[a-z0-9_-]*\d)[a-z0-9]+(?:[-_][a-z0-9]+)+\b", folded):
        return None
    if re.search(r"\b(?:da nhay cam|nhay cam|sensitive skin)\b", folded) and re.search(
        r"\b(?:thanh phan|ingredients?|nen tranh|avoid)\b", folded,
    ):
        return (
            "Không có danh sách thành phần cần tránh áp dụng cho tất cả mọi người. Hãy tránh chất bạn từng phản ứng; nếu dễ kích ứng, lưu ý hương liệu mạnh, cồn làm khô hoặc hoạt chất mạnh. Nếu da đỏ, ngứa hay rát rõ, nên hỏi chuyên gia."
            if not english else
            "There is no ingredient-avoidance list that applies to everyone. Avoid ingredients you have reacted to and check the label; seek medical advice for persistent or severe symptoms."
        )

    # These are advice requests, not definitions of a shop's specific products.
    if "da dau" in folded and any(term in folded for term in ("sua rua mat", "cleanser")):
        return (
            "Da dầu thường hợp sữa rửa mặt làm sạch dịu, hỗ trợ giảm nhờn mà không làm da căng khô. Nếu bạn có mụn hoặc lỗ chân lông to, cho mình biết để tư vấn sát hơn."
            if not english else
            "Oily skin generally benefits from a gentle cleanser that helps remove excess oil without leaving the skin tight or dry. If you also have acne or enlarged pores, tell me so I can tailor the advice."
        )
    if "da kho" in folded and any(term in folded for term in ("duong am", "kem duong", "moisturizer")):
        return (
            "Da khô thường cần cấp ẩm và khóa ẩm; có thể xem kem dưỡng hoặc serum có hyaluronic acid, ceramide hay glycerin. Bạn thích dạng gel, lotion hay cream để mình lọc lựa chọn?"
            if not english else
            "Dry skin generally needs moisturizing care; the right choice depends on ingredients and texture. The catalog does not include enough of those details to confirm a specific item."
        )

    if "toner" in folded and "da kho" in folded and any(term in folded for term in ("co nen", "nen dung", "dung khong")):
        return (
            "Da khô có thể dùng toner cấp ẩm dịu nhẹ nếu thấy phù hợp; toner không bắt buộc. Ngưng dùng nếu da bị kích ứng."
            if not english else
            "Dry skin can use a gentle hydrating toner if it suits the skin, but toner is optional. Stop if irritation occurs."
        )
    if "toner" in folded and any(term in folded for term in ("cach dung", "dung toner", "how to use")):
        return (
            "Dùng toner sau bước làm sạch theo hướng dẫn trên nhãn; thoa nhẹ và ngưng nếu da bị kích ứng."
            if not english else
            "Use toner after cleansing according to its label; apply gently and stop if irritation occurs."
        )
    if "da hon hop" in folded and any(term in folded for term in ("kem duong", "duong am", "moisturizer")):
        return (
            "Da hỗn hợp có thể chọn kem dưỡng kết cấu nhẹ; thoa vừa đủ vùng dầu và tăng ở vùng khô nếu cần. Lựa chọn cụ thể còn tùy thành phần và phản ứng của da."
            if not english else
            "Combination skin can try a lightweight moisturizer, using less on oily areas and more on dry areas if needed. The right choice still depends on its formula and your skin's response."
        )
    if "mun dau den" in folded:
        return (
            "Mụn đầu đen thường liên quan đến lỗ chân lông bít tắc; sản phẩm làm sạch hoặc tẩy tế bào chết phù hợp có thể hỗ trợ. Cần xét loại da và độ nhạy; shop chưa có dữ liệu đủ để chốt một mẫu cụ thể."
            if not english else
            "Blackheads are commonly associated with clogged pores; suitable cleansing or exfoliating products may help. Skin type and sensitivity matter, and the shop data does not verify a specific item."
        )
    if "aha" in folded and any(term in folded for term in ("dau nhon", "da dau")):
        return (
            "AHA hỗ trợ làm mịn bề mặt da; da dầu có thể cân nhắc nếu công thức phù hợp. Dùng từ từ theo hướng dẫn, tránh lạm dụng và ngưng nếu da đỏ, khô rát hoặc kích ứng."
            if not english else
            "Oily skin alone is not enough to decide whether AHA is suitable. Follow the product directions and stop if irritation occurs; seek professional advice for active or severe symptoms."
        )
    if "vitamin c" in folded and "serum" in folded and any(
        term in folded for term in ("buoi sang", "buoi toi", "sang hay toi", "morning", "evening")
    ):
        return (
            "Vitamin C thường được dùng buổi sáng, nhưng còn tùy công thức và hướng dẫn sản phẩm. Da nhạy cảm nên bắt đầu từ từ."
            if not english else
            "Vitamin C is often used in the morning, but follow the product's formula and directions. Sensitive skin should start gradually."
        )
    if any(term in folded for term in ("kem chong nang", "sunscreen")) and any(
        term in folded for term in ("may lan", "bao lau", "thoa lai", "reapply", "how often")
    ):
        return (
            "Thoa theo hướng dẫn trên sản phẩm; nên thoa lại khi ở ngoài nắng lâu hoặc sau khi đổ mồ hôi, bơi, rửa hay lau khô."
            if not english else
            "Follow the product directions and reapply after prolonged sun exposure, sweating, swimming, washing, or towel drying."
        )
    if any(term in folded for term in ("sua rua mat", "cleanser", "face wash")) and any(
        term in folded for term in ("2 lan", "may lan", "twice a day", "how often")
    ):
        return (
            "Rửa mặt 2 lần mỗi ngày phù hợp với nhiều người, nhưng hãy điều chỉnh theo độ dầu và cảm giác da. Nếu da khô hoặc kích ứng, giảm tần suất và chọn loại dịu nhẹ."
            if not english else
            "Cleansing twice daily works for many people, but adjust for oiliness and how your skin feels. If it becomes dry or irritated, cleanse less often and use a gentle formula."
        )
    if "retinol" in folded and any(term in folded for term in ("ket hop", "tranh", "combine", "avoid")):
        return (
            "Nếu mới dùng retinol, bắt đầu từ từ theo hướng dẫn. Khi da còn nhạy cảm, tránh dùng cùng lúc quá nhiều hoạt chất mạnh như AHA, BHA hoặc sản phẩm tẩy tế bào chết mạnh."
            if not english else
            "If you are new to retinol, start gradually and follow its directions. While your skin is sensitive, avoid layering several strong actives such as AHA, BHA, or strong exfoliants in the same routine."
        )
    if "serum" in folded and "niacinamide" in folded and any(
        term in folded for term in ("so sanh", "yeu to", "compare", "which factors")
    ):
        return (
            "Khi so sánh serum niacinamide, hãy xem nồng độ, thành phần đi kèm, độ dịu, khả năng dưỡng ẩm và hướng dẫn dùng. Da nhạy cảm nên ưu tiên công thức dịu và thử từ từ."
            if not english else
            "Compare niacinamide concentration, supporting ingredients, gentleness, hydration, and directions. Sensitive skin should favor a gentle formula and introduce it gradually."
        )
    if "serum" in folded and any(term in folded for term in ("da nhay cam", "nhay cam", "sensitive skin")):
        return (
            "Da nhạy cảm nên ưu tiên serum dịu nhẹ, ít hương liệu và không quá nhiều hoạt chất mạnh. Bạn ưu tiên cấp ẩm, làm dịu hay hỗ trợ hàng rào bảo vệ da?"
            if not english else
            "Sensitive skin generally benefits from a gentle serum with little fragrance and fewer strong actives. Is your priority hydration, soothing, or barrier support?"
        )
    if any(term in folded for term in ("sua rua mat", "cleanser", "face wash")) and any(
        term in folded for term in ("da mun", "mun", "acne")
    ):
        return (
            "Da mụn thường nên chọn sữa rửa mặt dịu, làm sạch bã nhờn và bụi bẩn mà không làm da khô căng. Danh mục chưa xác nhận công thức từng mẫu nên mình chưa chốt sản phẩm cụ thể."
            if not english else
            "Acne-prone skin generally needs a gentle cleanser that removes oil and dirt without over-drying. The catalog does not verify each formula, so I cannot name a specific item yet."
        )
    if "kem duong" in folded and "serum" in folded and any(
        term in folded for term in ("vs", "so sanh", "lua chon", "chon gi", "which", "compare")
    ):
        return (
            "Kem dưỡng chủ yếu cấp ẩm và khóa ẩm; serum thường bổ sung hoạt chất cho mục tiêu cụ thể. Nếu cần cấp ẩm, kem dưỡng là nền tảng; serum có thể bổ trợ theo nhu cầu."
            if not english else
            "Moisturizers mainly hydrate and seal in moisture; serums usually target a specific concern with active ingredients. For hydration, start with a moisturizer and add a serum for a specific goal."
        )
    if any(term in folded for term in ("mun", "acne")) and "routine" in folded:
        return (
            "Routine cơ bản thường gồm làm sạch dịu nhẹ, dưỡng ẩm và sản phẩm hỗ trợ kiểm soát dầu hoặc lỗ chân lông tùy tình trạng. Bạn đang gặp mụn đầu đen, mụn ẩn hay mụn viêm?"
            if not english else
            "To suggest a suitable routine, are you dealing with blackheads, clogged pores, or inflamed acne?"
        )

    asks_skin_types = re.search(r"\b(?:bao nhieu loai da|cac loai da|how many skin types|types of skin)\b", folded)
    asks_definition = re.search(
        r"\b(?:la gi|nghia la gi|co tac dung gi|tac dung gi|cong dung la gi|dung de lam gi|"
        r"what is|what are|what does .+ mean|what does .+ do|definition|thuong dung trong truong hop nao)\b",
        folded,
    )
    if asks_skin_types:
        return (
            "Khi tư vấn thường xét da dầu, da khô, da hỗn hợp, da nhạy cảm và tình trạng thiếu nước. Các nhóm có thể chồng lấp; da thiếu nước không nhất thiết là một loại cố định."
            if not english else
            "Common categories are oily, dry, combination, normal, and sensitive. Dehydration can occur with different skin types and is not necessarily a separate type."
        )
    if not asks_definition:
        return None

    for aliases, vietnamese, english_answer in _DEFINITIONS:
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", folded) for alias in aliases):
            return english_answer if english else vietnamese
    if "niacinamide" in folded or "nicotinamide" in folded or "vitamin b3" in folded:
        return (
            "Niacinamide (vitamin B3) thường được dùng để hỗ trợ cân bằng dầu, giữ ẩm và cải thiện vẻ ngoài không đều màu. Tác dụng cụ thể tùy công thức và hướng dẫn của từng sản phẩm."
            if not english else
            "Niacinamide (vitamin B3) is commonly used to support oil balance, hydration, and the appearance of uneven tone. Its specific effect depends on each product's formula and directions."
        )
    return None
