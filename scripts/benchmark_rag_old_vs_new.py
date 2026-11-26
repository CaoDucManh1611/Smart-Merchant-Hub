"""A/B in an isolated PostgreSQL schema, rolled back after measurement."""
import json,re,time,statistics
from collections import defaultdict
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.tenant_session import tenant_engine
from app.models.document import Document,DocumentChunk
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping
from app.rag.chunker import Chunk
from app.rag.token_chunker import split_for_encoder
from app.rag.embedder import _get_local_encoder,embed_texts
from app.rag.semantic_chunker import contextual_embedding_text
from app.rag.retriever import retrieve
from app.core.config import settings

QUESTIONS=[
 ("exact","Sữa rửa mặt dịu nhẹ có công dụng gì?",["01"]),
 ("exact","Toner cấp ẩm dùng để làm gì?",["02"]),
 ("exact","Serum niacinamide là nhóm sản phẩm nào?",["03"]),
 ("exact","Kem dưỡng phục hồi có công dụng gì?",["04"]),
 ("exact","Kem chống nắng có tác dụng gì?",["05"]),
 ("exact","Dầu tẩy trang dùng để làm gì?",["06"]),
 ("exact","Mặt nạ đất sét có công dụng gì?",["07"]),
 ("exact","Son dưỡng môi dùng làm gì?",["08"]),
 ("exact","Dầu gội dịu nhẹ có công dụng gì?",["09"]),
 ("exact","Sữa tắm dưỡng ẩm dùng để làm gì?",["10"]),
 ("paraphrase","Tôi muốn làm sạch làn da trên mặt sau một ngày đi đường",["01"]),
 ("paraphrase","Da cần bổ sung độ ẩm, tôi nên tham khảo nhóm nào?",["02","04"]),
 ("paraphrase","Tôi cần chăm sóc da với tinh chất serum",["03"]),
 ("paraphrase","Có món nào dưỡng ẩm cho làn da không?",["02","04"]),
 ("paraphrase","Ra ngoài trời nắng thì dùng món nào hỗ trợ bảo vệ da?",["05"]),
 ("paraphrase","Tôi muốn làm sạch lớp trang điểm buổi tối",["06"]),
 ("paraphrase","Tôi cần chăm sóc da bằng mặt nạ",["07"]),
 ("paraphrase","Môi khô thì tham khảo nhóm chăm sóc nào?",["08"]),
 ("paraphrase","Tóc và da đầu cần được làm sạch thì tìm loại gì?",["09"]),
 ("paraphrase","Dùng gì làm sạch cơ thể khi tắm?",["10"]),
 ("sku","Cho tôi thông tin mã DEMO-BEA-01-1",["01"]),
 ("sku","DEMO-BEA-05-3 thuộc nhóm nào?",["05"]),
 ("sku","Mã DEMO-BEA-08-2 có công dụng gì?",["08"]),
 ("policy","Gửi mã QR có nghĩa đã thanh toán chưa?",["POLICY"]),
 ("policy","Khách muốn hoàn tiền thì cần cung cấp mã gì?",["POLICY"]),
 ("policy","Khách gửi thông tin đặt hàng thành nhiều tin được không?",["POLICY"]),
 ("policy","Shop chưa có căn cứ trả lời thì bot nên làm gì?",["POLICY"]),
 ("no_source","Lãi suất vay mua nhà hôm nay bao nhiêu?",[]),
 ("no_source","Dự báo thời tiết ngày mai tại Hà Nội",[]),
 ("no_source","Giá vé máy bay đi Singapore tuần tới",[]),
]

def main():
 encoder=_get_local_encoder(settings.EMBEDDING_MODEL)
 started=time.perf_counter()
 query_vectors=embed_texts([q for _,q,_ in QUESTIONS])
 query_batch_ms=(time.perf_counter()-started)*1000
 conn=tenant_engine.connect();tx=conn.begin();db=None
 output={"question_count":len(QUESTIONS),"positive_questions":sum(bool(g) for _,_,g in QUESTIONS),
   "model":settings.EMBEDDING_MODEL,"max_tokens":encoder.max_seq_length,"query_batch_ms":query_batch_ms,
   "note":"Retrieval-only benchmark, not generated-answer correctness. Schema changes are uncommitted and rolled back. Latencies exclude precomputed query embedding.","arms":{},"cases":[]}
 try:
  conn.execute(text('CREATE SCHEMA rag_ab_eval_20261125'))
  for table in ["documents","document_chunks","recommendation_catalog_entries","recommendation_catalog_chunk_mappings","recommendation_catalog_attributes","products"]:
   conn.execute(text(f'CREATE TABLE rag_ab_eval_20261125.{table} AS SELECT * FROM shop_7.{table}'))
  conn.execute(text('SET LOCAL search_path TO rag_ab_eval_20261125, public'))
  db=Session(bind=conn,join_transaction_mode="create_savepoint")
  ids=[d.id for d in db.query(Document).filter_by(business_id=7,status="ready")]
  originals=db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(ids)).order_by(DocumentChunk.document_id,DocumentChunk.chunk_index).all()
  originals_data=[{"id":c.id,"document_id":c.document_id,"content":c.content,"index":c.chunk_index,"metadata":dict(c.metadata_ or {})} for c in originals]
  parent_labels={c["id"]:(["POLICY"] if c["document_id"]==3 else re.findall(r"DEMO-BEA-(\d{2})-",c["content"]+" "+str(c["metadata"].get("context","")))) for c in originals_data}
  def evaluate(name,mode):
   metrics=[]
   for i,(group,query,gold) in enumerate(QUESTIONS):
    diag={};start=time.perf_counter()
    rows=retrieve(query,db,7,top_k=3,retrieval_mode=mode,query_embedding=query_vectors[i] if mode=="hybrid" else None,diagnostics=diag)
    elapsed=(time.perf_counter()-start)*1000
    ranked=[]
    for row in rows:
     meta=row.metadata or {};parent=int(meta.get("eval_parent_id",row.chunk_id))
     ranked.append({"chunk_id":row.chunk_id,"parent":parent,"labels":parent_labels.get(parent,[]),"preview":row.content[:160]})
    hits=[bool(set(x["labels"])&set(gold)) for x in ranked]
    reciprocal=next((1/(j+1) for j,h in enumerate(hits) if h),0)
    metrics.append({"group":group,"positive":bool(gold),"hit1":bool(hits and hits[0]),"hit3":any(hits),"mrr":reciprocal,"ms":elapsed,"empty":not rows})
    output["cases"].append({"arm":name,"query":query,"group":group,"expected_labels":gold,"results":ranked,"ms":elapsed,"vector_hits":diag.get("retrieval_vector_hits",0)})
   positives=[m for m in metrics if m["positive"]]
   output["arms"][name]={"mode":mode,"hit1":sum(m["hit1"] for m in positives)/len(positives),"hit3":sum(m["hit3"] for m in positives)/len(positives),"mrr3":sum(m["mrr"] for m in positives)/len(positives),"median_retrieval_ms":statistics.median(m["ms"] for m in metrics),"negative_empty":sum(m["empty"] for m in metrics if not m["positive"]),"groups":{g:{"count":len(ms:=[m for m in metrics if m["group"]==g]),"hit3":sum(m["hit3"] for m in ms)/len(ms)} for g in sorted({m["group"] for m in positives})}}
   print(name,json.dumps(output["arms"][name]),flush=True)
  evaluate("A_old_BM25","bm25")
  evaluate("diagnostic_old_hybrid","hybrid")
  mappings=defaultdict(list)
  for m in db.query(RecommendationCatalogChunkMapping).filter(RecommendationCatalogChunkMapping.document_chunk_id.in_([c["id"] for c in originals_data])):
   mappings[m.document_chunk_id].append((m.catalog_entry_id,m.mapping_type))
  candidate=[]
  for old in originals_data:
   source=Chunk(old["content"],old["index"],old["metadata"])
   for piece in split_for_encoder([source],encoder.tokenizer,encoder.max_seq_length):
    piece.metadata["eval_parent_id"]=old["id"]
    candidate.append((old["document_id"],old["id"],piece))
  vectors=embed_texts([contextual_embedding_text(p) for _,_,p in candidate])
  db.query(RecommendationCatalogChunkMapping).filter(RecommendationCatalogChunkMapping.document_chunk_id.in_([c["id"] for c in originals_data])).delete(synchronize_session=False)
  db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(ids)).delete(synchronize_session=False)
  db.expunge_all();indices=defaultdict(int)
  for i,((docid,parent,piece),vector) in enumerate(zip(candidate,vectors),1):
   cid=-i
   db.add(DocumentChunk(id=cid,document_id=docid,chunk_index=indices[docid],content=piece.content,metadata_=piece.metadata,embedding=vector));indices[docid]+=1
   for j,(entry,kind) in enumerate(mappings[parent]):
    db.add(RecommendationCatalogChunkMapping(id=-(i*100+j+1),catalog_entry_id=entry,document_chunk_id=cid,mapping_type=kind))
  db.flush()
  for d in db.query(Document).filter(Document.id.in_(ids)):d.chunk_count=indices[d.id]
  db.flush()
  output["old_chunks"]=len(originals_data);output["new_chunks"]=len(candidate)
  output["new_max_tokens"]=max(p.metadata["embedding_token_count"] for _,_,p in candidate)
  assert output["new_max_tokens"]<=encoder.max_seq_length
  evaluate("diagnostic_new_BM25","bm25")
  evaluate("B_token_safe_hybrid","hybrid")
 finally:
  if db is not None:db.close()
  if tx.is_active:tx.rollback()
  conn.close()
 output["rolled_back"]=True
 from pathlib import Path
 Path("/app/backups/rag-ab-old-vs-new-20261125.json").write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
 print("DONE; all experimental schema changes rolled back; live configuration unchanged",flush=True)
if __name__=="__main__":main()
