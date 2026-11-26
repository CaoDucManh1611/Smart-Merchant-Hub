# 01. Làm đẹp & chăm sóc cá nhân

> Dữ liệu giả lập để kiểm thử. Không dùng làm chính sách hoặc lời hứa với khách thật.

## Hồ sơ ngành

- Đơn vị catalogue: chai/tuýp.
- Thuộc tính cần xác nhận: dung tích, loại da, thành phần, hạn dùng, cách dùng.
- Ý định khách thường gặp: loại da, thứ tự dùng, dị ứng, hạn dùng.
- Cách gọi sản phẩm mẫu: Sữa rửa mặt dịu nhẹ, Toner cấp ẩm, Serum niacinamide, Kem dưỡng phục hồi, Kem chống nắng, Dầu tẩy trang, Mặt nạ đất sét, Son dưỡng môi, Dầu gội dịu nhẹ, Sữa tắm dưỡng ẩm.
- Lưu ý: Không khẳng định điều trị bệnh da; thử vùng nhỏ trước khi dùng.
- Giá, tồn và trạng thái phải tra từ catalogue theo SKU; tài liệu này không có giá cố định.
- Giao hàng, đổi trả, bảo hành, thanh toán và lịch hẹn chỉ trả lời từ chính sách đã được shop phê duyệt.

## 35 câu theo mức được giao

### 01. Shop có Sữa rửa mặt dịu nhẹ bản Tiêu chuẩn không?

**Đáp án kỳ vọng:** Có SKU DEMO-BEA-01-1 — Sữa rửa mặt dịu nhẹ – Tiêu chuẩn, trạng thái active trong catalogue demo.

### 02. Sữa rửa mặt dịu nhẹ bản Tiêu chuẩn giá bao nhiêu?

**Đáp án kỳ vọng:** Theo CSV demo, SKU DEMO-BEA-01-1 giá 119,000 đồng. Khi nhập shop thật phải tra giá hiện thời.

### 03. Sữa rửa mặt dịu nhẹ bản Tiêu chuẩn còn bao nhiêu?

**Đáp án kỳ vọng:** Theo CSV demo, SKU DEMO-BEA-01-1 tồn 9 đơn vị. Khi vận hành phải tra tồn hiện thời.

### 04. Có Toner cấp ẩm bản Tiêu chuẩn không?

**Đáp án kỳ vọng:** Có SKU DEMO-BEA-02-1 — Toner cấp ẩm – Tiêu chuẩn, giá demo 142,000 đồng.

### 05. So sánh giá Sữa rửa mặt dịu nhẹ bản Tiêu chuẩn và Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-01-1 giá 119,000 đồng; SKU DEMO-BEA-01-2 giá 238,000 đồng trong CSV demo.

### 06. Có màu nào?

**Đáp án kỳ vọng:** Hỏi tên hoặc SKU rồi đọc cột Màu; không tự tạo màu chưa có.

### 07. Có kích thước nào?

**Đáp án kỳ vọng:** Hỏi sản phẩm cụ thể rồi đọc cột Kích thước hoặc thông số tương ứng.

### 08. Mẫu nào rẻ nhất?

**Đáp án kỳ vọng:** Lọc sản phẩm đang bán và còn hàng trong catalogue, rồi so giá theo cùng đơn vị.

### 09. Mẫu nào phù hợp với tôi?

**Đáp án kỳ vọng:** Hỏi nhu cầu và các thông số liên quan: dung tích, loại da, thành phần, hạn dùng, cách dùng; đề xuất tối đa ba SKU có dữ liệu phù hợp.

### 10. Có mẫu cao cấp hơn không?

**Đáp án kỳ vọng:** So sánh các biến thể cùng nhóm theo giá và thuộc tính; không mặc định giá cao hơn là tốt hơn.

### 11. Có bộ đôi không?

**Đáp án kỳ vọng:** Tìm biến thể Bộ đôi của đúng mẫu; xác nhận giá, số lượng và tồn kho theo SKU.

### 12. Có giao hàng không?

**Đáp án kỳ vọng:** Chỉ trả lời theo chính sách giao hàng đã được shop xác nhận; nếu chưa có, chuyển nhân viên.

### 13. Phí vận chuyển bao nhiêu?

**Đáp án kỳ vọng:** Cần địa chỉ nhận, phương thức giao và bảng phí thực tế; không tự bịa mức phí.

### 14. Bao lâu nhận được?

**Đáp án kỳ vọng:** Cần khu vực giao và chính sách vận chuyển hiện hành; không hứa ngày nhận khi chưa xác nhận.

### 15. Có được đổi trả không?

**Đáp án kỳ vọng:** Đọc chính sách đổi trả chính thức của shop; hỏi ngày mua, tình trạng và chứng từ nếu cần.

### 16. Bảo hành bao lâu?

**Đáp án kỳ vọng:** Đọc thời hạn bảo hành theo SKU hoặc chính sách đã duyệt; không dùng thời hạn giả định.

### 17. Có hóa đơn không?

**Đáp án kỳ vọng:** Chuyển nhân viên kiểm tra loại hóa đơn và thông tin người mua trước khi xác nhận.

### 18. Đặt nhiều có giảm giá không?

**Đáp án kỳ vọng:** Hỏi số lượng và chuyển nhân viên báo giá sỉ; không tự áp chiết khấu.

### 19. Thanh toán thế nào?

**Đáp án kỳ vọng:** Đọc phương thức thanh toán được shop bật; không gửi số tài khoản ngoài dữ liệu đã duyệt.

### 20. Có thể giữ hàng không?

**Đáp án kỳ vọng:** Chỉ giữ hàng hoặc chỗ khi nhân viên xác nhận quy trình và thời hạn giữ.

### 21. Có thể đặt trước không?

**Đáp án kỳ vọng:** Hỏi SKU và số lượng; nhân viên xác nhận lịch có hàng và điều kiện đặt trước.

### 22. Tôi muốn hủy đơn?

**Đáp án kỳ vọng:** Xác minh đơn và chuyển đúng quy trình hủy; không tự hứa hoàn tiền.

### 23. Tôi muốn gặp nhân viên?

**Đáp án kỳ vọng:** Ghi nhận nhu cầu và chuyển cho nhân viên của shop.

### 24. Có sản phẩm tương tự?

**Đáp án kỳ vọng:** Tìm theo danh mục và thuộc tính; chỉ giới thiệu SKU đang bán và còn hàng.

### 25. Thông tin trên ảnh có đúng không?

**Đáp án kỳ vọng:** Ưu tiên catalogue và chính sách đã duyệt; hỏi ảnh hoặc SKU nếu hai nguồn mâu thuẫn.

### 26. Giá hôm qua có còn không?

**Đáp án kỳ vọng:** Giá hiện tại lấy từ catalogue; chương trình cũ cần nhân viên xác nhận.

### 27. Có thể dùng cho trẻ em không?

**Đáp án kỳ vọng:** Kiểm tra giới hạn độ tuổi và cảnh báo trên nhãn; nếu thiếu, không khẳng định an toàn.

### 28. Có gây dị ứng không?

**Đáp án kỳ vọng:** Cung cấp thành phần đã ghi, khuyên kiểm tra nhãn và hỏi chuyên gia khi có tiền sử dị ứng.

### 29. Có hướng dẫn sử dụng không?

**Đáp án kỳ vọng:** Đọc hướng dẫn theo đúng SKU/tài liệu nhà cung cấp; nếu thiếu, báo chưa có thông tin.

### 30. Hàng này có chính hãng không?

**Đáp án kỳ vọng:** Chỉ xác nhận khi shop có chứng từ/nguồn nhập đã được duyệt; không tự cam kết.

### 31. Da nhạy cảm dùng serum nào?

**Đáp án kỳ vọng:** Hỏi thành phần và tiền sử kích ứng; chỉ đề xuất SKU có thông tin phù hợp.

### 32. Kem chống nắng dùng trước hay sau kem dưỡng?

**Đáp án kỳ vọng:** Theo hướng dẫn chung, dùng sau kem dưỡng buổi sáng; kiểm tra chỉ dẫn từng sản phẩm.

### 33. Serum niacinamide có nồng độ bao nhiêu?

**Đáp án kỳ vọng:** Catalogue demo chưa ghi nồng độ; cần kiểm tra nhãn sản phẩm.

### 34. Có mỹ phẩm không hương liệu?

**Đáp án kỳ vọng:** Chỉ lọc khi trường thành phần xác nhận không hương liệu; nếu thiếu thì hỏi nhân viên.

### 35. Mỹ phẩm đã mở nắp dùng bao lâu?

**Đáp án kỳ vọng:** Theo ký hiệu PAO/hạn dùng trên bao bì từng lô; không suy từ ngày nhập CSV.

## 35 câu bổ sung để kiểm thử catalogue

### 36. Sữa rửa mặt dịu nhẹ – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-01-3, giá demo 357,000 đồng.

### 37. Còn mấy đơn vị Sữa rửa mặt dịu nhẹ – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-01-2 tồn demo 14; khi trả lời khách phải tra tồn hiện thời.

### 38. Sữa rửa mặt dịu nhẹ – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-01-4 có trạng thái active và tồn demo 24. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 39. Bản Tiêu chuẩn hay Nâng cao của Sữa rửa mặt dịu nhẹ rẻ hơn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-01-1 giá 119,000 đồng; SKU DEMO-BEA-01-3 giá 357,000 đồng. Bản Tiêu chuẩn rẻ hơn 238,000 đồng trong CSV demo.

### 40. Toner cấp ẩm – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-02-3, giá demo 426,000 đồng.

### 41. Còn mấy đơn vị Toner cấp ẩm – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-02-2 tồn demo 17; khi trả lời khách phải tra tồn hiện thời.

### 42. Toner cấp ẩm – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-02-4 có trạng thái active và tồn demo 27. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 43. Bản Tiêu chuẩn hay Nâng cao của Toner cấp ẩm rẻ hơn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-02-1 giá 142,000 đồng; SKU DEMO-BEA-02-3 giá 426,000 đồng. Bản Tiêu chuẩn rẻ hơn 284,000 đồng trong CSV demo.

### 44. Serum niacinamide – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-03-3, giá demo 495,000 đồng.

### 45. Còn mấy đơn vị Serum niacinamide – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-03-2 tồn demo 20; khi trả lời khách phải tra tồn hiện thời.

### 46. Serum niacinamide – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-03-4 có trạng thái active và tồn demo 2. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 47. Bản Tiêu chuẩn hay Nâng cao của Serum niacinamide rẻ hơn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-03-1 giá 165,000 đồng; SKU DEMO-BEA-03-3 giá 495,000 đồng. Bản Tiêu chuẩn rẻ hơn 330,000 đồng trong CSV demo.

### 48. Kem dưỡng phục hồi – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-04-3, giá demo 564,000 đồng.

### 49. Còn mấy đơn vị Kem dưỡng phục hồi – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-04-2 tồn demo 23; khi trả lời khách phải tra tồn hiện thời.

### 50. Kem dưỡng phục hồi – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-04-4 có trạng thái active và tồn demo 5. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 51. Bản Tiêu chuẩn hay Nâng cao của Kem dưỡng phục hồi rẻ hơn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-04-1 giá 188,000 đồng; SKU DEMO-BEA-04-3 giá 564,000 đồng. Bản Tiêu chuẩn rẻ hơn 376,000 đồng trong CSV demo.

### 52. Kem chống nắng – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-05-3, giá demo 633,000 đồng.

### 53. Còn mấy đơn vị Kem chống nắng – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-05-2 tồn demo 26; khi trả lời khách phải tra tồn hiện thời.

### 54. Kem chống nắng – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-05-4 có trạng thái active và tồn demo 8. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 55. Bản Tiêu chuẩn hay Nâng cao của Kem chống nắng rẻ hơn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-05-1 giá 211,000 đồng; SKU DEMO-BEA-05-3 giá 633,000 đồng. Bản Tiêu chuẩn rẻ hơn 422,000 đồng trong CSV demo.

### 56. Dầu tẩy trang – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-06-3, giá demo 702,000 đồng.

### 57. Còn mấy đơn vị Dầu tẩy trang – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-06-2 tồn demo 1; khi trả lời khách phải tra tồn hiện thời.

### 58. Dầu tẩy trang – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-06-4 có trạng thái active và tồn demo 11. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 59. Mặt nạ đất sét – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-07-3, giá demo 771,000 đồng.

### 60. Còn mấy đơn vị Mặt nạ đất sét – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-07-2 tồn demo 4; khi trả lời khách phải tra tồn hiện thời.

### 61. Mặt nạ đất sét – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-07-4 có trạng thái active và tồn demo 14. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 62. Son dưỡng môi – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-08-3, giá demo 840,000 đồng.

### 63. Còn mấy đơn vị Son dưỡng môi – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-08-2 tồn demo 7; khi trả lời khách phải tra tồn hiện thời.

### 64. Son dưỡng môi – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-08-4 có trạng thái active và tồn demo 17. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 65. Dầu gội dịu nhẹ – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-09-3, giá demo 909,000 đồng.

### 66. Còn mấy đơn vị Dầu gội dịu nhẹ – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-09-2 tồn demo 10; khi trả lời khách phải tra tồn hiện thời.

### 67. Dầu gội dịu nhẹ – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-09-4 có trạng thái active và tồn demo 0. Chỉ nhận đơn khi trạng thái active và còn tồn.

### 68. Sữa tắm dưỡng ẩm – Nâng cao giá bao nhiêu, mã nào?

**Đáp án kỳ vọng:** SKU DEMO-BEA-10-3, giá demo 978,000 đồng.

### 69. Còn mấy đơn vị Sữa tắm dưỡng ẩm – Nhỏ gọn?

**Đáp án kỳ vọng:** SKU DEMO-BEA-10-2 tồn demo 13; khi trả lời khách phải tra tồn hiện thời.

### 70. Sữa tắm dưỡng ẩm – Bộ đôi hiện có bán không?

**Đáp án kỳ vọng:** SKU DEMO-BEA-10-4 có trạng thái archived và tồn demo 23. Chỉ nhận đơn khi trạng thái active và còn tồn.
