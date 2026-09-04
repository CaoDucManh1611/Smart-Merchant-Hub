import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.document import Document, DocumentChunk
from app.rag.retriever import _retrieve_lexical


class RagTenantIsolationTests(unittest.TestCase):
    def test_lexical_retrieval_excludes_other_tenant_documents(self):
        engine = create_engine("sqlite://")
        Business.metadata.create_all(engine)
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
