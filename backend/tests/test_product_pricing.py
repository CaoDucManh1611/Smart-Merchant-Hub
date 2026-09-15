from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import TenantBase
from app.models.sales import Product
from app.services.product_pricing import combo_price_comparison_reply


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TenantBase.metadata.create_all(engine)
    return engine


def test_combo_comparison_uses_current_component_prices_and_returns_savings():
    engine = _engine()
    with Session(engine) as db:
        business_id = 1
        db.add_all([
            Product(
                business_id=business_id,
                sku="CLEANSER-01",
                name="Sữa rửa mặt dịu nhẹ",
                price=Decimal("179000"),
                stock_quantity=18,
                status="active",
            ),
            Product(
                business_id=business_id,
                sku="SERUM-01",
                name="Serum Vitamin C",
                price=Decimal("420000"),
                stock_quantity=10,
                status="active",
            ),
            Product(
                business_id=business_id,
                sku="SUN-01",
                name="Kem chống nắng Daily Shield",
                price=Decimal("289000"),
                stock_quantity=25,
                status="active",
            ),
            Product(
                business_id=business_id,
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
            business_id=business_id,
            text="Nếu mua combo thì sẽ rẻ hơn so với mua lẻ bao nhiêu?",
        )

        assert reply is not None
        assert "888.000" in reply
        assert "799.000" in reply
        assert "89.000" in reply
        assert "10,0%" in reply

        component_reply = combo_price_comparison_reply(
            db,
            business_id=business_id,
            text="Món lẻ trong combo sữa rửa mặt lệch giá bao nhiêu?",
        )
        assert component_reply is not None
        assert "Sữa rửa mặt dịu nhẹ" in component_reply
        assert "89.000" in component_reply

        item_reply = combo_price_comparison_reply(
            db,
            business_id=business_id,
            text="Nếu mua riêng sữa rửa mặt trong combo thì lệch giá bao nhiêu?",
        )
        assert item_reply is not None
        assert "Sữa rửa mặt dịu nhẹ mua lẻ là 179.000 đồng" in item_reply
        assert "phân bổ theo tỷ trọng" in item_reply
        assert "17.940" in item_reply


def test_combo_comparison_returns_a_safe_fallback_when_component_price_is_missing():
    engine = _engine()
    with Session(engine) as db:
        business_id = 2
        db.add(Product(
            business_id=business_id,
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
            business_id=business_id,
            text="Mua lẻ trong combo này thì lệch giá bao nhiêu?",
        )

        assert reply is not None
        assert "chưa đủ" in reply.lower()
        assert "đoán" not in reply.lower()


def test_out_of_stock_combo_returns_grounded_alternative_suggestions():
    engine = _engine()
    with Session(engine) as db:
        business_id = 3
        cleanser = Product(business_id=business_id, sku="ALT-CLEAN", name="Sữa rửa mặt thay thế", price=Decimal("150000"), stock_quantity=5, status="active")
        serum = Product(business_id=business_id, sku="ALT-SERUM", name="Serum thay thế", price=Decimal("250000"), stock_quantity=3, status="active")
        combo = Product(
            business_id=business_id,
            sku="ALT-COMBO",
            name="Combo hết hàng",
            price=Decimal("350000"),
            stock_quantity=0,
            status="active",
            metadata_={"components": [{"product_id": cleanser.id}, {"product_id": serum.id}]},
        )
        db.add_all([cleanser, serum])
        db.flush()
        combo.metadata_ = {"components": [{"product_id": cleanser.id}, {"product_id": serum.id}]}
        db.add(combo)
        db.commit()

        reply = combo_price_comparison_reply(
            db,
            business_id=business_id,
            text="Combo hết hàng rẻ hơn mua lẻ bao nhiêu và có gì thay thế?",
        )
        assert reply is not None
        assert "không đủ tồn kho" in reply
        assert "Gợi ý thay thế" in reply
        # The individual components are the grounded replacement path.
        assert "Sữa rửa mặt thay thế" in reply
        assert "Serum thay thế" in reply
