import json
from pathlib import Path
from datetime import datetime
from app.database.tenant_session import tenant_session
from app.services.business_profile import get_business_profile,save_business_profile
from app.schemas.business_profile import CollectionField

with tenant_session('shop_8') as db:
 profile=get_business_profile(db,8)
 backup=Path('/tmp/shop8-business-profile-before-shipping.json')
 if not backup.exists():backup.write_text(json.dumps(profile.model_dump(mode='json'),ensure_ascii=False,indent=2))
 fields=profile.collection_fields['goods']
 for key,label in [('email','Email'),('address','Địa chỉ nhận hàng')]:
  if not any(f.key==key for f in fields):
   fields.insert(max(len(fields)-1,0),CollectionField(key=key,label=label,type='text'))
 save_business_profile(db,8,profile);db.commit()
 print('goods_fields',[f.key for f in profile.collection_fields['goods']])
 print('service_fields',[f.key for f in profile.collection_fields['service']])
