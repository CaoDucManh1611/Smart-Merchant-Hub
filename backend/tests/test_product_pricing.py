from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.sales import Product
from app.services.product_pricing import combo_price_comparison_reply


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    return engine


def test_combo_comparison_uses_current_component_prices_and_returns_savings():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Pricing Shop", slug="pricing-shop")
        db.add(business)
        db.flush()
        db.add_all([
            Product(
                business_id=business.id,
                sku="CLEANSER-01",
                name="Sữa rửa mặt dịu nhẹ",
                price=Decimal("179000"),
                stock_quantity=18,
                status="active",
            ),
            Product(
                business_id=business.id,
                sku="SERUM-01",
                name="Serum Vitamin C",
                price=Decimal("420000"),
                stock_quantity=10,
                status="active",
            ),
            Product(
                business_id=business.id,
                sku="SUN-01",
                name="Kem chống nắng Daily Shield",
                price=Decimal("289000"),
                stock_quantity=25,
                status="active",
            ),
            Product(
                business_id=business.id,
                sku="COMBO-01",
                name="Combo chăm sóc da cơ bản",
                description="gồm Sữa rửa mặt dịu nhẹ, Serum Vitamin C và Kem chống nắng Daily Shield. Giá niêm yết 888.000 đồng; giá combo 799.000 đồng.",
                price=Decimal("799000"),
                stock_quantity=6,
                status="active",
            ),
        ])
        db.commit()

        reply = combo_price_comparison_reply(
            db,
            business_id=business.id,
            text="Nếu mua combo thì sẽ rẻ hơn so với mua lẻ bao nhiêu?",
        )

        assert reply is not None
        assert "888.000" in reply
        assert "799.000" in reply
        assert "89.000" in reply
        assert "10,0%" in reply

        component_reply = combo_price_comparison_reply(
            db,
            business_id=business.id,
            text="Món lẻ trong combo sữa rửa mặt lệch giá bao nhiêu?",
        )
        assert component_reply is not None
        assert "Sữa rửa mặt dịu nhẹ" in component_reply
        assert "89.000" in component_reply


def test_combo_comparison_returns_a_safe_fallback_when_component_price_is_missing():
    engine = _engine()
    with Session(engine) as db:
        business = Business(name="Incomplete Pricing Shop", slug="incomplete-pricing-shop")
        db.add(business)
        db.flush()
        db.add(Product(
            business_id=business.id,
            sku="COMBO-01",
            name="Combo chăm sóc da cơ bản",
            description="gồm Sữa rửa mặt dịu nhẹ và Serum Vitamin C.",
            price=Decimal("799000"),
            stock_quantity=6,
            status="active",
        ))
        db.commit()

        reply = combo_price_comparison_reply(
            db,
            business_id=business.id,
            text="Mua lẻ trong combo này thì lệch giá bao nhiêu?",
        )

        assert reply is not None
        assert "chưa đủ" in reply.lower()
        assert "đoán" not in reply.lower()
