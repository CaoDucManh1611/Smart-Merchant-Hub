"""Shared, explainable RFM labels for CRM and recommendation profiles."""

RFM_RULES_VERSION = "rfm_percentile_v1"

RFM_GROUPS = (
    "RFM · Khách mới",
    "RFM · Chưa mua",
    "RFM · Giá trị cao",
    "RFM · Trung thành",
    "RFM · Tiềm năng",
    "RFM · Cần chăm sóc",
    "RFM · Nguy cơ rời bỏ",
    "RFM · Duy trì",
)

RFM_SEGMENT_KEYS = {
    "RFM · Khách mới": "new_customer",
    "RFM · Chưa mua": "no_purchase",
    "RFM · Giá trị cao": "high_value",
    "RFM · Trung thành": "loyal",
    "RFM · Tiềm năng": "potential",
    "RFM · Cần chăm sóc": "needs_attention",
    "RFM · Nguy cơ rời bỏ": "at_risk",
    "RFM · Duy trì": "regular",
}


def rfm_score(value: float, population: list[float], *, lower_is_better: bool = False) -> int:
    if not population:
        return 1
    if len(population) == 1:
        return 3
    rank = sum(candidate < value for candidate in population)
    rank += (sum(candidate == value for candidate in population) - 1) / 2
    if lower_is_better:
        rank = len(population) - 1 - rank
    return max(1, min(5, 1 + round(4 * rank / (len(population) - 1))))


def rfm_group(recency: int, frequency: int, monetary: float, *, first_purchase_recent: bool = False) -> str:
    if frequency == 0:
        return "RFM · Chưa mua"
    if first_purchase_recent:
        return "RFM · Khách mới"
    if recency >= 4 and frequency >= 4 and monetary >= 4:
        return "RFM · Giá trị cao"
    if recency >= 3 and frequency >= 4:
        return "RFM · Trung thành"
    if recency >= 4 and frequency <= 2:
        return "RFM · Tiềm năng"
    if recency <= 2 and frequency >= 3:
        return "RFM · Cần chăm sóc"
    if recency <= 2 and frequency <= 2:
        return "RFM · Nguy cơ rời bỏ"
    return "RFM · Duy trì"
