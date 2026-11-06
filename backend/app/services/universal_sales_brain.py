"""Tenant-scoped industry playbooks and deterministic needs discovery.

This module contains configuration and extraction contracts only. It does not
read or write a database, call a model, or treat customer text as shop config.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


PLAYBOOK_VERSION = "universal-sales-v1"


class SlotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    question: str
    applies_to: tuple[str, ...] = ("recommendation",)
    trigger_any: tuple[str, ...] = ()
    priority: int = 100


class VerticalPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    industry_id: str
    industry_name: str
    trigger_terms: tuple[str, ...] = ()
    required_customer_information: tuple[SlotSpec, ...] = ()
    discovery_questions: tuple[str, ...] = ()
    selection_criteria: tuple[str, ...] = ()
    recommendation_rules: tuple[str, ...] = ()
    prohibited_assumptions: tuple[str, ...] = ()
    handoff_conditions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("catalog_lookup", "knowledge_lookup")
    available_workflows: tuple[str, ...] = ("product_inquiry", "human_handoff")
    business_type: str = "mixed"
    playbook_version: str = PLAYBOOK_VERSION


class IndustryProfile(BaseModel):
    """Resolved, read-only profile for one configured vertical."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    industry_id: str
    industry_name: str
    business_type: str
    capabilities: tuple[str, ...]
    available_workflows: tuple[str, ...]
    required_customer_information: tuple[SlotSpec, ...]
    guardrails: tuple[str, ...]
    playbook_version: str


class TenantIndustryConfig(BaseModel):
    """Trusted configuration supplied by the tenant configuration layer."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    business_id: int = Field(gt=0)
    industry_ids: tuple[str, ...] = Field(min_length=1, max_length=14)
    config_version: str = "1"

    @field_validator("industry_ids")
    @classmethod
    def unique_industries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("industry_ids_must_be_unique")
        return value


class ResolvedIndustryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    business_id: int | None
    profiles: tuple[IndustryProfile, ...]
    generic_fallback: bool
    configuration_rejected: bool = False
    config_version: str | None = None


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    amount: int = Field(gt=0)
    currency: str = "VND"
    operator: str = "lte"


class NeedsDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: str
    product_service_interest: str | None = None
    budget: Budget | None = None
    purpose: str | None = None
    preferences: dict[str, str] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    required_slots: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    next_best_question: str | None = None
    applicable_playbook_id: str = "generic"


def _fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold().replace("đ", "d"))
    return "".join(char for char in text if not unicodedata.combining(char))


def _slot(name: str, question: str, *, priority: int, trigger: tuple[str, ...] = (),
          applies_to: tuple[str, ...] = ("recommendation",)) -> SlotSpec:
    return SlotSpec(name=name, question=question, priority=priority,
                    trigger_any=trigger, applies_to=applies_to)


# Shared contracts with data-driven vertical differences; there is no per-
# industry routing implementation. Trigger phrases are for selecting among a
# shop's already configured playbooks, never for declaring the shop's industry.
_PLAYBOOK_DATA: tuple[dict[str, Any], ...] = (
    {"id":"fashion_apparel", "name":"Fashion & Apparel", "triggers":("ao", "quan", "vay", "giay", "fashion", "apparel"),
     "slots":(_slot("size", "Bạn thường mặc size nào hoặc muốn mình tư vấn size theo số đo?", priority=10, trigger=("ao", "quan", "vay", "giay", "size")),),
     "criteria":("loại sản phẩm", "size", "phom dáng", "chất liệu", "ngân sách"),
     "prohibitions":("Không tự suy ra size hoặc độ vừa vặn từ chiều cao/cân nặng thiếu dữ liệu bảng size.",),
     "handoff":("Khi khách cần xác nhận size nhưng shop chưa có bảng size đáng tin cậy.",)},
    {"id":"beauty_cosmetics", "name":"Beauty & Cosmetics", "triggers":("my pham", "serum", "kem duong", "chong nang", "skincare", "cosmetic", "makeup"),
     "slots":(_slot("skin_type_or_goal", "Bạn muốn cải thiện vấn đề da nào và da bạn thuộc loại nào?", priority=10, trigger=("serum", "kem duong", "chong nang", "duong da", "skincare", "da mat")),),
     "criteria":("mục đích sử dụng", "loại da nếu liên quan", "thành phần đã biết", "dung tích", "ngân sách"),
     "prohibitions":("Không chẩn đoán bệnh da hoặc cam kết hiệu quả điều trị.", "Không khẳng định an toàn khi thiếu thành phần/hướng dẫn chính thức."),
     "handoff":("Phản ứng nghiêm trọng, dị ứng, hoặc câu hỏi cần chẩn đoán y tế.",)},
    {"id":"electronics", "name":"Electronics", "triggers":("laptop", "dien thoai", "may tinh", "tivi", "tai nghe", "electronics", "thiet bi dien"),
     "slots":(_slot("budget", "Bạn dự kiến ngân sách khoảng bao nhiêu?", priority=10, trigger=("laptop", "dien thoai", "may tinh", "tivi", "thiet bi")),
              _slot("primary_use", "Bạn chủ yếu dùng thiết bị cho công việc hoặc nhu cầu nào?", priority=20, trigger=("laptop", "dien thoai", "may tinh", "tivi", "thiet bi"))),
     "criteria":("ngân sách", "mục đích dùng", "thông số được catalog xác nhận", "bảo hành có nguồn"),
     "prohibitions":("Không tự bịa thông số, bảo hành, tương thích hoặc tình trạng tồn.",),
     "handoff":("Yêu cầu sửa chữa/bảo hành cần chẩn đoán hoặc chính sách chưa có nguồn.",)},
    {"id":"automotive_motorbike", "name":"Automotive & Motorbike", "triggers":("xe may", "xe hoi", "wave", "vision", "sirius", "lop", "nhot", "bugi", "automotive", "motorbike"),
     "slots":(_slot("vehicle_model", "Bạn cho mình xin hãng, dòng xe và đời xe để đối chiếu đúng loại?", priority=10, trigger=("lap vua", "phu hop", "tuong thich", "dung cho xe", "xe toi", "xe minh")),),
     "criteria":("hãng/dòng/đời xe", "mã phụ tùng", "kích thước và thông số", "an toàn lắp đặt"),
     "prohibitions":("Không khẳng định lắp vừa chỉ dựa trên tên dòng xe nếu thiếu đời xe/thông số.",),
     "handoff":("Tương thích an toàn chưa được xác minh hoặc cần thợ kiểm tra thực tế.",)},
    {"id":"furniture_home_living", "name":"Furniture & Home Living", "triggers":("noi that", "ban ghe", "giuong", "tu quan ao", "phong khach", "home living", "furniture"),
     "slots":(_slot("space_or_dimensions", "Bạn định đặt ở không gian nào và kích thước tối đa khoảng bao nhiêu?", priority=10, trigger=("ban", "ghe", "giuong", "tu", "sofa", "ke")),),
     "criteria":("kích thước", "không gian sử dụng", "vật liệu có nguồn", "lắp đặt và vận chuyển"),
     "prohibitions":("Không đoán kích thước thực tế, vật liệu hoặc khả năng chịu tải.",),
     "handoff":("Kích thước/lắp đặt/vận chuyển cần khảo sát hoặc xác nhận riêng.",)},
    {"id":"food_beverage", "name":"Food & Beverage", "triggers":("do an", "thuc an", "do uong", "mon an", "ca phe", "food", "beverage", "restaurant"),
     "slots":(_slot("dietary_constraints", "Bạn có dị ứng hoặc cần tránh nguyên liệu nào không?", priority=10, trigger=("mon", "do an", "thuc an", "do uong", "food", "beverage")),),
     "criteria":("món/đồ uống", "khẩu phần", "dị ứng và chế độ ăn", "thời gian nhận hàng"),
     "prohibitions":("Không khẳng định không gây dị ứng nếu chưa có dữ liệu thành phần và quy trình.",),
     "handoff":("Dị ứng nghiêm trọng hoặc thông tin thành phần chưa xác minh.",)},
    {"id":"real_estate", "name":"Real Estate", "triggers":("bat dong san", "nha dat", "can ho", "mat bang", "property", "real estate"),
     "slots":(_slot("location", "Bạn đang tìm ở khu vực nào?", priority=10, trigger=("nha", "can ho", "dat", "mat bang", "property")),
              _slot("budget", "Ngân sách dự kiến của bạn khoảng bao nhiêu?", priority=20, trigger=("nha", "can ho", "dat", "mat bang", "property"))),
     "criteria":("khu vực", "ngân sách", "mục đích", "diện tích và pháp lý được xác minh"),
     "prohibitions":("Không đảm bảo lợi nhuận, pháp lý, quyền sở hữu hoặc tình trạng giao dịch khi chưa có nguồn.",),
     "handoff":("Yêu cầu xác nhận pháp lý, thương lượng hoặc giao dịch.",)},
    {"id":"education", "name":"Education", "triggers":("khoa hoc", "lop hoc", "dao tao", "hoc phi", "education", "training", "course"),
     "slots":(_slot("learning_goal", "Bạn muốn học nội dung gì và đang ở trình độ nào?", priority=10, trigger=("khoa hoc", "lop hoc", "dao tao", "hoc", "course", "training")),),
     "criteria":("mục tiêu học", "trình độ đầu vào", "lịch học", "học phí có nguồn"),
     "prohibitions":("Không cam kết kết quả học tập hoặc chứng chỉ khi không có chính sách xác nhận.",),
     "handoff":("Cần tư vấn lộ trình cá nhân hoặc xác nhận chứng chỉ/đầu ra.",)},
    {"id":"travel_hospitality", "name":"Travel & Hospitality", "triggers":("du lich", "khach san", "tour", "ve may bay", "travel", "hotel", "hospitality"),
     "slots":(_slot("destination_and_dates", "Bạn muốn đi đâu và vào khoảng ngày nào?", priority=10, trigger=("tour", "du lich", "khach san", "hotel", "travel")),),
     "criteria":("điểm đến", "ngày đi", "số khách", "điều kiện hủy và giá hiện hành"),
     "prohibitions":("Không khẳng định còn chỗ, lịch hoặc giá ngoài dữ liệu hiện thời.",),
     "handoff":("Cần xác nhận nhà cung cấp, chỗ trống hoặc điều kiện thay đổi.",)},
    {"id":"healthcare_wellness", "name":"Healthcare & Wellness", "triggers":("suc khoe", "kham benh", "dieu tri", "wellness", "clinic", "y te"),
     "slots":(_slot("care_goal", "Bạn đang cần hỗ trợ dịch vụ chăm sóc nào?", priority=10, trigger=("kham", "dieu tri", "wellness", "clinic", "suc khoe")),),
     "criteria":("dịch vụ được cấp phép", "nhu cầu chăm sóc", "thời gian", "thông tin do cơ sở xác nhận"),
     "prohibitions":("Không chẩn đoán, kê đơn, cam kết điều trị hoặc thay thế chuyên gia y tế.",),
     "handoff":("Triệu chứng cấp cứu, chẩn đoán/điều trị, hoặc yêu cầu chuyên môn y tế.",)},
    {"id":"b2b_wholesale", "name":"B2B & Wholesale", "triggers":("ban si", "gia si", "so luong lon", "doanh nghiep", "wholesale", "b2b"),
     "slots":(_slot("volume", "Bạn dự kiến lấy khoảng số lượng bao nhiêu?", priority=10, trigger=("si", "so luong lon", "doanh nghiep", "wholesale", "b2b")),
              _slot("delivery_location", "Bạn cần giao đến khu vực nào?", priority=20, trigger=("si", "so luong lon", "doanh nghiep", "wholesale", "b2b"))),
     "criteria":("số lượng", "bậc giá có nguồn", "quy cách", "địa điểm và lịch giao"),
     "prohibitions":("Không tự đặt chiết khấu, MOQ, thời hạn công nợ hoặc cam kết giao hàng.",),
     "handoff":("Báo giá số lượng lớn, công nợ hoặc điều khoản thương mại riêng.",)},
    {"id":"services_repair", "name":"Services & Repair", "triggers":("dich vu", "sua chua", "sua xe", "bao tri", "lap dat", "repair", "maintenance", "service"),
     "slots":(_slot("service_scope", "Bạn muốn làm dịch vụ nào hoặc đang gặp vấn đề gì?", priority=10, trigger=("sua", "bao tri", "lap dat", "repair", "maintenance", "service")),),
     "criteria":("phạm vi công việc", "giá và đơn vị tính", "thời lượng", "lịch còn trống"),
     "prohibitions":("Không tự xác nhận lịch, đơn vị giá hoặc kết quả sửa chữa khi thiếu dữ liệu.",),
     "handoff":("Chẩn đoán cần kỹ thuật viên hoặc lịch phải xác nhận thủ công.",)},
    {"id":"rental_business", "name":"Rental Business", "triggers":("cho thue", "thue xe", "thue phong", "thue may", "rental", "rent"),
     "slots":(_slot("rental_period", "Bạn cần thuê từ ngày nào đến ngày nào?", priority=10, trigger=("thue", "rental", "rent")),),
     "criteria":("đối tượng thuê", "khoảng thời gian", "tình trạng còn khả dụng", "điều kiện thuê có nguồn"),
     "prohibitions":("Không tự suy ra tiền cọc, khả dụng, phí phát sinh hoặc điều kiện hợp đồng.",),
     "handoff":("Cần xác nhận lịch trống, tài sản hoặc điều khoản thuê.",)},
    {"id":"professional_services", "name":"Professional Services", "triggers":("tu van", "ke toan", "phap ly", "thiet ke", "professional service", "consulting"),
     "slots":(_slot("desired_outcome", "Bạn muốn đạt kết quả gì từ dịch vụ tư vấn?", priority=10, trigger=("tu van", "ke toan", "phap ly", "thiet ke", "consulting")),),
     "criteria":("mục tiêu", "phạm vi", "chuyên môn được xác nhận", "phí và lịch tư vấn"),
     "prohibitions":("Không đưa kết luận chuyên môn thay chuyên gia hoặc cam kết kết quả.",),
     "handoff":("Ý kiến pháp lý/tài chính/y khoa cần chuyên gia hoặc đánh giá hồ sơ.",)},
)


def _build_playbook(data: dict[str, Any]) -> VerticalPlaybook:
    business_types = {
        "fashion_apparel":"retail", "beauty_cosmetics":"retail", "electronics":"retail",
        "automotive_motorbike":"retail", "furniture_home_living":"retail", "food_beverage":"retail",
        "real_estate":"real_estate", "education":"education", "travel_hospitality":"travel",
        "healthcare_wellness":"healthcare", "b2b_wholesale":"b2b", "services_repair":"services",
        "rental_business":"rental", "professional_services":"professional_services",
    }
    return VerticalPlaybook(
        industry_id=data["id"], industry_name=data["name"], trigger_terms=data["triggers"],
        required_customer_information=data["slots"],
        discovery_questions=tuple(slot.question for slot in data["slots"]),
        selection_criteria=data["criteria"],
        recommendation_rules=("Ưu tiên điều kiện được khách nói rõ; không đoán thuộc tính còn thiếu.",
                              "Giá, tồn kho và trạng thái bán lấy từ catalog hiện hành.",
                              "Chỉ đề xuất đối tượng đúng loại hình; không trộn hàng hóa, dịch vụ và thuê."),
        prohibited_assumptions=data["prohibitions"], handoff_conditions=data["handoff"],
        capabilities=("catalog_lookup", "knowledge_lookup", "customer_context",
                      "recommendations", "human_handoff"),
        available_workflows=("product_inquiry", "order", "booking", "rental", "human_handoff"),
        business_type=business_types[data["id"]],
    )


VERTICAL_PLAYBOOKS: dict[str, VerticalPlaybook] = {
    data["id"]: _build_playbook(data) for data in _PLAYBOOK_DATA
}

GENERIC_PLAYBOOK = VerticalPlaybook(
    industry_id="generic", industry_name="Generic fallback",
    required_customer_information=(
        _slot("product_or_goal", "Bạn đang tìm sản phẩm/dịch vụ nào hoặc muốn giải quyết nhu cầu gì?", priority=10),
    ),
    discovery_questions=("Bạn đang tìm sản phẩm/dịch vụ nào hoặc muốn giải quyết nhu cầu gì?",),
    selection_criteria=("Nhu cầu khách nói rõ", "Điều kiện catalog hiện hành", "Nguồn kiến thức của đúng shop"),
    recommendation_rules=("Không đoán ngành của shop từ một câu hỏi khách hàng.",
                          "Hỏi một thông tin thiết yếu nếu chưa đủ để chọn.",
                          "Giá, tồn kho và trạng thái bán chỉ từ catalog hiện hành."),
    prohibited_assumptions=("Không suy đoán ngành, giá, tồn kho, chính sách hoặc khả năng tương thích.",),
    handoff_conditions=("Thiếu dữ kiện nghiệp vụ quan trọng hoặc cần quyết định của shop.",),
    capabilities=("catalog_lookup", "knowledge_lookup", "human_handoff"),
    available_workflows=("product_inquiry", "order", "booking", "rental", "human_handoff"),
)


def _profile_from_playbook(playbook: VerticalPlaybook) -> IndustryProfile:
    return IndustryProfile(
        industry_id=playbook.industry_id, industry_name=playbook.industry_name,
        business_type=playbook.business_type, capabilities=playbook.capabilities,
        available_workflows=playbook.available_workflows,
        required_customer_information=playbook.required_customer_information,
        guardrails=playbook.prohibited_assumptions + playbook.handoff_conditions,
        playbook_version=playbook.playbook_version,
    )


def resolve_industry_profiles(business_id: int, configuration: TenantIndustryConfig | dict | None = None) -> ResolvedIndustryContext:
    """Resolve only trusted, tenant-bound configuration; mismatch fails closed."""
    if type(business_id) is not int or business_id <= 0:
        return ResolvedIndustryContext(business_id=None, profiles=(_profile_from_playbook(GENERIC_PLAYBOOK),),
                                       generic_fallback=True, configuration_rejected=configuration is not None)
    if configuration is None:
        return ResolvedIndustryContext(business_id=business_id,
            profiles=(_profile_from_playbook(GENERIC_PLAYBOOK),), generic_fallback=True)
    try:
        config = configuration if isinstance(configuration, TenantIndustryConfig) else TenantIndustryConfig.model_validate(configuration)
    except Exception:
        return ResolvedIndustryContext(business_id=business_id,
            profiles=(_profile_from_playbook(GENERIC_PLAYBOOK),), generic_fallback=True,
            configuration_rejected=True)
    if config.business_id != business_id or any(key not in VERTICAL_PLAYBOOKS for key in config.industry_ids):
        return ResolvedIndustryContext(business_id=business_id,
            profiles=(_profile_from_playbook(GENERIC_PLAYBOOK),), generic_fallback=True,
            configuration_rejected=True)
    profiles = tuple(_profile_from_playbook(VERTICAL_PLAYBOOKS[key]) for key in config.industry_ids)
    return ResolvedIndustryContext(business_id=business_id, profiles=profiles,
        generic_fallback=False, config_version=config.config_version)


class IndustryResolver:
    """Small adapter for a trusted tenant-config source; deliberately no DB access."""

    def resolve(self, business_id: int,
                configuration: TenantIndustryConfig | dict | None = None) -> ResolvedIndustryContext:
        return resolve_industry_profiles(business_id, configuration)


_ADVICE_CUES = ("goi y", "tu van", "nen chon", "phu hop", "tim cho", "recommend", "suggest", "which one")
_FOLLOWUP_CUES = ("cai do", "loai do", "loai re hon", "con mau khac", "con loai nao", "what about", "the cheaper", "that one")
_RESET_CUES = ("bat dau lai", "doi chu de", "san pham khac", "chu de khac", "start over", "different product")
_PURPOSE_CUES = ("de ", "dung de ", "phuc vu ", "for ", "nhu cau ")


def _extract_budget(query: str) -> Budget | None:
    folded = _fold(query)
    pattern = re.compile(r"(?<![\w])([0-9]+(?:[.,][0-9]+)?)\s*(trieu|tr|million|m|k|nghin|ngan)?\s*(?:vnd|vnđ|dong|d|đ)?\b", re.I)
    matches = list(pattern.finditer(folded))
    if not matches:
        return None
    # Only use a number in a money/budget phrase; unrelated sizes/years are not budgets.
    chosen = None
    for match in matches:
        start, end = max(0, match.start() - 24), min(len(folded), match.end() + 16)
        neighborhood = folded[start:end]
        suffix = (match.group(2) or "").lower()
        if suffix or any(cue in neighborhood for cue in ("ngan sach", "duoi", "toi da", "khong qua", "tam ", "khoang ", "vnd", "dong")):
            chosen = match
            break
    if chosen is None:
        return None
    raw = chosen.group(1).replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    suffix = (chosen.group(2) or "").lower()
    if suffix in {"trieu", "tr", "million", "m"}:
        amount *= 1_000_000
    elif suffix in {"k", "nghin", "ngan"}:
        amount *= 1_000
    elif "." in raw and len(raw.rsplit(".", 1)[-1]) == 3:
        amount *= 1_000
    value = int(amount)
    if value <= 0 or value > 10**12:
        return None
    prefix = folded[max(0, chosen.start() - 20):chosen.start()]
    operator = "gte" if any(cue in prefix for cue in ("tren ", "toi thieu", "at least")) else "lte"
    return Budget(amount=value, operator=operator)


def _extract_purpose(folded: str) -> str | None:
    for cue in _PURPOSE_CUES:
        index = folded.find(cue)
        if index >= 0:
            value = folded[index + len(cue):]
            value = re.split(r"[?.!,;]|\b(?:va|and)\b", value, maxsplit=1)[0].strip()
            if value and value not in {"toi", "minh", "ban", "me", "you", "myself"}:
                return value[:120]
    return None


def _extract_interest(query: str, folded: str) -> str | None:
    patterns = (
        r"(?:tim|mua|can|muon|goi y|tu van|recommend|suggest)\s+(?:cho minh\s+|giup minh\s+)?(.+)",
        r"(?:dich vu|service)\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, folded)
        if match:
            text = re.split(r"[?.!,;]", match.group(1), maxsplit=1)[0].strip()
            for prefix in ("cho toi ", "cho minh ", "giup toi ", "giup minh ", "toi ", "minh "):
                while text.startswith(prefix):
                    text = text[len(prefix):].strip()
            if text not in {"", "giup", "giup toi", "giup minh", "cho toi", "cho minh", "toi", "minh", "mua gi", "tu van", "goi y"}:
                return text[:120]
    if any(cue in folded for cue in ("laptop", "ao ", "serum", "xe ", "sua chua", "cho thue", "khoa hoc", "nha dat")):
        return folded[:120]
    return None


def _known_slot(name: str, folded: str, budget: Budget | None, purpose: str | None,
                memory: dict[str, Any] | None, is_followup: bool) -> bool:
    if name == "budget":
        return budget is not None or bool(is_followup and isinstance((memory or {}).get("constraints", {}).get("budget"), dict))
    if name == "purpose":
        return purpose is not None or any(term in folded for term in ("hoc tap", "lam viec", "choi game", "di lam", "di hoc", "di du lich"))
    if name == "size":
        return bool(re.search(r"\b(?:size|co)\s*(?:xs|s|m|l|xl|xxl|\d{1,3})\b", folded))
    if name == "skin_type_or_goal":
        return any(term in folded for term in ("da dau", "da kho", "da hon hop", "da nhay cam", "mun", "tham", "chong nang"))
    if name == "vehicle_model":
        return bool(re.search(r"\b(?:wave|vision|sirius|air blade|lead|exciter|vario|winner|sh mode|future|city|vios|everest)\b", folded))
    if name == "primary_use":
        return purpose is not None or any(term in folded for term in ("hoc", "lap trinh", "do hoa", "van phong", "gaming", "choi game", "chup anh"))
    if name == "space_or_dimensions":
        return bool(re.search(r"\b\d+(?:[.,]\d+)?\s*(?:cm|mm|m|met|x)\b", folded)) or any(term in folded for term in ("phong khach", "phong ngu", "ban lam viec"))
    if name == "dietary_constraints":
        return any(term in folded for term in ("di ung", "khong an", "an chay", "khong duong", "khong gluten"))
    if name == "location":
        return bool(re.search(r"\b(?:quan|huyen|tp|thanh pho|ha noi|ho chi minh|da nang|can tho)\b", folded))
    if name == "learning_goal":
        return any(term in folded for term in ("hoc", "trinh do", "beginner", "nang cao", "ielts", "toeic", "lap trinh"))
    if name == "destination_and_dates":
        return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}\b", folded)) and any(term in folded for term in ("du lich", "tour", "khach san", "di "))
    if name == "care_goal":
        return any(term in folded for term in ("kham", "dieu tri", "massage", "thu gian", "vat ly tri lieu"))
    if name == "volume":
        return bool(re.search(r"\b\d+\s*(?:bo|cai|chiec|thung|san pham|units?)\b", folded))
    if name == "delivery_location":
        return _known_slot("location", folded, budget, purpose, memory, is_followup)
    if name == "service_scope":
        return any(term in folded for term in ("sua", "bao tri", "lap dat", "thay ", "repair", "service"))
    if name == "rental_period":
        return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}\b", folded))
    if name == "desired_outcome":
        return purpose is not None or any(term in folded for term in ("hop dong", "thiet ke", "ke khai", "thanh lap", "tu van ve"))
    if name == "product_or_goal":
        return bool(_extract_interest("", folded))
    return False


def _intent(folded: str) -> str:
    if any(cue in folded for cue in ("bao gia", "gia bao nhieu", "how much", "la gi", "thong tin ve")):
        return "information"
    if any(cue in folded for cue in ("dat lich", "dat phong", "book appointment", "book now")):
        return "booking"
    if any(cue in folded for cue in ("so sanh", "khac nhau", "compare")):
        return "compare"
    if any(cue in folded for cue in ("mua luon", "dat hang", "chot don", "buy now", "order now")):
        return "purchase"
    if any(cue in folded for cue in ("dich vu", "sua chua", "bao tri", "thay ", "service", "repair")):
        return "service_recommendation" if any(cue in folded for cue in _ADVICE_CUES) else "service_information"
    if any(cue in folded for cue in _ADVICE_CUES + ("muon mua", "can mua", "tim laptop", "tim san pham", "mua loai nao")):
        return "product_recommendation"
    if len(folded.split()) <= 3 and any(cue in folded for cue in ("xin chao", "chao ban", "hello", "cam on")):
        return "social"
    return "unknown"


def _applicable_playbook(context: ResolvedIndustryContext, folded: str) -> VerticalPlaybook:
    if context.generic_fallback:
        return GENERIC_PLAYBOOK
    if len(context.profiles) == 1:
        return VERTICAL_PLAYBOOKS[context.profiles[0].industry_id]
    configured = [VERTICAL_PLAYBOOKS[profile.industry_id] for profile in context.profiles]
    matches = [playbook for playbook in configured if any(_fold(term) in folded for term in playbook.trigger_terms)]
    return matches[0] if len(matches) == 1 else GENERIC_PLAYBOOK


def discover_needs(query: str, context: ResolvedIndustryContext, *,
                   memory: dict[str, Any] | None = None) -> NeedsDiscovery:
    """Extract explicit needs and at most one essential question without an LLM."""
    folded = _fold(query)
    intent = _intent(folded)
    reset = any(cue in folded for cue in _RESET_CUES)
    followup = not reset and any(cue in folded for cue in _FOLLOWUP_CUES)
    active_memory = memory if followup and isinstance(memory, dict) else {}
    budget = _extract_budget(query)
    if budget is None and isinstance(active_memory.get("constraints", {}).get("budget"), dict):
        try:
            budget = Budget.model_validate(active_memory["constraints"]["budget"])
        except Exception:
            budget = None
    purpose = _extract_purpose(folded)
    interest = _extract_interest(query, folded)
    preferences: dict[str, str] = {}
    pref = re.search(r"(?:uu tien|thich|prefer)\s+([^?.!,;]{2,100})", folded)
    if pref:
        preferences["explicit"] = pref.group(1).strip()
    constraints: dict[str, Any] = {}
    if budget:
        constraints["budget"] = budget.model_dump()
    vehicle = re.search(r"\b(wave(?: alpha)?|vision|sirius(?: fi)?|air blade|lead|exciter|vario|winner)\s*(\d{2,4})?\b", folded)
    if vehicle:
        constraints["vehicle"] = " ".join(part for part in vehicle.groups() if part)
    size = re.search(r"\b(?:size|co)\s*(xs|s|m|l|xl|xxl|\d{1,3})\b", folded)
    if size:
        constraints["size"] = size.group(1)
    purpose = purpose or None

    playbook = _applicable_playbook(context, folded)
    advisory = intent in {"product_recommendation", "service_recommendation", "compare"}
    slot_intent = "recommendation" if intent in {"product_recommendation", "service_recommendation"} else intent
    selected_slots = tuple(slot for slot in playbook.required_customer_information
                           if advisory and slot_intent in slot.applies_to
                           and (not slot.trigger_any or any(_fold(cue) in folded for cue in slot.trigger_any)))
    required = tuple(slot.name for slot in selected_slots)
    missing = tuple(slot.name for slot in selected_slots
                    if not _known_slot(slot.name, folded, budget, purpose, active_memory, followup))
    next_question = None
    if missing:
        chosen = min((slot for slot in selected_slots if slot.name == missing[0]), key=lambda slot: slot.priority)
        next_question = chosen.question
    elif (playbook.industry_id == "generic" and advisory and interest is None
          and not followup):
        required = ("product_or_goal",)
        missing = required
        next_question = GENERIC_PLAYBOOK.required_customer_information[0].question
    evidence_count = sum(value is not None for value in (interest, budget, purpose)) + len(preferences) + len(constraints)
    confidence = min(0.98, 0.35 + evidence_count * 0.12) if folded else 0.0
    return NeedsDiscovery(
        intent=intent, product_service_interest=interest, budget=budget, purpose=purpose,
        preferences=preferences, constraints=constraints, required_slots=required,
        missing_slots=missing, confidence=confidence, next_best_question=next_question,
        applicable_playbook_id=playbook.industry_id,
    )


def sales_brain_context(context: ResolvedIndustryContext, needs: NeedsDiscovery) -> dict[str, Any]:
    """Compact structured context for existing Graph planner and answer model."""
    return {
        "business_id": context.business_id,
        "industry_ids": [profile.industry_id for profile in context.profiles],
        "generic_fallback": context.generic_fallback,
        "configuration_rejected": context.configuration_rejected,
        "playbook_version": PLAYBOOK_VERSION,
        "needs": needs.model_dump(mode="json"),
    }


def playbook_guidance(context: ResolvedIndustryContext, needs: NeedsDiscovery) -> dict[str, Any]:
    """Return non-factual selection/guardrail guidance, never catalog facts."""
    playbook = VERTICAL_PLAYBOOKS.get(needs.applicable_playbook_id, GENERIC_PLAYBOOK)
    return {
        "industry_ids": [profile.industry_id for profile in context.profiles],
        "active_playbook_id": playbook.industry_id,
        "playbook_version": playbook.playbook_version,
        "selection_criteria": list(playbook.selection_criteria),
        "recommendation_rules": list(playbook.recommendation_rules),
        "prohibited_assumptions": list(playbook.prohibited_assumptions),
        "handoff_conditions": list(playbook.handoff_conditions),
        "available_workflows": list(playbook.available_workflows),
        "capabilities": list(playbook.capabilities),
    }
