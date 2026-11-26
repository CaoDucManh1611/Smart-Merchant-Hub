"""Replay actual Oanh conversation prefixes against three isolated graph variants.
No channel send is permitted; both tenant and platform writes are rolled back.
"""
import json,hashlib,time,logging,copy,sys
from pathlib import Path
from collections import defaultdict
from contextlib import ExitStack
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.tenant_session import tenant_engine
from app.database.platform_session import platform_engine,PlatformSession
from app.models.message import Message
from app.models.conversation import Conversation
from app.models.document import Document,DocumentChunk
from app.models.customer_collection import CustomerCollectionSession
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping
from app.rag.chunker import Chunk
from app.rag.token_chunker import split_for_encoder
from app.rag.semantic_chunker import contextual_embedding_text
from app.rag.embedder import _get_local_encoder,embed_texts
from app.core.config import settings
from app.services.conversation_graph import graph_reply
import app.rag.serving as serving
import app.rag.output_contracts as contracts
import app.services.conversation_graph as graphmod

logging.basicConfig(level=logging.WARNING)
OUT=Path('/app/backups/oanh-three-methods-20261125.json')

def clone(conn,source,target):
 conn.execute(text(f'CREATE SCHEMA {target}'))
 sequences=conn.execute(text("SELECT sequencename FROM pg_sequences WHERE schemaname=:s"),{'s':source}).scalars().all()
 for name in sequences:
  conn.execute(text(f'CREATE SEQUENCE {target}."{name}"'))
  current=conn.execute(text(f'SELECT last_value FROM {source}."{name}"')).scalar()
  conn.execute(text(f"SELECT setval('{target}.\"{name}\"',:v,true)"),{'v':max(1,current)})
 tables=conn.execute(text('SELECT tablename FROM pg_tables WHERE schemaname=:s ORDER BY tablename'),{'s':source}).scalars().all()
 for table in tables:
  conn.execute(text(f'CREATE TABLE {target}."{table}" (LIKE {source}."{table}" INCLUDING ALL)'))
  defaults=conn.execute(text("SELECT a.attname,pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=CAST(:rel AS regclass)"),{'rel':source+'.'+table}).all()
  for col,expr in defaults:
   if 'nextval(' in expr:
    seqname=expr.split("'")[1].split('.')[-1].strip('"')
    conn.execute(text(f'ALTER TABLE {target}."{table}" ALTER COLUMN "{col}" SET DEFAULT nextval(\'{target}."{seqname}"\'::regclass)'))
  conn.execute(text(f'INSERT INTO {target}."{table}" SELECT * FROM {source}."{table}"'))
  # Live rows can arrive between copying sequences and copying tables.
  # Reseed only private sequences above copied IDs; never touch shop sequences.
  for col,expr in defaults:
   if 'nextval(' in expr:
    seqname=expr.split("'")[1].split('.')[-1].strip('"')
    maximum=conn.execute(text(f'SELECT COALESCE(MAX("{col}"),0) FROM {target}."{table}"')).scalar()
    conn.execute(text(f"SELECT setval('{target}.\"{seqname}\"',:v,true)"),{'v':max(1,maximum+1000)})
 conn.execute(text(f'SET LOCAL search_path TO {target}, public'))
 return tables

def main():
 encoder=_get_local_encoder(settings.EMBEDDING_MODEL)
 tc=tenant_engine.connect();tt=tc.begin();pc=platform_engine.connect();pt=pc.begin()
 report={'conversation_id':26,'design':'historical-prefix replay: same original preceding messages for all arms; no provider delivery; identical structured-model prompts share cache','arms':{},'cases':[],'remote_structured_calls':0,'cache_hits':0}
 cache={};active={};candidate=[];retrieval_events=[]
 real_completion=contracts.graph_json_completion
 real_retrieve=serving.retrieve_shop_knowledge
 def completion(messages,**kwargs):
  key=hashlib.sha256(json.dumps({'messages':messages,'schema':kwargs.get('schema'),'name':kwargs.get('name')},ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
  if key in cache:
   report['cache_hits']+=1
   return cache[key]
  value=real_completion(messages,**kwargs)
  cache[key]=value;report['remote_structured_calls']+=1
  return value
 def retrieve(**kwargs):
  kwargs['retrieval_mode']=active['mode']
  started=time.perf_counter()
  try:
   rows=real_retrieve(**kwargs)
   retrieval_events.append({'query':kwargs['query'],'count':len(rows),'mode':active['mode'],'ms':(time.perf_counter()-started)*1000,'diagnostics':dict(kwargs.get('diagnostics') or {})})
   return rows
  except Exception as e:
   retrieval_events.append({'mode':active['mode'],'error':type(e).__name__});raise
 def forbidden_send(*args,**kwargs):raise AssertionError('External delivery forbidden in isolated evaluation')
 def platform_factory():
  return PlatformSession(bind=pc,join_transaction_mode='create_savepoint',expire_on_commit=False)
 try:
  print('Cloning tenant and platform into uncommitted isolated schemas',flush=True)
  report['tenant_tables']=len(clone(tc,'shop_7','oanh_eval_tenant_20261125'))
  report['platform_tables']=len(clone(pc,'public','oanh_eval_platform_20261125'))
  with Session(bind=tc,join_transaction_mode='create_savepoint') as db:
   source=db.query(Message).filter(Message.conversation_id==26,Message.id<=17760).order_by(Message.id).all()
   source_data=[{'id':m.id,'direction':m.direction,'sender_type':m.sender_type,'content':m.content,'at':str(m.received_at)} for m in source]
   turns=[];pending=[]
   for m in source_data:
    if m['direction']=='inbound' and m['sender_type']=='customer':pending.append(m)
    elif pending:
     turns.append({'id':pending[-1]['id'],'query':'\n'.join(m['content'] or '' for m in pending),'source_ids':[m['id'] for m in pending]});pending=[]
   if pending:turns.append({'id':pending[-1]['id'],'query':'\n'.join(m['content'] or '' for m in pending),'source_ids':[m['id'] for m in pending]})
   report['messages']=len(source_data);report['turns']=len(turns)
   dids=[d.id for d in db.query(Document).filter_by(business_id=7,status='ready')]
   old=[{'id':c.id,'doc':c.document_id,'content':c.content,'index':c.chunk_index,'metadata':dict(c.metadata_ or {})} for c in db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(dids)).all()]
   for c in old:
    for piece in split_for_encoder([Chunk(c['content'],c['index'],c['metadata'])],encoder.tokenizer,encoder.max_seq_length):candidate.append((c['doc'],c['id'],piece))
   maps=defaultdict(list)
   for m in db.query(RecommendationCatalogChunkMapping).filter(RecommendationCatalogChunkMapping.document_chunk_id.in_([c['id'] for c in old])):maps[m.document_chunk_id].append((m.catalog_entry_id,m.mapping_type))
  vectors=embed_texts([contextual_embedding_text(p) for _,_,p in candidate])
  report.update(old_chunks=len(old),new_chunks=len(candidate),new_max_tokens=max(p.metadata['embedding_token_count'] for _,_,p in candidate))
  with ExitStack() as stack:
   stack.enter_context(patch('app.database.platform_session.PlatformSessionLocal',platform_factory))
   stack.enter_context(patch.object(graphmod,'graph_json_completion',completion))
   stack.enter_context(patch.object(serving,'retrieve_shop_knowledge',retrieve))
   stack.enter_context(patch('app.services.auto_reply_service._send_channel_reply',forbidden_send))
   stack.enter_context(patch('app.services.auto_reply_service.send_text_reply',forbidden_send))
   for name,mode,new in [('A_old_BM25','bm25',False),('B_token_hybrid','hybrid',True),('C_token_BM25','bm25',True)]:
    arm_t=tc.begin_nested();arm_p=pc.begin_nested();active['mode']=mode
    if new:
     with Session(bind=tc,join_transaction_mode='create_savepoint') as db:
      db.query(RecommendationCatalogChunkMapping).filter(RecommendationCatalogChunkMapping.document_chunk_id.in_([c['id'] for c in old])).delete(synchronize_session=False)
      db.query(DocumentChunk).filter(DocumentChunk.document_id.in_(dids)).delete(synchronize_session=False)
      indices=defaultdict(int)
      for i,((doc,parent,piece),v) in enumerate(zip(candidate,vectors),1):
       db.add(DocumentChunk(id=-i,document_id=doc,chunk_index=indices[doc],content=piece.content,embedding=v,metadata_=piece.metadata));indices[doc]+=1
       for j,(entry,kind) in enumerate(maps[parent]):db.add(RecommendationCatalogChunkMapping(id=-(i*100+j+1),catalog_entry_id=entry,document_chunk_id=-i,mapping_type=kind))
      db.flush()
      for d in db.query(Document).filter(Document.id.in_(dids)):d.chunk_count=indices[d.id]
      db.commit()
    for turn in turns:
     case_t=tc.begin_nested();case_p=pc.begin_nested();retrieval_events.clear();start=time.perf_counter()
     row={'arm':name,**turn}
     try:
      with Session(bind=tc,join_transaction_mode='create_savepoint',expire_on_commit=False) as db,platform_factory() as pdb:
       db.info['tenant_schema']='oanh_eval_tenant_20261125'
       db.query(Message).filter(Message.conversation_id==26,Message.id>turn['id']).delete(synchronize_session=False)
       db.query(CustomerCollectionSession).filter_by(conversation_id=26).delete(synchronize_session=False)
       c=db.query(Conversation).filter_by(id=26,business_id=7).one()
       c.bot_mode='auto'
       # Remove the later ticket so early questions cannot see future handoff state.
       tc.execute(text('DELETE FROM tickets WHERE conversation_id=26'))
       db.flush()
       result=graph_reply(db,business_id=7,conversation=c,query=turn['query'],job_key='26:'+str(turn['id']),platform_db=pdb)
       row.update(status=getattr(result,'status',None),answer=getattr(result,'prompt',None),metadata=getattr(result,'metadata',None))
     except Exception as e:
      row.update(error=type(e).__name__,error_detail=str(e)[:180],answer=None)
     finally:
      if case_t.is_active:case_t.rollback()
      if case_p.is_active:case_p.rollback()
     row.update(retrieval=copy.deepcopy(retrieval_events),ms=(time.perf_counter()-start)*1000)
     report['cases'].append(row)
     OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
     print(name,turn['id'],row.get('status') or row.get('error'),'rag_calls='+str(len(retrieval_events)),str(row.get('answer') or '')[:120],flush=True)
    if arm_t.is_active:arm_t.rollback()
    if arm_p.is_active:arm_p.rollback()
    rows=[r for r in report['cases'] if r['arm']==name]
    report['arms'][name]={'turns':len(rows),'errors':sum(bool(r.get('error')) for r in rows),'retrieval_turns':sum(bool(r['retrieval']) for r in rows)}
 finally:
  if tt.is_active:tt.rollback()
  if pt.is_active:pt.rollback()
  tc.close();pc.close()
 report['rolled_back']=True
 OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
 print('DONE',json.dumps(report['arms']),flush=True)
if __name__=='__main__':main()
