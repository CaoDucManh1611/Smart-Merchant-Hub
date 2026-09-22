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


if __name__ == "__main__":
    unittest.main()
