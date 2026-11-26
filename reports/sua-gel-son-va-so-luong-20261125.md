# Sửa nhóm gel, tên son rút gọn và đặt hàng tham chiếu
- Lỗi tái hiện: Các loại gel dưỡng ẩm bị giao choLLM chọn Gel rửa mặt; son môi không màu thiếu từ dưỡng không được nhận diện; câu Ok cho tôi đặt1cái nha bị lexicalmatch từ đặt vào đất sét, chọnMND-030; mua2cái đi không được parserquantity nhận.
- Duyệt nhóm: đối chiếu nguyên cụm khách hỏi với tên và category của đúngshop trước gọiAI. Không thay sang nhóm chỉ khớp một từgel.
- Chi tiết: cho phép bỏ1từ nội bộ của tên khi còn>=3từ liên tiếp trong câu khách, giữ thứ tự tên và phầnngữpháp; tên mơ hồ vẫn hỏi lại.
- Đặt hàng: câu có động từ mua/đặt, số lượng và đơn vị nhưng không tên hàng là thamchiếu; ưu tiênprovenance SKU của tinbot vừa xem trướclexical, không cócontext thì hỏi lại. Không cần gọiAI cho dạngnày. Bổ sung tiểu từđi cho yêu cầu sửa sốlượng.
- Kiểm thử:3ca mới thất bại trước sửa; sau sửa5ca gồmtoàn graph, không cóngữcảnh, nhómgel, thiếu1từ, đặt1→mua2 đạt. Suite rộng231pass; 2casauđược thêm vàtest riêng (không cộng trùng).
- Readonlyshop8: Gel dưỡngbanngày119000 vàbanđêm179000, khôngcógelrửamặt; sonkhôngmàu59000 đúngchitiết.
- Đóngsession6 shop8 conversation28, purposeorder_confirmation pending, đúngcartwrongproduct17 qty1. Chuyểnabandoned; giữitems/dấuvết/audit vàbackup; hủyreminder củaquote. Không sửađơnbán/tồn. User cần chọnlại son rõtên đểkhông thamchiếutinquote lỗi tronglịchsử.
- Đã restartbackendworker. Chưa gửi tin quakênhkhách hoặc tạo đơn thật.
