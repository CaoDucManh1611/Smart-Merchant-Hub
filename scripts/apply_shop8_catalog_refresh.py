"""Apply the user-approved catalog to existing shop8 SKUs without stock receipts."""
import csv,json,hashlib
from pathlib import Path
from app.database.tenant_session import tenant_session
from app.models.sales import Product
from app.models.document import Document
from app.services.ingestion_service import ingest_document
from app.services.recommendation_catalog_service import sync_product_catalog_entry
from app.api.sales import _import_product_profile

rows=list(csv.DictReader(Path('/tmp/shop8-products.csv').open(encoding='utf-8-sig')))
data=Path('/tmp/shop8-product-knowledge.md').read_bytes()
with tenant_session('shop_8') as db:
 products=db.query(Product).filter_by(business_id=8).all();by_sku={p.sku:p for p in products}
 assert len(rows)==24 and len({r['sku'] for r in rows})==24
 assert set(r['sku'] for r in rows)==set(by_sku), 'SKU mismatch: abort'
 before=[dict(id=p.id,sku=p.sku,name=p.name,description=p.description,price=str(p.price),stock=p.stock_quantity,reserved=p.reserved_quantity,metadata=p.metadata_) for p in products]
 Path('/tmp/shop8-catalog-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
 old=db.query(Document).filter_by(business_id=8,filename='KhoTriThuc_ChamSocCaNhan_ShopMoi.md').first()
 digest=hashlib.sha256(data).hexdigest()
 doc=db.query(Document).filter_by(business_id=8,content_hash=digest).first()
 if doc is None:
  doc=Document(business_id=8,filename='KhoTriThuc_DanhMucMoi_24SanPham.md',file_type='md',file_size=len(data),source_bytes=data,content_hash=digest,status='pending')
  db.add(doc);db.commit();db.refresh(doc)
 if doc.status!='ready':
  ok=ingest_document(doc.id,data,doc.filename,db,use_embeddings=True,business_id=8,reindex_only=True)
  db.refresh(doc)
  assert ok and doc.status=='ready' and doc.chunk_count>0, 'Knowledge ingestion failed; old document remains enabled'
 for row in rows:
  product=by_sku[row['sku']]
  product.name=row['name'];product.description=row['description']
  metadata=dict(product.metadata_ or {});attributes=dict(metadata.get('attributes') or {})
  attributes['category']=[row['category']];metadata['attributes']=attributes
  metadata['product_profile']=_import_product_profile(row)
  product.metadata_=metadata
  sync_product_catalog_entry(db,product,source='user_catalog_refresh')
 if old and old.id!=doc.id:old.status='disabled'
 for previous in before:
  product=by_sku[previous['sku']]
  assert str(product.price)==previous['price'] and product.stock_quantity==previous['stock'] and product.reserved_quantity==previous['reserved']
 db.commit()
 print(json.dumps({'updated':len(rows),'stock_and_prices':'unchanged','knowledge_document':doc.id,'chunks':doc.chunk_count,'embedding_status':doc.embedding_status,'old_document':old.status if old else None}))
