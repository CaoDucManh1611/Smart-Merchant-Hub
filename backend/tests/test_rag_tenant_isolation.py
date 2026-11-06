import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database.bases import TenantBase

from app.models.business import Business
from app.models.document import Document, DocumentChunk
from app.rag.retriever import _retrieve_lexical, _retrieval_statement_timeout, retrieve


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


def test_retrieval_statement_timeout_is_transaction_local_and_restored():
    from types import SimpleNamespace

    class ScalarResult:
        def scalar_one(self):
            return "17s"

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, statement, parameters=None):
            self.calls.append((str(statement), dict(parameters or {})))
            return ScalarResult()

    class Savepoint:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class PostgresSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def __init__(self):
            self.connection_value = Connection()

        def begin_nested(self):
            return Savepoint()

        def connection(self):
            return self.connection_value

    db = PostgresSession()

    with _retrieval_statement_timeout(db, 2.5):
        pass

    assert db.connection_value.calls[0][0] == "SHOW statement_timeout"
    assert db.connection_value.calls[1][1] == {"timeout": "2500ms"}
    assert db.connection_value.calls[2][1] == {"timeout": "17s"}


class RagTenantIsolationTests(unittest.TestCase):
    def test_precomputed_query_vector_keeps_tenant_scope_without_provider_calls(self):
        from app.core.config import settings
        db = _RecordingSession()
        diagnostics = {}
        with patch.object(settings, "EMBEDDING_DIMENSION", 3), patch(
            "app.rag.retriever._retrieve_lexical", return_value=[]
        ), patch("app.rag.retriever.embed_query") as provider:
            retrieve("product alpha", db, business_id=73, query_embedding=[0.1, 0.2, 0.3],
                     diagnostics=diagnostics, retrieval_mode="hybrid")
        provider.assert_not_called()
        self.assertEqual(73, db.calls[0][1]["business_id"])
        self.assertEqual("hybrid", diagnostics["retrieval_mode"])

    def test_default_bm25_serving_skips_embedding_and_ppr(self):
        from app.core.config import settings
        from app.rag.retriever import RetrievedChunk

        db = _RecordingSession()
        hit = RetrievedChunk(chunk_id=1, document_id=2, content="policy", similarity=0.8, metadata={})
        diagnostics = {}
        with patch.object(settings, "RAG_RETRIEVAL_MODE", "bm25"), patch(
            "app.rag.retriever._retrieve_lexical", return_value=[hit]
        ), patch("app.rag.retriever._expand_parent_neighbors", side_effect=lambda items, *a, **k: items), patch(
            "app.rag.retriever.embed_query"
        ) as embed, patch("app.rag.retriever._personalized_pagerank_rerank") as ppr:
            results = retrieve("policy question", db, business_id=73, diagnostics=diagnostics)

        embed.assert_not_called()
        ppr.assert_not_called()
        self.assertEqual([hit], results)
        self.assertEqual("bm25", diagnostics["retrieval_mode"])
        self.assertEqual("none", diagnostics["retrieval_reranker"])
        self.assertEqual("bm25_baseline_v1", diagnostics["retrieval_version"])

    def test_hard_sku_filter_is_in_vector_sql_before_limit(self):
        from app.core.config import settings

        db = _RecordingSession()
        with patch.object(settings, "EMBEDDING_DIMENSION", 3), patch(
            "app.rag.retriever._retrieve_lexical", return_value=[]
        ), patch("app.rag.retriever.embed_query", return_value=[0.1, 0.2, 0.3]), patch(
            "app.rag.retriever.sa_inspect"
        ) as inspect:
            inspect.return_value.has_table.return_value = True
            retrieve("SKU-123", db, business_id=73, top_k=3,
                     hard_filters={"sku": "SKU-123"}, retrieval_mode="hybrid")

        statement, params = db.calls[0]
        self.assertLess(statement.index("EXISTS"), statement.index("LIMIT"))
        self.assertIn("rce.business_id = :business_id", statement)
        self.assertIn("rce.sku_norm IN (:hard_filter_sku_0)", statement)
        self.assertEqual(73, params["business_id"])

    def test_lexical_sql_keeps_business_filter_even_in_schema_bound_session(self):
        db = _RecordingSession()

        _retrieve_lexical("serum alpha", db, 5, business_id=42)

        statement, params = db.calls[0]
        self.assertIn("d.business_id = :business_id", statement)
        self.assertEqual(42, params["business_id"])

    def test_lexical_exact_attribute_filter_is_scoped_and_applied_before_limit(self):
        db = _RecordingSession()
        with patch("app.rag.retriever.sa_inspect") as inspect:
            inspect.return_value.has_table.return_value = True
            _retrieve_lexical(
                "áo size L", db, 5, business_id=42,
                hard_filters={"required_attributes": {"size": "L"}},
            )

        statement, params = db.calls[0]
        self.assertLess(statement.index("EXISTS"), statement.index("LIMIT"))
        self.assertIn("rce.business_id = :business_id", statement)
        self.assertIn("rca.key_norm", statement)
        self.assertIn("rca.normalized_value", statement)
        self.assertEqual("l", params["hard_filter_attr_value_0_0"])
        self.assertEqual(42, params["business_id"])

    def test_missing_catalog_mapping_fails_closed_for_structured_attribute(self):
        db = _RecordingSession()
        with patch("app.rag.retriever.sa_inspect") as inspect:
            inspect.return_value.has_table.return_value = False
            _retrieve_lexical("áo size L", db, 5, business_id=42,
                              hard_filters={"required_attributes": {"size": "L"}})
        statement, params = db.calls[0]
        self.assertIn("AND FALSE", statement)
        self.assertEqual(42, params["business_id"])

    def test_vector_sql_keeps_business_filter_even_in_schema_bound_session(self):
        db = _RecordingSession()
        with patch("app.rag.retriever._retrieve_lexical", return_value=[]), patch(
            "app.rag.retriever.embed_query",
            return_value=[0.1, 0.2, 0.3],
        ):
            retrieve("serum alpha", db, business_id=73, top_k=3, similarity_threshold=0.1,
                     retrieval_mode="hybrid")

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
            product_chunks = []
            for index, sku in enumerate(("DM-APP-001", "DM-APP-003", "DM-BEA-002")):
                chunk = DocumentChunk(document_id=catalogue.id, chunk_index=index,
                                      content=("sku | product_name_vi | color | demo_stock\n"
                                               f"{sku} | Sản phẩm hồng {index} | hồng | {index + 5}"),
                                      metadata_={"topic": "products"})
                db.add(chunk)
                product_chunks.append((sku, chunk))
            db.flush()
            from app.services.recommendation_catalog_service import sync_catalog_entry
            for index, (sku, chunk) in enumerate(product_chunks):
                sync_catalog_entry(
                    db,
                    business_id=shop.id,
                    object_type="product",
                    external_id=str(index + 1),
                    name=f"Sản phẩm hồng {index}",
                    sku=sku,
                    attributes={"color": "hồng"},
                    document_chunk_ids=[chunk.id],
                )
            db.commit()

            with patch("app.rag.retriever.embed_query", side_effect=RuntimeError("offline")):
                chunks = retrieve("Khách thích đồ màu hồng, đang có sản phẩm nào còn hàng?",
                                  db, business_id=shop.id, top_k=4, similarity_threshold=0.1)

            assert len(chunks) == 3
            assert all(chunk.document_id == catalogue.id for chunk in chunks[:3])
            assert {"DM-APP-001", "DM-APP-003", "DM-BEA-002"} == {
                chunk.content.splitlines()[-1].split("|")[0].strip() for chunk in chunks[:3]
            }

    def test_catalog_upsert_is_idempotent_for_repeated_attributes_and_chunk_links(self):
        from app.models.recommendation_catalog import (
            RecommendationCatalogAttribute,
            RecommendationCatalogChunkMapping,
        )
        from app.services.recommendation_catalog_service import sync_catalog_entry

        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
        TenantBase.metadata.create_all(engine)
        with Session(engine) as db:
            business = Business(name="Catalog reindex", slug="catalog-reindex")
            db.add(business)
            db.flush()
            document = Document(business_id=business.id, filename="products.csv", file_type="csv", status="ready")
            db.add(document)
            db.flush()
            chunk = DocumentChunk(document_id=document.id, chunk_index=0, content="SKU-1 | Volume 1 lít")
            db.add(chunk)
            db.flush()

            for _ in range(2):
                sync_catalog_entry(
                    db,
                    business_id=business.id,
                    object_type="product",
                    external_id="1",
                    name="Drink",
                    sku="SKU-1",
                    attributes={"volume": ["1 lít", "1 lít"], "color": "clear"},
                    document_chunk_ids=[chunk.id],
                )

            db.commit()
            self.assertEqual(2, db.query(RecommendationCatalogAttribute).count())
            self.assertEqual(1, db.query(RecommendationCatalogChunkMapping).count())

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
