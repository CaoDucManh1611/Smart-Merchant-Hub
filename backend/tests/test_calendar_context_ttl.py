from datetime import datetime, timedelta, timezone

from app.services.conversation_graph import recent_calendar_subject


NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def test_calendar_context_uses_only_immediately_previous_recent_topic():
    question = "Còn lịch trống lúc 9 giờ không?"
    service = "Shop có dịch vụ thay lốp không?"
    assert recent_calendar_subject([(question, NOW), (service, NOW - timedelta(minutes=5))],
                                   question, now=NOW) == service
    assert recent_calendar_subject([(question, NOW), (service, NOW - timedelta(minutes=31))],
                                   question, now=NOW) is None
    assert recent_calendar_subject([(question, NOW), ("Tôi hỏi sản phẩm khác", NOW)],
                                   question, now=NOW) == "Tôi hỏi sản phẩm khác"
    assert recent_calendar_subject([(question, NOW), (service, None)],
                                   question, now=NOW) is None
