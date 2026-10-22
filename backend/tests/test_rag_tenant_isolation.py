import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database.bases import TenantBase

from app.models.business import Business
from app.models.document import Document, DocumentChunk
from app.rag.retriever import _retrieve_lexical, retrieve


class _EmptyResult:
    def fetchall(self):
        return []


class _RecordingSession:
    def __init__(self):
        self.info = {"tenant_schema": "shop_1"}
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), dict(params)))
        return _EmptyResult()


class RagTenantIsolationTests(unittest.TestCase):
    def test_precomputed_query_vector_keeps_tenant_scope_without_provider_calls(self):
        from app.core.config import settings
        db = _RecordingSession()
        diagnostics = {}
        with patch.object(settings, "EMBEDDING_DIMENSION", 3), patch(
            "app.rag.retriever._retrieve_lexical", return_value=[]
        ), patch("app.rag.retriever.embed_query") as provider:
            retrieve("product alpha", db, business_id=73, query_embedding=[0.1, 0.2, 0.3], diagnostics=diagnostics)
        provider.assert_not_called()
        self.assertEqual(73, db.calls[0][1]["business_id"])
        self.assertEqual("hybrid", diagnostics["retrieval_mode"])

    def test_lexical_sql_keeps_business_filter_even_in_schema_bound_session(self):
        db = _RecordingSession()

        _retrieve_lexical("serum alpha", db, 5, business_id=42)

        statement, params = db.calls[0]
        self.assertIn("d.business_id = :business_id", statement)
        self.assertEqual(42, params["business_id"])

    def test_vector_sql_keeps_business_filter_even_in_schema_bound_session(self):
        db = _RecordingSession()
        with patch("app.rag.retriever._retrieve_lexical", return_value=[]), patch(
            "app.rag.retriever.embed_query",
            return_value=[0.1, 0.2, 0.3],
        ):
            retrieve("serum alpha", db, business_id=73, top_k=3, similarity_threshold=0.1)

        statement, params = db.calls[0]
        self.assertIn("d.business_id = :business_id", statement)
        self.assertEqual(73, params["business_id"])

    def test_lexical_retrieval_excludes_other_tenant_documents(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            one = Business(name="One", slug="one")
            two = Business(name="Two", slug="two")
            db.add_all([one, two])
            db.flush()
            first = Document(business_id=one.id, filename="one.txt", file_type="txt", status="ready")
            second = Document(business_id=two.id, filename="two.txt", file_type="txt", status="ready")
            db.add_all([first, second])
            db.flush()
            db.add_all([
                DocumentChunk(document_id=first.id, content="shared product alpha", chunk_index=0),
                DocumentChunk(document_id=second.id, content="shared product beta", chunk_index=0),
            ])
            db.commit()

            results = _retrieve_lexical("shared product", db, 10, business_id=one.id)

            self.assertEqual([first.id], [result.document_id for result in results])

    def test_lexical_retrieval_drops_weak_single_token_overlap(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Threshold", slug="threshold")
            db.add(business)
            db.flush()
            document = Document(business_id=business.id, filename="policy.txt", file_type="txt", status="ready")
            db.add(document)
            db.flush()
            db.add(DocumentChunk(document_id=document.id, content="gift card available", chunk_index=0))
            db.commit()

            results = _retrieve_lexical(
                "gift customer returns delivery",
                db,
                5,
                business_id=business.id,
                similarity_threshold=0.3,
            )

            self.assertEqual([], results)

    def test_product_recommendation_keeps_multiple_catalog_rows_ahead_of_generic_guides(self):
        """Pink stock queries need actual products, not just relevant policy prose."""
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            shop = Business(name="Catalogue QA", slug="catalogue-qa")
            db.add(shop)
            db.flush()
            guide = Document(business_id=shop.id, filename="guide.md", file_type="md", status="ready")
            catalogue = Document(business_id=shop.id, filename="products.csv", file_type="csv", status="ready")
            db.add_all([guide, catalogue])
            db.flush()
            db.add(DocumentChunk(document_id=guide.id, chunk_index=0,
                                 content="Khách thích đồ hồng còn hàng: xem chính sách sản phẩm.",
                                 metadata_={"topic": "products"}))
            for index, sku in enumerate(("DM-APP-001", "DM-APP-003", "DM-BEA-002")):
                db.add(DocumentChunk(document_id=catalogue.id, chunk_index=index,
                                     content=("sku | product_name_vi | color | demo_stock\n"
                                              f"{sku} | Sản phẩm hồng {index} | hồng | {index + 5}"),
                                     metadata_={"topic": "products"}))
            db.commit()

            with patch("app.rag.retriever.embed_query", side_effect=RuntimeError("offline")):
                chunks = retrieve("Khách thích đồ màu hồng, đang có sản phẩm nào còn hàng?",
                                  db, business_id=shop.id, top_k=4, similarity_threshold=0.1)

            assert len(chunks) == 4
            assert all(chunk.document_id == catalogue.id for chunk in chunks[:3])
            assert {"DM-APP-001", "DM-APP-003", "DM-BEA-002"} == {
                chunk.content.splitlines()[-1].split("|")[0].strip() for chunk in chunks[:3]
            }

    def test_lexical_retrieval_uses_section_heading_for_headingless_chunks(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Section context", slug="section-context")
            db.add(business)
            db.flush()
            document = Document(business_id=business.id, filename="policy.md", file_type="md", status="ready")
            db.add(document)
            db.flush()
            chunk = DocumentChunk(
                document_id=document.id,
                content="Test fee: 30,000 VND for orders below 500,000 VND.",
                chunk_index=0,
                metadata_={"section": "Delivery / Giao hàng", "context": "Section: Delivery / Giao hàng"},
            )
            db.add(chunk)
            db.commit()

            results = _retrieve_lexical("Phí ship đơn hàng bao nhiêu?", db, 5, business_id=business.id)

            self.assertEqual([chunk.id], [result.chunk_id for result in results])

    def test_retriever_normalizes_sqlite_json_metadata_before_parent_expansion(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Metadata", slug="metadata")
            db.add(business)
            db.flush()
            document = Document(business_id=business.id, filename="policy.md", file_type="md", status="ready")
            db.add(document)
            db.flush()
            db.add(DocumentChunk(
                document_id=document.id,
                content="Đổi trả trong vòng 7 ngày; nhân viên xác nhận điều kiện.",
                chunk_index=0,
                metadata_={
                    "topic": "returns",
                    "parent_id": 1,
                    "parent_start": 0,
                    "parent_end": 0,
                },
            ))
            db.commit()

            with patch("app.rag.retriever.embed_query", side_effect=RuntimeError("offline test")):
                results = retrieve(
                    "Chính sách đổi trả trong 7 ngày",
                    db,
                    business_id=business.id,
                    top_k=5,
                    similarity_threshold=0.1,
                )

            self.assertEqual(1, len(results))
            self.assertEqual("returns", results[0].metadata["topic"])

    def test_lexical_retrieval_ranks_relevant_late_chunks_before_candidate_limit(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Large knowledge base", slug="large-knowledge-base")
            db.add(business)
            db.flush()
            document = Document(
                business_id=business.id,
                filename="knowledge.md",
                file_type="md",
                status="ready",
            )
            db.add(document)
            db.flush()
            db.add_all([
                DocumentChunk(
                    document_id=document.id,
                    content="Mẫu demo cần làm bước tiếp theo.",
                    chunk_index=index,
                )
                for index in range(200)
            ])
            db.add(DocumentChunk(
                document_id=document.id,
                content="Thiết bị có mùi khét thì ngừng sử dụng và gọi nhân viên.",
                chunk_index=200,
            ))
            db.commit()

            results = _retrieve_lexical(
                "Thiết bị có mùi khét thì tôi nên làm gì?",
                db,
                5,
                business_id=business.id,
                similarity_threshold=0.3,
            )

            self.assertTrue(results)
            self.assertIn("mùi khét", results[0].content)


if __name__ == "__main__":
    unittest.main()
