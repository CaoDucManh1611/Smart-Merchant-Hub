from pathlib import Path
import re


SERVICE_SOURCE = Path(__file__).parents[1].joinpath("app", "services", "order_service.py").read_text(encoding="utf-8")


def test_sales_transition_does_not_lock_a_collection_join():
    """PostgreSQL rejects FOR UPDATE on the nullable side of a joinedload."""
    transition_source = SERVICE_SOURCE.split("def transition_sales_order(", 1)[-1]
    transition_query = re.search(
        r"order = db\.query\(Order\).*?if order is None:",
        transition_source,
        flags=re.DOTALL,
    )
    assert transition_query is not None
    query_source = transition_query.group(0)
    assert "with_for_update()" in query_source
    assert "joinedload(Order.items)" not in query_source
    assert "db.query(OrderItem)" in SERVICE_SOURCE
