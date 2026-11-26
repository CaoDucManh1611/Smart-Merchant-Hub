"""Run inside backend with app imports available; scoped to demo products in shop_7."""
import json
from pathlib import Path
from app.database.tenant_session import tenant_session
from app.models.sales import Product
from app.models.document import Document

FAMILIES = {
 "01": ("Sữa rửa mặt", "Làm sạch da mặt", ["rửa mặt", "sữa rửa mặt", "làm sạch da mặt"]),
 "02": ("Toner", "Bổ sung độ ẩm cho da", ["toner", "cấp ẩm", "dưỡng ẩm"]),
 "03": ("Serum", "Chăm sóc da với serum", ["serum", "chăm sóc da"]),
 "04": ("Kem dưỡng", "Dưỡng ẩm cho da", ["kem dưỡng", "dưỡng ẩm"]),
 "05": ("Kem chống nắng", "Hỗ trợ bảo vệ da khi tiếp xúc ánh nắng", ["kem chống nắng", "chống nắng"]),
 "06": ("Dầu tẩy trang", "Làm sạch lớp trang điểm", ["tẩy trang", "dầu tẩy trang"]),
 "07": ("Mặt nạ đất sét", "Chăm sóc và làm sạch da với mặt nạ", ["mặt nạ", "mặt nạ đất sét"]),
 "08": ("Son dưỡng môi", "Dưỡng ẩm cho môi", ["son dưỡng", "dưỡng môi", "dưỡng ẩm môi"]),
 "09": ("Dầu gội", "Làm sạch tóc và da đầu", ["dầu gội", "gội đầu", "làm sạch tóc"]),
 "10": ("Sữa tắm", "Làm sạch cơ thể", ["sữa tắm", "tắm", "làm sạch cơ thể"]),
}

def main():
 with tenant_session("shop_7") as db:
  products=db.query(Product).filter(Product.business_id==7,Product.sku.like("DEMO-BEA-%")).order_by(Product.sku).all()
  assert products, "No demo catalog found"
  before=[{"id":p.id,"sku":p.sku,"description":p.description,"metadata":p.metadata_} for p in products]
  Path("/tmp/all-demo-profiles-before.json").write_text(json.dumps(before,ensure_ascii=False,indent=2))
  old=db.query(Document).filter_by(id=2,business_id=7).first()
  assert old and old.source_bytes
  Path("/tmp/beauty-70-test-cases.md").write_bytes(old.source_bytes)
  sections=["# Hồ sơ tư vấn danh mục làm đẹp demo", "Nội dung minh họa cho demo; không phải thông tin nhà sản xuất xác nhận. Giá, tồn và trạng thái bán phải tra CRM hiện tại. Không dùng tài liệu này để ghi nhận thanh toán hay cam kết chính sách."]
  for p in products:
   family,benefit,needs=FAMILIES[p.sku.split("-")[2]]
   profile={"demo":True,"category":family,"benefits":[benefit],"suitable_needs":needs,
      "usage":[],"warnings":["Chưa xác nhận thành phần, dung tích, loại da phù hợp và hướng dẫn sử dụng từ nhà sản xuất; cần shop kiểm tra khi khách hỏi."]}
   m=dict(p.metadata_ or {}); m["product_profile"]=profile;p.metadata_=m
   sections.append(f"## {p.sku} — {p.name}\nNhóm: {family}.\nCông dụng minh họa: {benefit}.\nNhu cầu: {'; '.join(needs)}.\nLưu ý: {profile['warnings'][0]}\nKhông suy luận công dụng, dung tích hay chất lượng khác nhau từ tên biến thể. Giá và tồn phải kiểm tra theo SKU này trong CRM.")
  sections.append("## Chính sách và thông tin chưa có\nChưa có chính sách giao hàng, giảm giá, bảo hành và đổi trả được xác nhận trong tài liệu này. Không tự hứa hẹn; nhờ nhân viên shop kiểm tra. Chưa có thông số SPF, nồng độ hoạt chất hay chứng nhận an toàn để tư vấn cụ thể.")
  Path("/tmp/beauty-product-profiles-demo.md").write_text("\n\n".join(sections),encoding="utf-8")
  db.commit()
  print("Updated",len(products),"demo profiles; exported original test document and new knowledge")
if __name__ == "__main__": main()
