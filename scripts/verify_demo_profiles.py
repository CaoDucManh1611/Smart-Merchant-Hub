"""Read-only checks of the live shop catalog through graph_reply; no messages sent."""
from types import SimpleNamespace
from app.database.tenant_session import tenant_session
from app.models.conversation import Conversation
from app.models.sales import Product
from app.services.conversation_graph import graph_reply
from app.services.product_profile import profile_detail_lines
from app.services.recommendation_artifacts import stated_budget

def main():
 with tenant_session("shop_7") as db:
  prior=db.query(Conversation).filter_by(id=24,business_id=7).first()
  cases=[("nhu cầu rửa mặt và dưới 200k", "Sữa rửa mặt", "Toner"),
    ("gợi ý dầu gội dưới 500000", "Dầu gội", "Sữa rửa mặt"),
    ("nhu cầu dưỡng môi dưới 1000000", "Son dưỡng môi", "Toner"),
    ("cho tôi xem thông tin chi tiết sữa rửa mặt tiêu chuẩn", "Công dụng:", "chưa xác nhận công dụng"),
    ("cho tôi xem có những loại sản phẩm sữa rửa mặt nào v", "Sữa rửa mặt", "Toner")]
  count=0
  for channel in ["zalo","telegram","facebook","instagram","tiktok"]:
   for conversation_id in [prior.id,999999999]:
    c=SimpleNamespace(id=conversation_id,customer_id=prior.customer_id,business_id=7,channel=channel,channel_id=prior.channel_id)
    for query,required,excluded in cases:
     r=graph_reply(db,business_id=7,conversation=c,query=query,job_key=f"profile-readonly-{channel}-{conversation_id}-{count}")
     assert required in r.prompt, (channel,conversation_id,query,r.prompt)
     assert excluded not in r.prompt, (channel,conversation_id,query,r.prompt)
     count+=1
  products=db.query(Product).filter(Product.business_id==7,Product.sku.like("DEMO-BEA-%")).all()
  assert len(products)==40 and all(profile_detail_lines(p) for p in products)
  assert stated_budget("dưới 200k")==200000
  print(f"PASS: {count} graph cases, 5 channel labels, with/without stored history; 40 profiles. No provider messages sent.")
if __name__=="__main__":main()
