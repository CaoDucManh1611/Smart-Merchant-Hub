"""Rebuild embeddings of active shop_7 knowledge only; preserve source/catalog."""
from app.database.tenant_session import tenant_session
from app.models.document import Document, DocumentChunk
from app.services.ingestion_service import ingest_document
from app.rag.embedder import embed_query

def main():
 with tenant_session("shop_7") as db:
  docs=db.query(Document).filter_by(business_id=7,status="ready").order_by(Document.id).all()
  for doc in docs:
   assert doc.source_bytes, (doc.id,"missing source")
   ok=ingest_document(doc.id,bytes(doc.source_bytes),doc.filename,db,use_embeddings=True,business_id=7,reindex_only=True)
   db.refresh(doc)
   count=db.query(DocumentChunk).filter(DocumentChunk.document_id==doc.id,DocumentChunk.embedding.isnot(None)).count()
   assert ok and doc.embedding_status=="ready" and count==doc.chunk_count, (doc.id,doc.embedding_status,count,doc.chunk_count)
   print("PASS document",doc.id,"vectors",count,flush=True)
  q=embed_query("Sữa rửa mặt giúp làm sạch da mặt")
  rows=db.query(DocumentChunk).join(Document).filter(Document.business_id==7,Document.status=="ready",DocumentChunk.embedding.isnot(None)).order_by(DocumentChunk.embedding.cosine_distance(q)).limit(3).all()
  assert rows and any("sữa rửa mặt" in r.content.lower() for r in rows)
  print("PASS pgvector cosine search: face wash evidence in top 3; active documents",len(docs))
if __name__=="__main__":main()
