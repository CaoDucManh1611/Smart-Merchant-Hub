"""Quality dashboard must keep platform aggregates out of tenant queries."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quality_dashboard_uses_platform_session_for_plan_and_usage():
    source = (ROOT / "app" / "api" / "reports.py").read_text(encoding="utf-8")
    assert "get_platform_db" in source
    assert "platform_db: Session = Depends(get_platform_db)" in source
    assert "platform_db.query(SaaSUsage)" in source
    assert "platform_db.query(ServicePlan)" in source


def test_agent_performance_reads_staff_identity_from_platform_session():
    source = (ROOT / "app" / "api" / "reports.py").read_text(encoding="utf-8")
    assert "def agent_performance(" in source
    assert "platform_db: Session = Depends(get_platform_db)" in source
    assert "platform_db.query(User)" in source


def test_customer_order_staff_assignment_accepts_platform_session():
    source = (ROOT / "app" / "services" / "customer_order_service.py").read_text(encoding="utf-8")
    assert "platform_db: Session | None = None" in source
    assert "_assignee(platform_db" in source
