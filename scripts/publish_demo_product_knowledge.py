"""Publish the prepared demo knowledge via the existing ingestion pipeline."""
from pathlib import Path
import hashlib
from app.database.tenant_session import tenant_session
from app.models.document import Document
from app.services.ingestion_service import ingest_document

def main():
 data=Path("/tmp/beauty-product-profiles-demo.md").read_bytes()
 with tenant_session("shop_7") as db:
  before={d.id:d.status for d in db.query(Document).filter(Document.business_id==7).all()}
  digest=hashlib.sha256(data).hexdigest()
  doc=db.query(Document).filter_by(business_id=7,content_hash=digest).first()
  if doc is None:
   doc=Document(business_id=7,filename="beauty-product-profiles-demo.md",file_type="md",file_size=len(data),source_bytes=data,content_hash=digest,status="pending")
   db.add(doc);db.commit();db.refresh(doc)
  ok=ingest_document(doc.id,data,doc.filename,db,use_embeddings=True,business_id=7,reindex_only=True)
  db.refresh(doc)
  if not ok or doc.status!="ready" or doc.chunk_count<=0:
   raise RuntimeError(f"Not published; original test document kept unchanged. status={doc.status} error={doc.error_code}")
  old=db.query(Document).filter_by(id=2,business_id=7).first()
  assert old.filename=="01-lam-dep-cham-soc-ca-nhan-ho-so-va-qa.md"
  old.status="disabled";db.commit()
  print(f"Published document={doc.id}, chunks={doc.chunk_count}, embeddings={doc.embedding_status}; document 2 disabled and preserved. Previous availability={before}")
if __name__=="__main__": main()
