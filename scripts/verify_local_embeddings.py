"""Real-model smoke check; no API keys or customer messages required."""
import math
from app.core.config import settings
from app.rag.embedder import embed_texts, embed_query

def main():
 assert settings.EMBEDDING_PROVIDER=="local"
 docs=["Sữa rửa mặt làm sạch da mặt", "Dầu gội làm sạch tóc và da đầu", "Bảo dưỡng xe máy"]
 vectors=embed_texts(docs)
 query=embed_query("Tôi cần sản phẩm để rửa mặt")
 assert len(vectors)==3 and len(query)==settings.EMBEDDING_DIMENSION
 assert all(len(v)==settings.EMBEDDING_DIMENSION and all(math.isfinite(x) for x in v) for v in vectors)
 scores=[sum(a*b for a,b in zip(query,v)) for v in vectors]
 assert scores.index(max(scores))==0, scores
 print("PASS local embedding:",settings.EMBEDDING_MODEL,"dimension",len(query),"semantic nearest match=face wash")
 from app.database.tenant_session import tenant_session
 from app.rag.retriever import retrieve
 with tenant_session("shop_7") as db:
  diagnostics={}
  rows=retrieve("Sữa rửa mặt làm sạch da mặt",db,7,top_k=3,query_embedding=query,
                diagnostics=diagnostics,retrieval_mode="hybrid",similarity_threshold=0.0)
  assert rows and diagnostics.get("retrieval_vector_hits",0)>0, diagnostics
  print("PASS live hybrid retriever: vector hits",diagnostics["retrieval_vector_hits"],"returned",len(rows))

if __name__=="__main__":main()
