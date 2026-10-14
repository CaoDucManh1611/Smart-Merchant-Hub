from app.services.rfm_segments import RFM_SEGMENT_KEYS, rfm_group, rfm_score


def test_rfm_scores_are_tie_stable_and_reverse_recency():
    assert rfm_score(10, [10, 10, 10]) == 3
    assert rfm_score(5, [5, 10, 20], lower_is_better=True) == 5
    assert rfm_score(20, [5, 10, 20], lower_is_better=True) == 1


def test_rfm_business_labels_are_stable_and_explainable():
    assert rfm_group(5, 5, 5) == "RFM · Giá trị cao"
    assert rfm_group(1, 4, 4) == "RFM · Cần chăm sóc"
    assert rfm_group(3, 4, 2) == "RFM · Trung thành"
    assert rfm_group(3, 3, 3, first_purchase_recent=True) == "RFM · Khách mới"
    assert RFM_SEGMENT_KEYS[rfm_group(0, 0, 0)] == "no_purchase"
